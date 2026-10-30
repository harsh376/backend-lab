"""Composable structured-output model client and provider accounting."""

import json
import math
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Protocol

import litellm
from pydantic import BaseModel

from backend.budget import Reservation, current_reservation
from backend.config import Settings


@dataclass
class StructuredCompletion:
    response: litellm.ModelResponse
    usage: dict[str, int]
    usage_cost_usd: float | None


class StructuredModel(Protocol):
    provider: str
    model: str

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: type[BaseModel],
        schema_name: str,
        prompt_version: str,
        observation_name: str,
    ) -> StructuredCompletion: ...


class ModelProviderError(Exception):
    """A sanitized provider rejection that the caller should not retry."""

    def __init__(self, message: str, *, error_type: str):
        super().__init__(message)
        self.error_type = error_type


def no_observation(*args, **kwargs):
    return nullcontext()


class LiteLLMStructuredModel:
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        model_setting: str = "MCP_ANSWER_MODEL",
        observation_factory: Callable[..., AbstractContextManager] = no_observation,
        temperature: float | None = None,
    ):
        self._observation = observation_factory
        # None keeps the provider's default sampling.
        self.temperature = temperature
        self.model = model or settings.mcp_answer_model
        self.provider, separator, model_name = self.model.partition("/")
        if (
            separator != "/"
            or not model_name
            or self.provider not in {"openai", "anthropic", "ollama_chat"}
        ):
            raise ValueError(
                f"{model_setting} must be openai/<model>, anthropic/<model>, "
                "or ollama_chat/<model>."
            )
        if self.provider == "ollama_chat":
            self._provider_options = {
                "api_base": settings.ollama_api_base,
                "reasoning_effort": "none",
            }
        else:
            key = {
                "openai": settings.openai_api_key,
                "anthropic": settings.anthropic_api_key,
            }[self.provider]
            if key is None or not key.get_secret_value().strip():
                raise ValueError(
                    f"Missing {self.provider.upper()}_API_KEY for answer model."
                )
            self._provider_options = {"api_key": key.get_secret_value()}
        self.max_tokens = settings.mcp_answer_max_tokens
        self.timeout = settings.timeout_model_request_seconds

    @property
    def _sampling_options(self) -> dict[str, float]:
        if self.temperature is None:
            return {}
        return {"temperature": self.temperature}

    def quote(self, messages, response_schema) -> Reservation:
        # UTF-8 bytes plus schema and framing allowance deliberately overestimate
        # input tokens. This is a pricing estimate, not a provider billing cap.
        payload = json.dumps(messages) + json.dumps(response_schema.model_json_schema())
        input_tokens = len(payload.encode("utf-8")) + 1024
        try:
            costs = litellm.cost_per_token(
                model=self.model,
                prompt_tokens=input_tokens,
                completion_tokens=self.max_tokens,
            )
            amount = math.fsum(costs)
            if not math.isfinite(amount) or amount < 0:
                raise ValueError("invalid price")
        except Exception:
            raise ModelProviderError(
                "Cannot reserve budget: model pricing is unavailable.",
                error_type="UnknownModelPricing",
            ) from None
        return Reservation(self.model, self.max_tokens, amount)

    def _record_request(self, generation) -> None:
        if generation is not None:
            generation.update(
                model=self.model,
                model_parameters={
                    "max_tokens": self.max_tokens,
                    "timeout": self.timeout,
                    "num_retries": 0,
                    **self._sampling_options,
                },
            )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: type[BaseModel],
        schema_name: str,
        prompt_version: str,
        observation_name: str,
    ) -> StructuredCompletion:
        reservation = current_reservation.get()
        if reservation is not None:
            quote = self.quote(messages, response_schema)
            if (
                quote.model != reservation.model
                or quote.max_tokens != reservation.max_tokens
                or quote.reserved_cost_usd > reservation.reserved_cost_usd
            ):
                raise ModelProviderError(
                    "Model configuration or price changed after budget reservation.",
                    error_type="ReservationChanged",
                )
        with self._observation(
            observation_name,
            as_type="generation",
            input=messages,
            metadata={"prompt_version": prompt_version},
        ) as generation:
            self._record_request(generation)
            response = await self._complete(messages, response_schema, schema_name)
            usage, cost = self._usage_and_cost(response)
            self._record_response(generation, response, usage, cost, prompt_version)
            return StructuredCompletion(response, usage, cost)

    async def _complete(
        self,
        messages: list[dict[str, str]],
        response_schema: type[BaseModel],
        schema_name: str,
    ) -> litellm.ModelResponse:
        try:
            response = await litellm.acompletion(
                model=self.model,
                **self._provider_options,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": response_schema.model_json_schema(),
                    },
                },
                max_tokens=self.max_tokens,
                **self._sampling_options,
                timeout=self.timeout,
                num_retries=0,
                caching=False,
                stream=False,
            )
        except (
            litellm.AuthenticationError,
            litellm.BadRequestError,
            litellm.PermissionDeniedError,
            litellm.NotFoundError,
        ) as error:
            # Configuration errors do not improve by repeating a paid activity.
            # Do not put SDK exception messages (which may contain requests)
            # or credentials into Temporal failure histories.
            raise ModelProviderError(
                "Model provider rejected the request; check credentials, "
                "model access and structured-output support.",
                error_type=type(error).__name__,
            ) from None
        if not isinstance(response, litellm.ModelResponse):
            raise ModelProviderError(
                "Expected a non-streaming model response.",
                error_type="UnexpectedResponseType",
            )
        return response

    @staticmethod
    def _usage_and_cost(
        response: litellm.ModelResponse,
    ) -> tuple[dict[str, int], float | None]:
        usage = {}
        if response.usage is not None:
            usage = {
                name: value
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(value := getattr(response.usage, name, None), int)
            }
        try:
            cost = (
                litellm.completion_cost(completion_response=response) if usage else None
            )
        except Exception:
            # New model pricing may be absent from LiteLLM's catalog.
            cost = None
        return usage, cost

    def _record_response(
        self,
        generation,
        response: litellm.ModelResponse,
        usage: dict[str, int],
        cost: float | None,
        prompt_version: str,
    ) -> None:
        if not response.choices:
            return
        choice = response.choices[0]
        content = choice.message.content
        if generation is not None:
            generation.update(
                output=content,
                usage_details={
                    label: usage[name]
                    for name, label in (
                        ("prompt_tokens", "input"),
                        ("completion_tokens", "output"),
                    )
                    if name in usage
                }
                if usage
                else None,
                cost_details={"total": cost} if cost is not None else None,
                metadata={
                    "prompt_version": prompt_version,
                    "response_model": response.model,
                    "response_id": response.id,
                    "finish_reason": choice.finish_reason,
                },
            )
