"""Tests at the local-inference module interface."""

import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from local_inference_mcp.config import InferenceConfig
from local_inference_mcp.inference import (
    InferenceProtocolError,
    LocalInference,
    UrllibJsonTransport,
)


@dataclass
class MemoryJsonTransport:
    responses: list[dict[str, Any]]
    requests: list[dict[str, Any]] = field(default_factory=list)

    def request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None,
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "body": body,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


def test_status_lists_models_without_starting_or_loading_them() -> None:
    transport = MemoryJsonTransport(
        [{"data": [{"id": "local-jp"}, {"id": "local-code"}]}]
    )
    inference = LocalInference(InferenceConfig.from_env({}), transport)

    status = inference.status()

    assert status == {
        "available": True,
        "endpoint": "http://127.0.0.1:1234/v1",
        "configured_model": None,
        "models": ["local-jp", "local-code"],
    }
    assert transport.requests == [
        {
            "method": "GET",
            "url": "http://127.0.0.1:1234/v1/models",
            "body": None,
            "headers": {"Accept": "application/json"},
            "timeout": 30.0,
        }
    ]


def test_complete_discovers_one_model_and_returns_normalized_usage() -> None:
    transport = MemoryJsonTransport(
        [
            {"data": [{"id": "local-jp"}]},
            {
                "model": "local-jp",
                "choices": [{"message": {"content": "散歩日和やで。"}}],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "total_tokens": 19,
                },
            },
        ]
    )
    inference = LocalInference(InferenceConfig.from_env({}), transport)

    result = inference.complete(
        "今日の一言を返して",
        system_prompt="簡潔な日本語で答える",
        temperature=0.3,
        max_tokens=64,
    )

    assert result.as_dict() == {
        "text": "散歩日和やで。",
        "model": "local-jp",
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 7,
            "total_tokens": 19,
        },
    }
    completion_request = transport.requests[1]
    assert completion_request["url"].endswith("/chat/completions")
    assert completion_request["body"] == {
        "model": "local-jp",
        "messages": [
            {"role": "system", "content": "簡潔な日本語で答える"},
            {"role": "user", "content": "今日の一言を返して"},
        ],
        "temperature": 0.3,
        "max_tokens": 64,
        "stream": False,
    }


def test_configured_model_skips_model_discovery_and_sends_optional_token() -> None:
    transport = MemoryJsonTransport(
        [{"choices": [{"message": {"content": "ok"}}]}]
    )
    config = InferenceConfig.from_env(
        {
            "SANPOLOID_LOCAL_LLM_MODEL": "configured-model",
            "SANPOLOID_LOCAL_LLM_API_TOKEN": "local-secret",
        }
    )
    inference = LocalInference(config, transport)

    result = inference.complete("ping")

    assert result.model == "configured-model"
    assert len(transport.requests) == 1
    assert transport.requests[0]["headers"]["Authorization"] == "Bearer local-secret"


def test_multiple_discovered_models_require_an_explicit_choice() -> None:
    transport = MemoryJsonTransport(
        [{"data": [{"id": "model-a"}, {"id": "model-b"}]}]
    )
    inference = LocalInference(InferenceConfig.from_env({}), transport)

    with pytest.raises(InferenceProtocolError, match="multiple models"):
        inference.complete("ping")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"prompt": ""}, "prompt"),
        ({"prompt": "x", "temperature": -0.1}, "temperature"),
        ({"prompt": "x", "temperature": 2.1}, "temperature"),
        ({"prompt": "x", "temperature": float("nan")}, "temperature"),
        ({"prompt": "x", "temperature": True}, "temperature"),
        ({"prompt": "x", "max_tokens": 0}, "max_tokens"),
        ({"prompt": "x", "max_tokens": 4097}, "max_tokens"),
        ({"prompt": "x", "max_tokens": True}, "max_tokens"),
    ],
)
def test_completion_input_is_bounded(kwargs: dict[str, Any], message: str) -> None:
    inference = LocalInference(
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_MODEL": "model"}),
        MemoryJsonTransport([]),
    )

    with pytest.raises(ValueError, match=message):
        inference.complete(**kwargs)


def test_combined_prompt_length_is_bounded_before_transport() -> None:
    transport = MemoryJsonTransport([])
    inference = LocalInference(
        InferenceConfig.from_env(
            {
                "SANPOLOID_LOCAL_LLM_MODEL": "model",
                "SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS": "5",
            }
        ),
        transport,
    )

    with pytest.raises(ValueError, match="prompt is too long"):
        inference.complete("1234", system_prompt="12")

    assert transport.requests == []


def test_http_transport_does_not_follow_redirects() -> None:
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            self.send_response(302)
            self.send_header("Location", "https://example.com/models")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = InferenceConfig.from_env(
            {
                "SANPOLOID_LOCAL_LLM_BASE_URL": (
                    f"http://127.0.0.1:{server.server_port}/v1"
                )
            }
        )
        status = LocalInference(config, UrllibJsonTransport()).status()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert status["available"] is False
    assert "HTTPError" in status["error"]
