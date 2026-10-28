from unittest.mock import AsyncMock, Mock

import litellm
import pytest
from temporalio.converter import DataConverter
from temporalio.exceptions import ActivityError

from apps.mcp.agent import workflow as module
from apps.mcp.agent.models import AnswerRequest, ArticleEvidence
from backend.budget import BudgetReport, Reservation, current_reservation
from backend.config import Settings
from backend.llm import LiteLLMStructuredModel, ModelProviderError
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerResult,
    Paragraph,
    SynthesisResponse,
    VerificationResult,
)


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_invalid_budget(limit):
    with pytest.raises(ValueError, match="budget_usd"):
        AnswerRequest("question", budget_usd=limit).validate()


def test_reservation_releases_unused_funds_and_reports_overrun():
    report = BudgetReport(0.1)
    assert report.reserve("synthesis", Reservation("model", 10, 0.08))
    assert report.reconcile(0.02)
    assert report.reserve("verification", Reservation("model", 10, 0.08))
    assert report.reconcile(0.09)
    assert report.stop_reason is None
    assert report.overrun_usd == pytest.approx(0.01)
    assert report.committed_usd == pytest.approx(0.11)


@pytest.mark.parametrize(
    "limit,synthesis_cost,failure,expected,dispatched",
    [
        (0.01, 0.02, False, "insufficient_budget", []),
        (0.07, 0.04, False, "insufficient_budget", ["synthesize_answer"]),
        (0.1, 0.02, False, None, ["synthesize_answer", "verify_answer"]),
        (0.1, None, False, "unknown_cost", ["synthesize_answer"]),
        (0.1, 0.11, False, "insufficient_budget", ["synthesize_answer"]),
        (0.1, 0.02, True, "unknown_provider_outcome", ["synthesize_answer"]),
    ],
)
async def test_workflow_budget(
    monkeypatch, limit, synthesis_cost, failure, expected, dispatched
):
    paragraph = Paragraph("v:1:0", "v", "1", 0, "Title", "Evidence")
    candidate = AnswerResult(
        "answer", "explanation", [paragraph], usage_cost_usd=synthesis_cost
    )
    calls = []

    async def execute(name, data, **kwargs):
        if name == "retrieve_answer_evidence":
            return [ArticleEvidence("1", "v", "1", "Title", [paragraph.text])]
        if name == "record_answer_result":
            assert data.answer.budget is not None
            assert data.answer.budget.stop_reason == expected
            assert data.answer.abstained == (expected is not None)
            return None
        assert kwargs["retry_policy"].maximum_attempts == 1
        if name.startswith("quote_"):
            return Reservation("model", 10, 0.04)
        calls.append(name)
        assert data.reservation.reserved_cost_usd == 0.04
        if failure:
            raise ActivityError(
                "unknown",
                scheduled_event_id=1,
                started_event_id=2,
                identity="worker",
                activity_type=name,
                activity_id="call",
                retry_state=None,
            )
        if name == "verify_answer":
            candidate.verification = VerificationResult(
                True, "supported", "provider", "model", usage_cost_usd=0.01
            )
        return candidate

    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    result = await module.AnswerWorkflow().run(
        AnswerRequest("question", budget_usd=limit)
    )
    assert calls == dispatched
    assert result.budget.stop_reason == expected
    if synthesis_cost is not None and synthesis_cost > limit and dispatched:
        assert result.budget.overrun_usd == pytest.approx(synthesis_cost - limit)
    assert result.abstained == (expected is not None)
    if expected:
        assert result.short_answer == ""
        assert result.citations == []
    if failure or synthesis_cost is None:
        assert result.budget.entries[-1].status == "unresolved"
        assert result.budget.committed_usd == 0.04
    converter = DataConverter.default
    assert await converter.decode(await converter.encode([result]), [AnswerResult]) == [
        result
    ]


