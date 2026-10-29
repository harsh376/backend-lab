from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langfuse.api import NotFoundError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError

from apps.evals import activities
from apps.evals.datasets import hosted_dataset as module
from apps.evals.datasets.dataset import load_cases
from apps.evals.datasets.hosted_dataset import HostedDatasetService, ScoreFilter
from apps.evals.models import EvalCase
from apps.evals.workflow import EvalRunRequest

DATASET = Path(__file__).parent / "kilt-v1/dev.json"


def case_payload(case_id="one", **updates):
    case = load_cases(DATASET)[0]
    return {
        **case.model_dump(mode="json"),
        "case_id": case_id,
        "tags": ["citation"],
        **updates,
    }


def item(item_id="one", **kwargs):
    return SimpleNamespace(
        **{
            "id": item_id,
            "input": case_payload(item_id),
            "expected_output": None,
            "metadata": {},
            "status": "ACTIVE",
            **kwargs,
        }
    )


async def read_item(value, api):
    api.datasets.get.side_effect = None
    api.datasets.get.return_value = SimpleNamespace(id="dataset-id", name="errors")
    api.dataset_items.list.return_value = SimpleNamespace(
        data=[value], meta=SimpleNamespace(total_pages=1)
    )
    return (await HostedDatasetService().read("errors"))[0]


@pytest.mark.parametrize("answerable", [True, False])
async def test_complete_case_input_round_trips_with_empty_expected_output(
    answerable, api
):
    payload = case_payload("stable-case", answerable=answerable)
    if not answerable:
        payload.update(accepted_answers=[], evidence_sets=[])
    original = EvalCase.model_validate(payload)
    case = await read_item(item("hosted-item", input=payload), api)
    assert case.model_dump(exclude={"source"}) == original.model_dump(
        exclude={"source"}
    )
    assert case.source.record_id == "hosted-item"
    assert case.source.dataset_id == "dataset-id"
    assert case.source.dataset == "errors"
    assert case.source.kind == "langfuse"
    assert case.source.original_output == original.source.original_output
    assert case.source.split == original.source.split
    converter = pydantic_data_converter
    assert await converter.decode(await converter.encode([case]), [EvalCase]) == [case]


@pytest.mark.parametrize(
    "field",
    [
        "case_id",
        "question",
        "source",
        "answerable",
        "evidence_sets",
        "accepted_answers",
        "group_id",
    ],
)
async def test_input_requires_the_same_eval_case_contract(field, api):
    payload = case_payload()
    del payload[field]
    with pytest.raises(ValueError):
        await read_item(item(input=payload), api)


async def test_expected_output_and_metadata_do_not_override_case(api):
    case = await read_item(
        item(
            expected_output={"accepted_answers": ["wrong"], "answerable": False},
            metadata={"case_id": "wrong", "tags": ["rejected"]},
        ),
        api,
    )
    assert case.accepted_answers == case_payload()["accepted_answers"]
    assert case.answerable is True
    assert case.tags == ["citation"]
    assert case.case_id == "one"


async def test_invalid_input_is_not_rescued_by_expected_output(api):
    with pytest.raises(ValueError):
        await read_item(
            item(
                input={"question": "Question?"},
                expected_output={"accepted_answers": ["answer"]},
            ),
            api,
        )


async def test_paginated_snapshot_skips_archived_items(monkeypatch):
    api = Mock()
    api.datasets.get = AsyncMock(return_value=SimpleNamespace(id="ds", name="errors"))
    api.dataset_items.list = AsyncMock(
        side_effect=[
            SimpleNamespace(
                data=[item(), item("archived", status="ARCHIVED", input=None)],
                meta=SimpleNamespace(total_pages=2),
            ),
            SimpleNamespace(data=[item("two")], meta=SimpleNamespace(total_pages=2)),
        ]
    )
    monkeypatch.setattr(module, "AsyncLangfuseAPI", Mock(return_value=api))
    monkeypatch.setattr(
        module,
        "Settings",
        lambda: SimpleNamespace(
            langfuse_public_key="pk",
            langfuse_secret_key=Mock(get_secret_value=lambda: "sk"),
            langfuse_base_url="https://example.com",
            timeout_dataset_fetch_http_seconds=20,
            timeout_dataset_export_http_seconds=30,
        ),
    )
    cases = await HostedDatasetService().read("errors")
    assert [case.case_id for case in cases] == ["one", "two"]
    calls = api.dataset_items.list.call_args_list
    assert [call.kwargs["page"] for call in calls] == [1, 2]
    assert calls[0].kwargs["version"] == calls[1].kwargs["version"]
    assert cases[0].source.version == calls[0].kwargs["version"].isoformat()
    api.dataset_items.list.side_effect = None
    api.dataset_items.list.return_value = SimpleNamespace(
        data=[
            item("one", input=case_payload("same", question="First?")),
            item("two", input=case_payload("same", question="Second?")),
        ],
        meta=SimpleNamespace(total_pages=1),
    )
    with pytest.raises(ValueError, match="Duplicate hosted case_id: same"):
        await HostedDatasetService().read("errors")


