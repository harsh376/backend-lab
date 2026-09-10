"""FastAPI application factory."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import MeterProvider
from opentelemetry.trace import TracerProvider

from app.api.dependencies import ApplicationDependencies
from app.api.middleware import install_request_id_middleware
from app.api.routers import health, titles
from app.api.schemas import error_response


def create_app(
    dependencies: ApplicationDependencies,
    tracer_provider: TracerProvider | None = None,
    meter_provider: MeterProvider | None = None,
) -> FastAPI:
    app = FastAPI(title="Title API", version="1.0.0")
    app.state.dependencies = dependencies
    install_request_id_middleware(app)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            status_code=400,
            code="INVALID_ARGUMENT",
            message="Request parameters are invalid",
            request_id=request.state.request_id,
        )

    app.include_router(health.router)
    app.include_router(titles.router, prefix="/v1")

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )

    return app