async def test_quote_failure_abstains_before_dispatch(monkeypatch):
    paragraph = Paragraph("v:1:0", "v", "1", 0, "Title", "Evidence")
    error = ActivityError(
        "unknown price",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="quote_synthesis",
        activity_id="quote",
        retry_state=None,
    )
    execute = AsyncMock(
        side_effect=[
            [ArticleEvidence("1", "v", "1", "Title", [paragraph.text])],
            error,
            None,
        ]
    )
    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    result = await module.AnswerWorkflow().run(AnswerRequest("q", budget_usd=1))
    assert result.abstained
    assert result.budget.entries == []
    assert result.budget.stop_reason == "reservation_unavailable"


async def test_model_checks_reservation_before_provider_call(monkeypatch):
    model = LiteLLMStructuredModel(
        Settings(mcp_answer_model="openai/test", openai_api_key="test")
    )
    pricing = Mock(return_value=(0.01, 0.02))
    monkeypatch.setattr(litellm, "cost_per_token", pricing)
    provider = AsyncMock()
    monkeypatch.setattr(litellm, "acompletion", provider)
    messages = [{"role": "user", "content": "question"}]
    quote = model.quote(messages, SynthesisResponse)
    assert quote.reserved_cost_usd == 0.03
    assert pricing.call_args.kwargs["completion_tokens"] == model.max_tokens
    token = current_reservation.set(Reservation("openai/different", 1, 1))
    try:
        with pytest.raises(ModelProviderError, match="changed"):
            await model.complete(
                messages,
                response_schema=SynthesisResponse,
                schema_name="test",
                prompt_version="test",
                observation_name="test",
            )
    finally:
        current_reservation.reset(token)
    provider.assert_not_awaited()
    pricing.side_effect = ValueError("unknown model")
    with pytest.raises(ModelProviderError, match="pricing is unavailable"):
        model.quote(messages, SynthesisResponse)


async def test_budget_forwarded_by_mcp(monkeypatch):
    from apps.mcp import server

    client = Mock(start_workflow=AsyncMock())
    monkeypatch.setattr(server, "temporal_client", AsyncMock(return_value=client))
    await server.answer("question", budget_usd=0.05)
    assert client.start_workflow.call_args.args[1].budget_usd == 0.05


async def test_no_evidence_spends_nothing(monkeypatch):
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    result = await module.AnswerWorkflow().run(AnswerRequest("q", budget_usd=0.1))
    assert result.abstained
    assert result.budget.entries == []
    assert execute.await_count == 2


async def test_reserved_model_call_dispatches_and_rejects_price_increase(monkeypatch):
    model = LiteLLMStructuredModel(
        Settings(mcp_answer_model="openai/test", openai_api_key="test")
    )
    pricing = Mock(return_value=(0.01, 0.02))
    monkeypatch.setattr(litellm, "cost_per_token", pricing)
    response = litellm.ModelResponse(
        model="test", usage={"prompt_tokens": 2, "completion_tokens": 2}
    )
    provider = AsyncMock(return_value=response)
    monkeypatch.setattr(litellm, "acompletion", provider)
    monkeypatch.setattr(litellm, "completion_cost", Mock(return_value=0.005))
    messages = [{"role": "user", "content": "question"}]
    token = current_reservation.set(model.quote(messages, SynthesisResponse))
    try:
        result = await model.complete(
            messages,
            response_schema=SynthesisResponse,
            schema_name="test",
            prompt_version="test",
            observation_name="test",
        )
        assert result.usage_cost_usd == 0.005
        assert provider.call_args.kwargs["num_retries"] == 0
        pricing.return_value = (0.02, 0.02)
        with pytest.raises(ModelProviderError, match="changed"):
            await model.complete(
                messages,
                response_schema=SynthesisResponse,
                schema_name="test",
                prompt_version="test",
                observation_name="test",
            )
        assert provider.await_count == 1
    finally:
        current_reservation.reset(token)


async def test_budget_scope_reconciles_on_exit(monkeypatch):
    from apps.mcp.agent.budget import budget_stage

    report = BudgetReport(0.1)
    quote = Reservation("model", 10, 0.08)
    monkeypatch.setattr(
        module.workflow, "execute_activity", AsyncMock(return_value=quote)
    )
    from apps.mcp.agent.models import SynthesisInput

    data = SynthesisInput("q", [])
    async with budget_stage(report, "synthesis", data) as stage:
        assert data.reservation == quote
        assert report.committed_usd == 0.08
        stage.record_cost(0.02)
        assert report.committed_usd == 0.08
    assert report.committed_usd == 0.02
    assert report.entries[0].status == "reconciled"


