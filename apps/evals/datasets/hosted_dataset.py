"""Export scored eval snapshots to retryable hosted Langfuse datasets."""

import hashlib
import json
import math
import operator
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx
from langfuse.api import NotFoundError
from langfuse.api.client import AsyncLangfuseAPI
from pydantic import BaseModel, ConfigDict, Field, field_validator
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter

from apps.evals.evaluators.answers import summarize_answers
from apps.evals.evaluators.retrieval import RECALL_KS, summarize_retrieval
from apps.evals.models import EvalCase, EvalRunResponse, EvalSource
from apps.evals.workflow import EvalRunRequest
from backend.config import Settings

OPERATORS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
}


class ScoreFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1, description="Evaluator key, e.g. answer_correctness"
    )
    operator: Literal["eq", "ne", "lt", "lte", "gt", "gte"] = "eq"
    value: float = Field(allow_inf_nan=False, strict=True)
    score_field: str = Field(default="correctness", min_length=1)

    @field_validator("name", "score_field")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("score names must not be blank")
        return value


def matches(result: dict, filters: list[ScoreFilter]) -> bool:
    for condition in filters:
        score = (
            result.get("evaluators", {})
            .get(condition.name, {})
            .get(condition.score_field)
        )
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not OPERATORS[condition.operator](score, condition.value)
        ):
            return False
    return True


