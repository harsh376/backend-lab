"""Check deadline relationships and Temporal sandbox compatibility."""

from temporalio import workflow
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from apps.evals.workflow import EvalWorkflow
from apps.mcp.agent.workflow import AnswerWorkflow
from backend.config import Settings


def test_outer_deadlines_allow_model_calls_and_scoring():
    settings = Settings.from_timeout_snapshot(None)
    assert (
        settings.timeout_model_activity_seconds
        > settings.timeout_model_request_max_seconds
    )
    assert settings.timeout_model_activity_total_seconds > (
        settings.timeout_model_activity_seconds * settings.model_max_attempts
    )
    assert (
        settings.timeout_eval_scoring_seconds
        > settings.timeout_model_request_max_seconds
    )
    assert (
        settings.timeout_answer_eval_seconds
        > 2 * settings.timeout_model_activity_seconds
    )


async def test_workflow_timeout_imports_are_sandbox_safe():
    runner = SandboxedWorkflowRunner()
    for cls in (AnswerWorkflow, EvalWorkflow):
        runner.prepare_workflow(workflow._Definition.must_from_class(cls))