@pytest.mark.parametrize("eval_type", ["answer", "retrieval"])
async def test_worker_filters_hosted_cases_without_loading_local(
    monkeypatch, api, eval_type
):
    cases = [
        await read_item(item(), api),
        await read_item(item("two", input=case_payload("two", tags=[])), api),
    ]
    monkeypatch.setattr(activities.activity, "info", lambda: Mock(workflow_id="eval"))
    loader = AsyncMock(return_value=cases)
    monkeypatch.setattr(activities.HostedDatasetService, "read", loader)
    local = Mock(side_effect=AssertionError("local dataset must not be loaded"))
    monkeypatch.setattr(activities, "load_cases", local)
    result = await activities.load_eval_cases(
        EvalRunRequest(
            hosted_dataset="errors", limit=None, tags=["citation"], eval_type=eval_type
        )
    )
    assert result == [cases[0]]
    loader.assert_awaited_once_with("errors")
    local.assert_not_called()
    loader.side_effect = ValueError("missing dataset")
    with pytest.raises(ApplicationError) as error:
        await activities.load_eval_cases(EvalRunRequest(hosted_dataset="missing"))
    assert error.value.non_retryable


async def test_api_errors_are_sanitized(monkeypatch):
    api = Mock()
    api.datasets.get = AsyncMock(side_effect=RuntimeError("secret-header"))
    monkeypatch.setattr(module, "AsyncLangfuseAPI", Mock(return_value=api))
    monkeypatch.setattr(
        module,
        "Settings",
        lambda: SimpleNamespace(
            langfuse_public_key="pk",
            langfuse_secret_key=Mock(get_secret_value=lambda: "sk"),
            langfuse_base_url="https://example.com",
            timeout_dataset_fetch_http_seconds=20,
            timeout_dataset_export_http_seconds=30,
        ),
    )
    with pytest.raises(ValueError, match="RuntimeError") as error:
        await HostedDatasetService().read("errors")
    assert "secret-header" not in str(error.value)


@pytest.fixture
def create(monkeypatch):
    service = HostedDatasetService()
    resolve = AsyncMock()
    read = AsyncMock()
    monkeypatch.setattr(service, "resolve_eval_name", resolve)
    monkeypatch.setattr(service, "read_eval", read)

    async def create(run_id, results, filters, dataset_name):
        resolve.return_value = run_id
        read.return_value = {"status": "COMPLETED", "results": results}
        return await service.create_from_eval("test-v5", filters, dataset_name)

    return create


@pytest.mark.parametrize(
    "score, expected",
    [(0, 1), (1, 0), (None, 0), ("0", 0), (False, 0), (float("nan"), 0)],
)
async def test_service_filters_exclude_unscored(api, create, score, expected):
    case = result()
    case["evaluators"]["answer_correctness"]["correctness"] = score
    response = await create(
        "run", [case], [ScoreFilter(name="answer_correctness", value=0)], "errors"
    )
    assert response["matched_count"] == expected
    assert api.dataset_items.create.await_count == expected


async def test_service_filters_combine_with_and_and_custom_fields(api, create):
    case = result()
    case["evaluators"] = {"a": {"correctness": 0}, "b": {"score": 0.5}}
    filters = [
        ScoreFilter(name="a", value=0),
        ScoreFilter(name="b", score_field="score", operator="gte", value=0.5),
    ]
    response = await create("run", [case], filters, "errors")
    assert response["matched_count"] == 1
    response = await create(
        "run", [case], filters + [ScoreFilter(name="missing", value=0)], "other"
    )
    assert response["status"] == "NO_MATCHES"
    assert api.datasets.create.await_count == 1


async def test_service_legacy_snapshot_uses_original_trace(api, create):
    api.trace.get = AsyncMock(
        return_value=SimpleNamespace(
            observations=[SimpleNamespace(name="eval_case", input=case_payload())]
        )
    )
    case = result()
    del case["case"]
    filters = [ScoreFilter(name="answer_correctness", value=0)]
    await create("run", [case], filters, "errors")
    assert api.dataset_items.create.call_args.kwargs["input"] == case_payload()
    case["case_id"] = "different"
    with pytest.raises(ValueError, match="does not match"):
        await create("run", [case], filters, "other")
    assert api.datasets.create.await_count == 1


