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


def test_strict_preset_adds_explicit_instruction_without_replacing_user_system_prompt() -> None:
    transport = MemoryJsonTransport(
        [{"choices": [{"message": {"content": "さんぽ日和やで。"}}]}]
    )
    inference = LocalInference(
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_MODEL": "local-jp"}),
        transport,
    )

    result = inference.complete(
        "『さんぽ日和やで。』だけを返してください。",
        system_prompt="日本語で答えてください。",
        preset="strict",
    )

    assert result.text == "さんぽ日和やで。"
    messages = transport.requests[0]["body"]["messages"]
    assert messages[0]["role"] == "system"
    assert "出力形式" in messages[0]["content"]
    assert "前置き" in messages[0]["content"]
    assert messages[0]["content"].endswith("日本語で答えてください。")
    assert messages[1] == {
        "role": "user",
        "content": "『さんぽ日和やで。』だけを返してください。",
    }


def test_lfm2_5_jp_generation_profile_sends_model_card_sampling_parameters() -> None:
    transport = MemoryJsonTransport(
        [{"choices": [{"message": {"content": "さんぽ日和やで。"}}]}]
    )
    inference = LocalInference(
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_MODEL": "local-jp"}),
        transport,
    )

    inference.complete("短く答えて", generation_profile="lfm2_5_jp")

    request_body = transport.requests[0]["body"]
    assert request_body["top_k"] == 50
    assert request_body["repeat_penalty"] == 1.05


def test_unknown_prompt_preset_is_rejected_before_transport() -> None:
    transport = MemoryJsonTransport([])
    inference = LocalInference(
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_MODEL": "local-jp"}),
        transport,
    )

    with pytest.raises(ValueError, match="preset"):
        inference.complete("ping", preset="unknown")
    with pytest.raises(ValueError, match="generation_profile"):
        inference.complete("ping", generation_profile="unknown")

    assert transport.requests == []


def test_prompt_bound_includes_preset_instruction() -> None:
    transport = MemoryJsonTransport([])
    inference = LocalInference(
        InferenceConfig.from_env(
            {
                "SANPOLOID_LOCAL_LLM_MODEL": "local-jp",
                "SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS": "20",
            }
        ),
        transport,
    )

    with pytest.raises(ValueError, match="prompt is too long"):
        inference.complete("ping", preset="strict")

    assert transport.requests == []


def test_json_preset_requests_backend_level_json_object_constraint() -> None:
    transport = MemoryJsonTransport(
        [{"choices": [{"message": {"content": '{"状態":"正常"}'}}]}]
    )
    inference = LocalInference(
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_MODEL": "local-jp"}),
        transport,
    )

    result = inference.complete(
        "状態をJSONで返して",
        preset="json",
        json_schema={
            "type": "object",
            "properties": {"状態": {"type": "string", "const": "正常"}},
            "required": ["状態"],
            "additionalProperties": False,
        },
    )

    assert result.text == '{"状態":"正常"}'
    assert result.parsed_json == {"状態": "正常"}
    assert result.as_dict()["parsed_json"] == {"状態": "正常"}
    assert transport.requests[0]["body"]["response_format"] == {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {"状態": {"type": "string", "const": "正常"}},
            "required": ["状態"],
            "additionalProperties": False,
        },
        "json_schema": {
            "name": "sanpoloid_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"状態": {"type": "string", "const": "正常"}},
                "required": ["状態"],
                "additionalProperties": False,
            },
        },
    }


def test_json_schema_requires_json_preset_and_is_size_bounded() -> None:
    inference = LocalInference(
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_MODEL": "local-jp"}),
        MemoryJsonTransport([]),
    )

    with pytest.raises(ValueError, match="json preset"):
        inference.complete("ping", json_schema={"type": "object"})
    with pytest.raises(ValueError, match="json_schema is too large"):
        inference.complete(
            "ping",
            preset="json",
            json_schema={"description": "x" * 20_000},
        )


def test_json_preset_rejects_backend_output_that_violates_the_constraint() -> None:
    inference = LocalInference(
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_MODEL": "local-jp"}),
        MemoryJsonTransport(
            [{"choices": [{"message": {"content": "```json\n{}\n```"}}]}]
        ),
    )

    with pytest.raises(InferenceProtocolError, match="JSON constraint"):
        inference.complete("JSONで返して", preset="json")


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
    assert "HTTP 302" in status["error"]


def test_http_client_error_is_reported_as_protocol_rejection_not_unavailability() -> None:
    class RejectingHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"may echo private prompt"}}')

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RejectingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        inference = LocalInference(
            InferenceConfig.from_env(
                {
                    "SANPOLOID_LOCAL_LLM_BASE_URL": (
                        f"http://127.0.0.1:{server.server_port}/v1"
                    ),
                    "SANPOLOID_LOCAL_LLM_MODEL": "model",
                }
            ),
            UrllibJsonTransport(),
        )
        with pytest.raises(InferenceProtocolError, match="HTTP 400") as captured:
            inference.complete("private prompt")
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert "private prompt" not in str(captured.value)
