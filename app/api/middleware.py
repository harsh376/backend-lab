"""Application-specific HTTP middleware."""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import Response
from opentelemetry import trace
from starlette.middleware.base import RequestResponseEndpoint


def install_request_id_middleware(app: FastAPI) -> None:
    """Propagate the API's request ID independently of telemetry context."""

    @app.middleware("http")
    async def propagate_request_id(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("app.request.id", request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