@pytest.fixture
def api(monkeypatch):
    api = Mock()
    api.datasets.get = AsyncMock(side_effect=NotFoundError(body="missing"))

    async def create(**kwargs):
        return SimpleNamespace(id="ds", metadata=kwargs["metadata"])

    api.datasets.create = AsyncMock(side_effect=create)
    api.dataset_items.list = AsyncMock(
        return_value=SimpleNamespace(data=[], meta=SimpleNamespace(total_pages=1))
    )
    api.dataset_items.create = AsyncMock()
    monkeypatch.setattr(module, "AsyncLangfuseAPI", Mock(return_value=api))
    monkeypatch.setattr(
        module,
        "Settings",
        lambda: SimpleNamespace(
            langfuse_public_key="pk",
            langfuse_secret_key=Mock(get_secret_value=lambda: "sk"),
            langfuse_base_url="https://example.com",
            timeout_dataset_fetch_http_seconds=20,
            timeout_dataset_export_http_seconds=30,
        ),
    )
    return api


def result(case_id="one"):
    return {
        "case_id": case_id,
        "case": case_payload(case_id),
        "trace_id": "trace",
        "evaluators": {"answer_correctness": {"correctness": 0, "reason": "wrong"}},
    }


async def test_export_preserves_inputs_and_retry_skips_existing(api, create):
    filters = [ScoreFilter(name="answer_correctness", value=0)]
    first = await create("run", [result()], filters, "errors")
    assert first["created_count"] == 1
    payload = api.dataset_items.create.call_args.kwargs
    assert payload["input"] == case_payload()
    assert (
        payload["expected_output"]["accepted_answers"]
        == case_payload()["accepted_answers"]
    )
    assert payload["source_trace_id"] == "trace"
    metadata = api.datasets.create.call_args.kwargs["metadata"]
    api.datasets.get.side_effect = None
    api.datasets.get.return_value = SimpleNamespace(id="ds", metadata=metadata)
    api.dataset_items.list.return_value.data = [SimpleNamespace(id=payload["id"])]
    retry = await create("run", [result()], filters, "errors")
    assert retry["existing_count"] == 1
    assert api.dataset_items.create.await_count == 1
    with pytest.raises(ValueError, match="different export"):
        await create("another-run", [result()], filters, "errors")


async def test_no_matches_and_invalid_snapshot_do_not_create(api, create):
    filters = [ScoreFilter(name="answer_correctness", value=0)]
    assert (await create("run", [], filters, "errors"))["status"] == "NO_MATCHES"
    broken = result()
    broken["case"] = {"case_id": "one"}
    with pytest.raises(ValueError):
        await create("run", [broken], filters, "errors")
    api.datasets.create.assert_not_called()


async def test_partial_failure_is_sanitized_and_retryable(api, create):
    api.dataset_items.create.side_effect = [RuntimeError("secret-header"), None]
    response = await create(
        "run",
        [result(), result("two")],
        [ScoreFilter(name="answer_correctness", value=0)],
        "errors",
    )
    assert response["status"] == "PARTIAL"
    assert response["created_count"] == 1
    assert response["failures"] == [{"case_id": "one", "error": "RuntimeError"}]


async def test_create_dataset_from_eval_requires_completed_run(monkeypatch):
    from apps.evals.datasets.hosted_dataset import ScoreFilter

    get = AsyncMock(return_value={"status": "RUNNING"})
    export = AsyncMock(return_value={"status": "COMPLETED", "matched_count": 2})
    monkeypatch.setattr(module.HostedDatasetService, "read_eval", get)
    monkeypatch.setattr(module, "export_dataset", export)
    monkeypatch.setattr(
        module.HostedDatasetService,
        "resolve_eval_name",
        AsyncMock(return_value="kilt-eval-one"),
    )
    filters = [ScoreFilter(name="answer_correctness", value=0)]
    with pytest.raises(ValueError, match="completed"):
        await HostedDatasetService().create_from_eval("test-v5", filters, "errors")
    export.assert_not_awaited()
    get.return_value = {"status": "COMPLETED", "results": [{"case_id": "one"}]}
    response = await HostedDatasetService().create_from_eval(
        "test-v5", filters, "errors"
    )
    assert response["matched_count"] == 2
    assert response["eval_name"] == "test-v5"
    assert response["run_id"] == "kilt-eval-one"
    export.assert_awaited_once_with(
        "kilt-eval-one", [{"case_id": "one"}], filters, "errors"
    )
    with pytest.raises(ValueError):
        await HostedDatasetService().create_from_eval("kilt-eval-one", [], "errors")