async def test_budget_scope_without_usage_stops_with_unresolved_reservation(
    monkeypatch,
):
    from apps.mcp.agent.budget import BudgetStopped, budget_stage
    from apps.mcp.agent.models import SynthesisInput

    report = BudgetReport(0.1)
    monkeypatch.setattr(
        module.workflow,
        "execute_activity",
        AsyncMock(return_value=Reservation("model", 10, 0.08)),
    )
    with pytest.raises(BudgetStopped):
        async with budget_stage(report, "synthesis", SynthesisInput("q", [])):
            pass
    assert report.stop_reason == "unknown_cost"
    assert report.committed_usd == 0.08
    assert report.entries[0].status == "unresolved"


async def test_unlimited_scope_skips_quotes_and_preserves_activity_failure(monkeypatch):
    from apps.mcp.agent.budget import budget_stage
    from apps.mcp.agent.models import SynthesisInput

    execute = AsyncMock()
    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    error = ActivityError(
        "provider failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="synthesize_answer",
        activity_id="call",
        retry_state=None,
    )
    data = SynthesisInput("q", [])
    with pytest.raises(ActivityError) as raised:
        async with budget_stage(None, "synthesis", data):
            raise error
    assert raised.value is error
    assert data.reservation is None
    execute.assert_not_awaited()


async def test_final_verification_overrun_preserves_verified_answer(monkeypatch):
    paragraph = Paragraph("v:1:0", "v", "1", 0, "Title", "Evidence")
    candidate = AnswerResult("answer", "explanation", [paragraph], usage_cost_usd=0.02)
    verified = AnswerResult(
        "answer",
        "explanation",
        [paragraph],
        usage_cost_usd=0.02,
        verification=VerificationResult(
            True, "supported", "provider", "model", usage_cost_usd=0.09
        ),
    )
    execute = AsyncMock(
        side_effect=[
            [ArticleEvidence("1", "v", "1", "Title", [paragraph.text])],
            Reservation("model", 10, 0.04),
            candidate,
            Reservation("model", 10, 0.04),
            verified,
            None,
        ]
    )
    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    result = await module.AnswerWorkflow().run(AnswerRequest("q", budget_usd=0.1))
    assert not result.abstained
    assert result.short_answer == "answer"
    assert result.citations == [paragraph]
    assert result.verification.supported
    assert result.budget.stop_reason is None
    assert result.budget.overrun_usd == pytest.approx(0.01)
    assert result.budget.entries[-1].status == "reservation_overrun"
    assert result.budget.entries[-1].usage_cost_usd == 0.09
    converter = DataConverter.default
    assert await converter.decode(await converter.encode([result]), [AnswerResult]) == [
        result
    ]


async def test_computed_overrun_is_returned_by_mcp(monkeypatch):
    from temporalio.client import WorkflowExecutionStatus

    from apps.mcp import server

    report = BudgetReport(0.1)
    report.reserve("verification", Reservation("model", 10, 0.08))
    assert report.overrun_usd == 0
    report.reconcile(0.12)
    answer = AnswerResult("answer", "explanation", budget=report)
    handle = Mock(
        describe=AsyncMock(return_value=Mock(status=WorkflowExecutionStatus.COMPLETED)),
        result=AsyncMock(return_value=answer),
    )
    client = Mock()
    client.get_workflow_handle.return_value = handle
    monkeypatch.setattr(server, "temporal_client", AsyncMock(return_value=client))
    result = await server.get_answer("kilt-answer-test")
    assert result["result"]["budget"]["overrun_usd"] == pytest.approx(0.02)


