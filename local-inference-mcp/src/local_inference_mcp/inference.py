"""Deep module for bounded OpenAI-compatible local inference."""

from __future__ import annotations

import json
import math
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .config import InferenceConfig
from .prompts import PromptPreset, compose_system_prompt
from .sampling import GenerationProfile, generation_parameters

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_JSON_SCHEMA_BYTES = 16 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep loopback requests from redirecting prompt data elsewhere."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class InferenceError(RuntimeError):
    """Base error surfaced by the local inference interface."""


class InferenceUnavailableError(InferenceError):
    """The configured loopback endpoint could not be reached."""


class InferenceProtocolError(InferenceError):
    """The endpoint returned an incompatible or incomplete response."""


class JsonTransport(Protocol):
    """Internal seam for one bounded JSON request."""

    def request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None,
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]: ...


class UrllibJsonTransport:
    """Standard-library JSON transport with bounded response reads."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None,
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        request_headers = dict(headers)
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=payload,
            headers=request_headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                encoded = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if 400 <= error.code < 500:
                raise InferenceProtocolError(
                    f"local inference endpoint rejected the request (HTTP {error.code})"
                ) from error
            raise InferenceUnavailableError(
                f"local inference endpoint is unavailable (HTTP {error.code})"
            ) from error
        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            OSError,
        ) as error:
            raise InferenceUnavailableError(
                f"local inference endpoint is unavailable ({type(error).__name__})"
            ) from error
        if len(encoded) > _MAX_RESPONSE_BYTES:
            raise InferenceProtocolError("local inference response exceeds 2 MiB")
        try:
            decoded = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InferenceProtocolError("local inference response is not valid JSON") from error
        if not isinstance(decoded, dict):
            raise InferenceProtocolError("local inference response must be a JSON object")
        return decoded


@dataclass(frozen=True)
class InferenceResult:
    """Normalized text completion returned through the MCP seam."""

    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
        }


class LocalInference:
    """Bounded local chat inference behind a two-method interface."""

    def __init__(self, config: InferenceConfig, transport: JsonTransport) -> None:
        self._config = config
        self._transport = transport

    def status(self) -> dict[str, Any]:
        """Report endpoint availability without starting or loading a model."""
        try:
            models = list(self._list_models())
        except InferenceError as error:
            return {
                "available": False,
                "endpoint": self._config.base_url,
                "configured_model": self._config.model,
                "models": [],
                "error": str(error),
            }
        return {
            "available": True,
            "endpoint": self._config.base_url,
            "configured_model": self._config.model,
            "models": models,
        }

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        model: str | None = None,
        preset: PromptPreset = "default",
        generation_profile: GenerationProfile = "runtime_default",
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> InferenceResult:
        """Generate one non-streaming completion with explicit resource bounds."""
        if not isinstance(system_prompt, str):
            raise ValueError("system_prompt must be text")
        composed_system_prompt = compose_system_prompt(preset, system_prompt)
        sampling_parameters = generation_parameters(generation_profile)
        normalized_json_schema = _validate_json_schema(preset, json_schema)
        self._validate_completion_input(
            prompt=prompt,
            system_prompt=composed_system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if model is not None and not isinstance(model, str):
            raise ValueError("model must be text")
        selected_model = (model or "").strip() or self._config.model
        if selected_model is not None and len(selected_model) > 512:
            raise ValueError("model must be at most 512 characters")
        if selected_model is None:
            models = self._list_models()
            if not models:
                raise InferenceProtocolError("local inference endpoint exposes no models")
            if len(models) > 1:
                raise InferenceProtocolError(
                    "multiple models are available; select one with SANPOLOID_LOCAL_LLM_MODEL "
                    "or the model argument"
                )
            selected_model = models[0]

        messages: list[dict[str, str]] = []
        if composed_system_prompt:
            messages.append({"role": "system", "content": composed_system_prompt})
        messages.append({"role": "user", "content": prompt})
        request_body: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        request_body.update(sampling_parameters)
        if preset == "json":
            response_schema = normalized_json_schema or {"type": "object"}
            request_body["response_format"] = {
                "type": "json_schema",
                # llama.cpp documents this direct field; LM Studio accepts it alongside
                # the OpenAI-compatible nested shape below.
                "schema": response_schema,
                "json_schema": {
                    "name": "sanpoloid_response",
                    "strict": True,
                    "schema": response_schema,
                },
            }
        response = self._request(
            "POST",
            "/chat/completions",
            body=request_body,
        )
        text = _completion_text(response)
        response_model = response.get("model")
        normalized_model = (
            response_model.strip()
            if isinstance(response_model, str) and response_model.strip()
            else selected_model
        )
        usage = response.get("usage")
        usage_mapping = usage if isinstance(usage, Mapping) else {}
        return InferenceResult(
            text=text,
            model=normalized_model,
            prompt_tokens=_optional_int(usage_mapping.get("prompt_tokens")),
            completion_tokens=_optional_int(usage_mapping.get("completion_tokens")),
            total_tokens=_optional_int(usage_mapping.get("total_tokens")),
        )

    def _list_models(self) -> tuple[str, ...]:
        response = self._request("GET", "/models", body=None)
        data = response.get("data")
        if not isinstance(data, list):
            raise InferenceProtocolError("model list response is missing data")
        models: list[str] = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                models.append(model_id.strip())
        return tuple(dict.fromkeys(models))

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self._config.api_token:
            headers["Authorization"] = f"Bearer {self._config.api_token}"
        return self._transport.request(
            method,
            f"{self._config.base_url}{path}",
            body=body,
            headers=headers,
            timeout=self._config.timeout_seconds,
        )

    def _validate_completion_input(
        self,
        *,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> None:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must not be empty")
        if len(prompt) + len(system_prompt) > self._config.max_prompt_chars:
            raise ValueError("combined prompt is too long")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)
            or not 0 <= temperature <= 2
        ):
            raise ValueError("temperature must be between 0 and 2")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= 4096
        ):
            raise ValueError("max_tokens must be between 1 and 4096")


def _completion_text(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise InferenceProtocolError("completion response is missing choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise InferenceProtocolError("completion choice must be an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise InferenceProtocolError("completion choice is missing a message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise InferenceProtocolError("completion message is missing text content")
    return content


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _validate_json_schema(
    preset: PromptPreset,
    json_schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if json_schema is None:
        return None
    if preset != "json":
        raise ValueError("json_schema requires the json preset")
    if not isinstance(json_schema, dict):
        raise ValueError("json_schema must be an object")
    try:
        encoded = json.dumps(json_schema, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        raise ValueError("json_schema must contain JSON values") from error
    if len(encoded) > _MAX_JSON_SCHEMA_BYTES:
        raise ValueError("json_schema is too large (maximum 16 KiB)")
    return json_schema
