"""Langfuse experiment reporting for Temporal-owned evaluation runs."""

import hashlib
import json
import logging
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from opentelemetry import baggage, context, trace
from temporalio import activity

from apps.mcp import telemetry
from backend.config import Settings

DATASET_PATH = Path(__file__).parent / "datasets/kilt-v1/dev.json"


def experiment_id() -> str:
    info = activity.info()
    return uuid5(NAMESPACE_URL, f"eval/{info.workflow_id}/{info.workflow_run_id}").hex


def case_trace_context(args) -> dict[str, str]:
    return {
        "trace_id": uuid5(
            NAMESPACE_URL, f"{experiment_id()}/{args['request'].case.case_id}"
        ).hex
    }


@contextmanager
def experiment_item(request):
    """Set root attributes and SDK-readable baggage for evaluator descendants.

    Local IDs correlate cases across runs without uploading a hosted dataset.
    Baggage keys follow the Langfuse SDK's OTEL propagation convention.
    """
    instance = telemetry.client()
    if instance is None:
        yield {}
        return
    settings = Settings()
    run_id = experiment_id()
    info = activity.info()
    metadata = {
        "temporal_workflow_id": info.workflow_id,
        "temporal_run_id": info.workflow_run_id,
        "git_commit_sha": settings.git_commit_sha or "unknown",
        "evaluator_version": "1",
        "eval_type": request.eval_type,
    }
    if request.eval_type == "retrieval":
        metadata["retrieval_limit"] = str(request.retrieval_limit)
        metadata["corpus_version"] = settings.kilt_index
    else:
        metadata.update(
            answer_model=settings.mcp_answer_model,
            judge_model=settings.eval_judge_model,
            verification_enabled=str(request.verification_enabled).lower(),
        )
    source = request.case.source
    if source.kind == "local":
        metadata.update(
            local_dataset="kilt-v1/dev",
            dataset_version=hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest(),
        )
    else:
        metadata.update(dataset_name=source.dataset, dataset_version=source.version)
    values = {
        "experiment_id": run_id,
        "experiment_name": (
            request.experiment_name.strip()
            if request.experiment_name is not None
            else f"{info.workflow_id}/{info.workflow_run_id}"
        ),
        "experiment_item_id": request.case.case_id,
        "experiment_item_root_observation_id": instance.get_current_observation_id(),
        **{f"experiment_metadata_{key}": value for key, value in metadata.items()},
    }
    if source.kind == "langfuse":
        values["experiment_dataset_id"] = source.dataset_id
        values["experiment_item_id"] = source.record_id
    span = trace.get_current_span()
    for key, value in values.items():
        attribute = (
            "langfuse.experiment.metadata." + key.removeprefix("experiment_metadata_")
            if key.startswith("experiment_metadata_")
            else {
                "experiment_id": "langfuse.experiment.id",
                "experiment_dataset_id": "langfuse.experiment.dataset.id",
                "experiment_name": "langfuse.experiment.name",
                "experiment_item_id": "langfuse.experiment.item.id",
                "experiment_item_root_observation_id": (
                    "langfuse.experiment.item.root_observation_id"
                ),
            }[key]
        )
        if isinstance(value, str):
            span.set_attribute(attribute, value)
    span.set_attribute(
        "langfuse.experiment.item.expected_output",
        json.dumps(
            [
                list(dict.fromkeys(e.wikipedia_id for e in evidence_set))
                for evidence_set in request.case.evidence_sets
            ]
            if request.eval_type == "retrieval"
            else request.case.accepted_answers
        ),
    )
    ctx = context.get_current()
    for key, value in values.items():
        if isinstance(value, str):
            ctx = baggage.set_baggage(f"langfuse_{key}", value, context=ctx)
    token = context.attach(ctx)
    try:
        # get_trace_url is public and resolves the configured project's ID.
        url = _project_trace_url(instance)
        report = {"experiment_id": run_id}
        if isinstance(url, str) and "/traces/" in url:
            report["experiment_url"] = (
                url.split("/traces/", 1)[0]
                + "/experiments/results?baseline="
                + quote(run_id, safe="")
            )
        yield report
    finally:
        context.detach(token)


@contextmanager
def without_experiment():
    """Keep the separately linked answer trace outside the experiment item."""
    token = context.attach(baggage.clear())
    try:
        yield
    finally:
        context.detach(token)


@lru_cache(maxsize=1)
def _project_trace_url(instance):
    try:
        return instance.get_trace_url(trace_id="0" * 32)
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not resolve Langfuse results URL", exc_info=True
        )
        return None
