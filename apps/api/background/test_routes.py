from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient
from kombu.exceptions import OperationalError

from apps.api.routers.conftest import make_app


@pytest.mark.parametrize("available", [True, False])
async def test_enqueue_ping(sqlalchemy_sessions, available):
    app = await make_app(sqlalchemy_sessions)
    queue = Mock()
    queue.send_task.return_value = SimpleNamespace(id="task-123")
    if not available:
        queue.send_task.side_effect = OperationalError("broker offline")
    app.state.dependencies = replace(app.state.dependencies, task_queue=queue)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/background/ping")
    assert response.status_code == (202 if available else 503)
    if available:
        assert response.json() == {"task_id": "task-123", "status": "queued"}
    queue.send_task.assert_called_once()
    assert queue.send_task.call_args.args == ("api.ping",)
    assert queue.send_task.call_args.kwargs["kwargs"]["request_id"]


async def test_enqueue_without_queue(sqlalchemy_sessions):
    app = await make_app(sqlalchemy_sessions)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/background/ping")
    assert response.status_code == 503