@pytest.mark.parametrize(
    "names, error",
    [
        (["test-v5"], None),
        (["other"], "No retained"),
        (["test-v5", "test-v5"], "Multiple"),
    ],
)
async def test_resolve_eval_name(monkeypatch, names, error):
    from types import SimpleNamespace

    executions = [
        SimpleNamespace(
            id=f"kilt-eval-{i}",
            run_id=str(i),
            memo=AsyncMock(return_value={"eval_name": name}),
        )
        for i, name in enumerate(names)
    ]

    async def listing(query):
        assert query == "WorkflowType = 'EvalWorkflow'"
        for execution in executions:
            yield execution

    client = Mock(list_workflows=listing)
    monkeypatch.setattr(module.Client, "connect", AsyncMock(return_value=client))
    if error:
        with pytest.raises(ValueError, match=error):
            await HostedDatasetService().resolve_eval_name("test-v5")
    else:
        assert (
            await HostedDatasetService().resolve_eval_name("test-v5") == "kilt-eval-0"
        )
    client.get_workflow_handle.assert_not_called()


async def test_resolve_legacy_eval_name_from_original_request(monkeypatch):
    from types import SimpleNamespace

    from temporalio.api.common.v1 import Payloads
    from temporalio.api.history.v1 import (
        HistoryEvent,
        WorkflowExecutionStartedEventAttributes,
    )
    from temporalio.contrib.pydantic import pydantic_data_converter

    from apps.evals.workflow import EvalRunRequest

    event = HistoryEvent(
        workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
            input=Payloads(
                payloads=await pydantic_data_converter.encode(
                    [EvalRunRequest(experiment_name="test-v5")]
                )
            )
        )
    )

    async def listing(query):
        yield SimpleNamespace(
            id="kilt-eval-old", run_id="execution", memo=AsyncMock(return_value={})
        )

    async def history():
        yield event

    client = Mock(list_workflows=listing)
    client.get_workflow_handle.return_value.fetch_history_events = history
    monkeypatch.setattr(module.Client, "connect", AsyncMock(return_value=client))
    assert await HostedDatasetService().resolve_eval_name("test-v5") == "kilt-eval-old"
    client.get_workflow_handle.assert_called_once_with(
        "kilt-eval-old", run_id="execution"
    )


async def test_blank_eval_name_is_rejected_before_connect(monkeypatch):
    connect = AsyncMock()
    monkeypatch.setattr(module.Client, "connect", connect)
    with pytest.raises(ValueError, match="blank"):
        await HostedDatasetService().resolve_eval_name("  ")
    connect.assert_not_awaited()


async def test_read_eval_returns_separate_answer_and_retrieval_summaries(monkeypatch):
    results = [
        {
            "output": {"status": "COMPLETED"},
            "evaluators": {
                "answer_correctness": {"correctness": 1},
                "retrieval_recall_at_k": {"recall@5": 0.5},
            },
        }
    ]
    handle = Mock(
        describe=AsyncMock(
            return_value=Mock(status=module.WorkflowExecutionStatus.COMPLETED)
        ),
        result=AsyncMock(return_value=results),
    )
    client = Mock(get_workflow_handle=Mock(return_value=handle))
    monkeypatch.setattr(module.Client, "connect", AsyncMock(return_value=client))
    response = await HostedDatasetService().read_eval("kilt-eval-test")
    assert response["summary"] == {"correctness": 1, "correctness_count": 1}
    assert response["retrieval_summary"]["recall@5"] == 0.5
    assert response["retrieval_summary"]["recall@5_count"] == 1
    assert response["retrieval_summary"]["recall@50"] is None


@pytest.mark.parametrize("failed", [False, True])
async def test_read_retrieval_eval_has_recall_coverage_without_correctness(
    monkeypatch, failed
):
    results = [
        {
            "output": {"status": "FAILED" if failed else "COMPLETED"},
            "evaluators": {}
            if failed
            else {"retrieval_recall_at_k": {"recall@5": 0, "passage_recall@5": 0.5}},
        }
    ]
    handle = Mock(
        describe=AsyncMock(
            return_value=Mock(status=module.WorkflowExecutionStatus.COMPLETED)
        ),
        result=AsyncMock(return_value=results),
    )
    client = Mock(get_workflow_handle=Mock(return_value=handle))
    monkeypatch.setattr(module.Client, "connect", AsyncMock(return_value=client))
    response = await HostedDatasetService().read_eval("kilt-eval-retrieval-test")
    assert "summary" not in response
    assert response["retrieval_summary"]["recall@5"] == (None if failed else 0)
    assert response["coverage"]["recall@5_scored"] == (0 if failed else 1)
    assert response["coverage"]["recall@5_skipped"] == (1 if failed else 0)
    assert response["coverage"]["recall@100_scored"] == 0
    assert response["retrieval_summary"]["passage_recall@5"] == (
        None if failed else 0.5
    )
    assert response["coverage"]["passage_recall@5_scored"] == (0 if failed else 1)
    assert response["coverage"]["passage_recall@5_skipped"] == (1 if failed else 0)
    assert response["coverage"]["passage_recall@100_scored"] == 0
    assert "correctness_scored" not in response["coverage"]