async def case_snapshot(api, result: dict) -> EvalCase:
    payload = result.get("case")
    if payload is None:
        # Older runs recorded the immutable input in the eval_case observation.
        trace_id = result.get("trace_id")
        if not trace_id:
            raise ValueError("Selected case has no snapshot or eval trace")
        trace = await api.trace.get(trace_id)
        candidates = [o.input for o in trace.observations if o.name == "eval_case"]
        if len(candidates) != 1:
            raise ValueError("Cannot resolve a unique original eval case snapshot")
        payload = candidates[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
    case = EvalCase.model_validate(payload)
    if case.case_id != result["case_id"]:
        raise ValueError("Snapshot case_id does not match eval result")
    return case


async def export_dataset(
    run_id: str, results: list[dict], filters: list[ScoreFilter], dataset_name: str
) -> dict:
    if not filters:
        raise ValueError("score_filters must not be empty")
    if not dataset_name.strip():
        raise ValueError("dataset_name must not be blank")
    selected = [r for r in results if matches(r, filters)]
    response = {
        "dataset_name": dataset_name,
        "matched_count": len(selected),
        "created_count": 0,
        "existing_count": 0,
        "failures": [],
    }
    if not selected:
        return {**response, "status": "NO_MATCHES"}
    settings = Settings()
    secret = settings.langfuse_secret_key
    if not settings.langfuse_public_key or not secret or not secret.get_secret_value():
        raise ValueError("Dataset export requires Langfuse public and secret keys")
    specification = {
        "run_id": run_id,
        "score_filters": sorted(
            [f.model_dump() for f in filters],
            key=lambda f: json.dumps(f, sort_keys=True),
        ),
    }
    fingerprint = hashlib.sha256(
        json.dumps(specification, sort_keys=True).encode()
    ).hexdigest()
    try:
        async with httpx.AsyncClient(
            timeout=settings.timeout_dataset_export_http_seconds
        ) as transport:
            api = AsyncLangfuseAPI(
                base_url=settings.langfuse_base_url,
                username=settings.langfuse_public_key,
                password=secret.get_secret_value(),
                httpx_client=transport,
            )
            # Resolve every snapshot before making any writes.
            cases = [await case_snapshot(api, r) for r in selected]
            if len({c.case_id for c in cases}) != len(cases):
                raise ValueError("Duplicate selected case_id")
            try:
                dataset = await api.datasets.get(quote(dataset_name, safe=""))
            except NotFoundError:
                dataset = await api.datasets.create(
                    name=dataset_name,
                    description=f"Filtered cases from {run_id}",
                    metadata={**specification, "eval_export_fingerprint": fingerprint},
                )
            if (dataset.metadata or {}).get("eval_export_fingerprint") != fingerprint:
                raise ValueError("Dataset name already exists for a different export")
            response["dataset_id"] = dataset.id
            # Link resolution is optional and must not prevent an export.
            try:
                projects = await api.projects.get()
                if len(projects.data) == 1:
                    response["dataset_url"] = (
                        settings.langfuse_base_url.rstrip("/")
                        + f"/project/{quote(projects.data[0].id, safe='')}"
                        + f"/datasets/{quote(dataset.id, safe='')}"
                    )
            except Exception:
                pass
            existing = set()
            page = 1
            while True:
                items = await api.dataset_items.list(
                    dataset_name=dataset_name, page=page, limit=100
                )
                existing.update(i.id for i in items.data)
                if page >= items.meta.total_pages:
                    break
                page += 1
            for result, case in zip(selected, cases, strict=True):
                item_id = str(
                    uuid5(NAMESPACE_URL, f"eval-export/{dataset.id}/{case.case_id}")
                )
                if item_id in existing:
                    response["existing_count"] += 1
                    continue
                try:
                    await api.dataset_items.create(
                        dataset_name=dataset_name,
                        id=item_id,
                        input=case.model_dump(mode="json"),
                        expected_output=case.model_dump(
                            mode="json",
                            include={"accepted_answers", "answerable", "evidence_sets"},
                        ),
                        source_trace_id=result.get("trace_id"),
                        metadata={
                            "source_run_id": run_id,
                            "case_id": case.case_id,
                            "evaluators": result.get("evaluators", {}),
                            "answer_trace_id": result.get("answer_trace_id"),
                        },
                    )
                    response["created_count"] += 1
                except Exception as error:
                    response["failures"].append(
                        {"case_id": case.case_id, "error": type(error).__name__}
                    )
            return {
                **response,
                "status": "PARTIAL" if response["failures"] else "COMPLETED",
            }
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(
            f"Langfuse dataset export failed ({type(error).__name__})"
        ) from None


async def load_hosted_cases(name: str) -> list[EvalCase]:
    settings = Settings()
    secret = settings.langfuse_secret_key
    if not settings.langfuse_public_key or not secret or not secret.get_secret_value():
        raise ValueError("Langfuse dataset loading requires public and secret keys")
    version = datetime.now(UTC)
    # Dataset reads must also work when tracing is disabled.
    async with httpx.AsyncClient(
        timeout=settings.timeout_dataset_fetch_http_seconds
    ) as transport:
        api = AsyncLangfuseAPI(
            base_url=settings.langfuse_base_url,
            username=settings.langfuse_public_key,
            password=secret.get_secret_value(),
            httpx_client=transport,
        )
        try:
            dataset = await api.datasets.get(dataset_name=quote(name, safe=""))
            items = []
            page = 1
            while True:
                response = await api.dataset_items.list(
                    dataset_name=name, page=page, limit=100, version=version
                )
                items.extend(response.data)
                if page >= response.meta.total_pages:
                    break
                page += 1
        except Exception as error:
            # Provider exception messages can include request headers or credentials.
            raise ValueError(
                f"Could not load Langfuse dataset ({type(error).__name__})"
            ) from None
    cases = []
    seen = set()
    case_ids = set()
    for item in items:
        if item.status != "ACTIVE":
            continue
        if item.id in seen:
            raise ValueError(f"Duplicate Langfuse dataset item: {item.id}")
        seen.add(item.id)
        try:
            case = case_from_item(item, dataset, version)
        except (ValueError, TypeError) as error:
            raise ValueError(
                f"Invalid Langfuse dataset item {item.id}: {error}"
            ) from None
        if case.case_id in case_ids:
            raise ValueError(f"Duplicate hosted case_id: {case.case_id}")
        case_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("Langfuse dataset has no active items")
    return cases


def case_from_item(item, dataset, version: datetime) -> EvalCase:
    """Validate the original EvalCase stored in observation/dataset input."""
    case = EvalCase.model_validate(item.input)
    source = EvalSource.model_validate(
        {
            **case.source.model_dump(),
            "kind": "langfuse",
            "dataset": dataset.name,
            "dataset_id": dataset.id,
            "record_id": item.id,
            "version": version.isoformat(),
        }
    )
    return case.model_copy(update={"source": source})


class HostedDatasetService:
    """Read hosted cases and create filtered datasets from retained eval runs."""

    async def read(self, name: str) -> list[EvalCase]:
        return await load_hosted_cases(name)

    async def create_from_eval(
        self, eval_name: str, score_filters: list[ScoreFilter], dataset_name: str
    ) -> dict:
        if not score_filters or not dataset_name.strip():
            raise ValueError("score_filters and a nonblank dataset_name are required")
        run_id = await self.resolve_eval_name(eval_name)
        result = await self.read_eval(run_id)
        if result["status"] != "COMPLETED":
            raise ValueError("Dataset export requires a completed eval run")
        exported = await export_dataset(
            run_id, result["results"], score_filters, dataset_name
        )
        return {**exported, "eval_name": eval_name, "run_id": run_id}

    async def read_eval(self, run_id: str) -> EvalRunResponse:
        if not run_id.startswith("kilt-eval-"):
            raise ValueError("invalid eval run ID")
        client = await Client.connect(
            Settings().temporal_address, data_converter=pydantic_data_converter
        )
        handle = client.get_workflow_handle(run_id, result_type=list[dict])
        description = await handle.describe()
        result: EvalRunResponse = {"run_id": run_id, "status": description.status.name}
        if description.status == WorkflowExecutionStatus.COMPLETED:
            result["results"] = await handle.result()
            retrieval_run = run_id.startswith("kilt-eval-retrieval-")
            if not retrieval_run:
                result["summary"] = summarize_answers(result["results"])
            if retrieval_run or any(
                "retrieval_recall_at_k" in r.get("evaluators", {})
                for r in result["results"]
            ):
                result["retrieval_summary"] = summarize_retrieval(result["results"])
            for case_result in result["results"]:
                if "experiment_id" in case_result:
                    result["experiment_id"] = case_result["experiment_id"]
                if "experiment_url" in case_result:
                    result["experiment_url"] = case_result["experiment_url"]
            result["coverage"] = {
                "total": len(result["results"]),
                "completed": sum(
                    r.get("output", {}).get("status") == "COMPLETED"
                    for r in result["results"]
                ),
                "failed": sum(
                    r.get("output", {}).get("status") != "COMPLETED"
                    for r in result["results"]
                ),
            }
            if retrieval_run:
                for k in RECALL_KS:
                    count = result["retrieval_summary"][f"recall@{k}_count"]
                    result["coverage"][f"recall@{k}_scored"] = count
                    result["coverage"][f"recall@{k}_skipped"] = (
                        len(result["results"]) - count
                    )
            else:
                count = result["summary"]["correctness_count"]
                result["coverage"].update(
                    correctness_scored=count,
                    correctness_skipped=len(result["results"]) - count,
                )
        return result

    async def resolve_eval_name(self, eval_name: str) -> str:
        """Resolve exact names, including runs started before name memos existed."""
        if not eval_name.strip():
            raise ValueError("eval_name must not be blank")
        client = await Client.connect(
            Settings().temporal_address, data_converter=pydantic_data_converter
        )
        matches = set()
        async for execution in client.list_workflows("WorkflowType = 'EvalWorkflow'"):
            if not execution.id.startswith("kilt-eval-"):
                continue
            memo = await execution.memo()
            if "eval_name" in memo:
                name = memo["eval_name"]
            else:
                name = None
                handle = client.get_workflow_handle(
                    execution.id, run_id=execution.run_id
                )
                async for event in handle.fetch_history_events():
                    if event.HasField("workflow_execution_started_event_attributes"):
                        payloads = (
                            event.workflow_execution_started_event_attributes.input
                        )
                        (request,) = await pydantic_data_converter.decode(
                            payloads.payloads, [EvalRunRequest]
                        )
                        name = request.experiment_name
                        break
            if name is not None and name.strip() == eval_name.strip():
                matches.add(execution.id)
                if len(matches) > 1:
                    raise ValueError(
                        f"Multiple eval runs match {eval_name!r}; use unique eval names"
                    )
        if not matches:
            raise ValueError(f"No retained eval run found named {eval_name!r}")
        return next(iter(matches))
