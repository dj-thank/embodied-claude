"""Environment configuration for loopback-only local inference."""

from __future__ import annotations

import ipaddress
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class InferenceConfig:
    """Validated configuration shared by LM Studio and llama.cpp adapters."""

    base_url: str = "http://127.0.0.1:1234/v1"
    model: str | None = None
    api_token: str | None = field(default=None, repr=False)
    timeout_seconds: float = 30.0
    max_prompt_chars: int = 16_000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> InferenceConfig:
        source = os.environ if env is None else env
        base_url = source.get(
            "SANPOLOID_LOCAL_LLM_BASE_URL",
            cls.base_url,
        ).strip()
        _validate_loopback_base_url(base_url)

        model = source.get("SANPOLOID_LOCAL_LLM_MODEL", "").strip() or None
        if model is not None and len(model) > 512:
            raise ValueError("SANPOLOID_LOCAL_LLM_MODEL must be at most 512 characters")
        api_token = source.get("SANPOLOID_LOCAL_LLM_API_TOKEN", "").strip() or None
        timeout_seconds = _positive_float(
            source.get("SANPOLOID_LOCAL_LLM_TIMEOUT_SECONDS", "30"),
            "SANPOLOID_LOCAL_LLM_TIMEOUT_SECONDS",
        )
        max_prompt_chars = _positive_int(
            source.get("SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS", "16000"),
            "SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS",
        )
        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_token=api_token,
            timeout_seconds=timeout_seconds,
            max_prompt_chars=max_prompt_chars,
        )


def _validate_loopback_base_url(base_url: str) -> None:
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("local LLM base URL is invalid") from error

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("local LLM base URL must use HTTP or HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("local LLM base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("local LLM base URL must not contain query or fragment data")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("local LLM base URL port is invalid")

    hostname = parsed.hostname.lower()
    if hostname == "localhost":
        return
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError as error:
        raise ValueError("local LLM base URL must use a loopback address") from error
    if not address.is_loopback:
        raise ValueError("local LLM base URL must use a loopback address")


def _positive_float(raw_value: str, name: str) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a positive number") from error
    if not math.isfinite(value) or not 0 < value <= 300:
        raise ValueError(f"{name} must be between 0 and 300")
    return value


def _positive_int(raw_value: str, name: str) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if not 0 < value <= 1_000_000:
        raise ValueError(f"{name} must be between 1 and 1000000")
    return value