async def test_final_result_span_contains_reconciled_budget_and_trace(monkeypatch):
    from contextlib import contextmanager
    from dataclasses import asdict

    from apps.mcp import telemetry
    from apps.mcp.agent.activities import AnswerActivities
    from apps.mcp.agent.models import FinalAnswerInput, FinalAnswerOutput

    report = BudgetReport(0.1)
    report.reserve("verification", Reservation("model", 10, 0.08))
    report.reconcile(0.12)
    trace_context = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    span = Mock()
    observations = []

    @contextmanager
    def observation(name, **kwargs):
        observations.append((name, kwargs))
        yield span

    monkeypatch.setattr(telemetry, "observation", observation)
    activities = AnswerActivities(Mock(), Mock())
    result = await activities.arecord_result(
        FinalAnswerInput(
            answer=AnswerResult(
                short_answer="answer",
                explanation="explanation",
                usage={"total_tokens": 100},
                usage_cost_usd=0.01,
                budget=report,
            ),
            trace_context=trace_context,
            session_id="codex:test",
        )
    )
    assert observations[0][0] == "record_answer_result"
    assert observations[0][1]["trace_context"] == trace_context
    assert observations[0][1]["session_id"] == "codex:test"
    assert isinstance(result, FinalAnswerOutput)
    converter = DataConverter.default
    assert await converter.decode(
        await converter.encode([result]), [FinalAnswerOutput]
    ) == [result]
    result = asdict(result)
    assert result["budget"]["entries"][0]["status"] == "reservation_overrun"
    assert result["budget"]["committed_usd"] == 0.12
    assert result["budget"]["overrun_usd"] == pytest.approx(0.02)
    assert "usage" not in result
    assert "usage_cost_usd" not in result
    assert "trace_context" not in result
    assert "session_id" not in result
    assert result["synthesis"] == {
        "provider": "litellm",
        "model": None,
        "usage": {"total_tokens": 100},
        "usage_cost_usd": 0.01,
    }
    assert result["verification"] is None
    assert result["total_cost_usd"] == 0.01
    assert "usage_cost_usd" not in result
    assert result["short_answer"] == "answer"
    span.update.assert_called_once_with(output=result)


@pytest.mark.parametrize("budget_limit", [None, 0.1])
@pytest.mark.parametrize(
    ("synthesis_cost", "verification_cost", "has_verification", "expected"),
    [
        (0.02, 0.03, True, 0.05),
        (0.02, None, False, 0.02),
        (0.0, 0.0, True, 0.0),
        (None, 0.03, True, 0.03),
        (0.02, None, True, 0.02),
        (None, None, True, None),
        (None, None, False, None),
    ],
)
async def test_final_result_total_cost(
    budget_limit, synthesis_cost, verification_cost, has_verification, expected
):
    from apps.mcp.agent.activities import AnswerActivities
    from apps.mcp.agent.models import FinalAnswerInput

    answer = AnswerResult(
        "answer",
        "explanation",
        usage_cost_usd=synthesis_cost,
        verification=(
            VerificationResult(
                True,
                "supported",
                "provider",
                "model",
                usage_cost_usd=verification_cost,
            )
            if has_verification
            else None
        ),
        budget=BudgetReport(budget_limit) if budget_limit is not None else None,
    )
    result = await AnswerActivities(Mock(), Mock()).arecord_result(
        FinalAnswerInput(answer)
    )
    if expected is None:
        assert result.total_cost_usd is None
    else:
        assert result.total_cost_usd == pytest.approx(expected)
    assert (result.budget is None) == (budget_limit is None)


async def test_final_result_unknown_verification_cost_retains_commitment():
    from apps.mcp.agent.activities import AnswerActivities
    from apps.mcp.agent.models import FinalAnswerInput

    report = BudgetReport(0.1)
    report.reserve("synthesis", Reservation("model", 10, 0.04))
    report.reconcile(0.02)
    report.reserve("verification", Reservation("model", 10, 0.03))
    report.reconcile(None)
    result = await AnswerActivities(Mock(), Mock()).arecord_result(
        FinalAnswerInput(
            AnswerResult("", "stopped", usage_cost_usd=0.02, budget=report)
        )
    )
    assert result.total_cost_usd == pytest.approx(0.02)
    assert result.budget.committed_usd == pytest.approx(0.05)
