from unittest.mock import Mock

from opentelemetry import baggage, context

from apps.evals import experiments


def test_execution_and_case_identity(monkeypatch):
    info = Mock(workflow_id="eval", workflow_run_id="execution", attempt=1)
    monkeypatch.setattr(experiments.activity, "info", lambda: info)
    request = Mock(case=Mock(case_id="case-one"))
    first = experiments.experiment_id()
    trace = experiments.case_trace_context({"request": request})
    info.attempt = 2
    assert experiments.experiment_id() == first
    assert experiments.case_trace_context({"request": request}) == trace
    request.case.case_id = "case-two"
    assert experiments.case_trace_context({"request": request}) != trace
    info.workflow_run_id = "another-execution"
    assert experiments.experiment_id() != first


def test_answer_baggage_is_isolated_and_restored():
    token = context.attach(baggage.set_baggage("langfuse_experiment_id", "eval"))
    try:
        with experiments.without_experiment():
            assert not baggage.get_all()
        assert baggage.get_baggage("langfuse_experiment_id") == "eval"
    finally:
        context.detach(token)


def test_url_lookup_failure_does_not_fail_evaluation():
    instance = Mock(get_trace_url=Mock(side_effect=ConnectionError("offline")))
    experiments._project_trace_url.cache_clear()
    assert experiments._project_trace_url(instance) is None
    assert experiments._project_trace_url(instance) is None
    instance.get_trace_url.assert_called_once()
    experiments._project_trace_url.cache_clear()
