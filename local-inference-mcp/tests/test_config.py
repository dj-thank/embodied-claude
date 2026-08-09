"""Configuration contract for loopback-only local inference."""

import pytest

from local_inference_mcp.config import InferenceConfig


def test_defaults_target_lm_studio_without_assuming_a_model() -> None:
    config = InferenceConfig.from_env({})

    assert config.base_url == "http://127.0.0.1:1234/v1"
    assert config.model is None
    assert config.timeout_seconds == 30.0
    assert config.max_prompt_chars == 16_000
    assert config.api_token is None


def test_environment_can_select_a_local_runtime_and_model() -> None:
    config = InferenceConfig.from_env(
        {
            "SANPOLOID_LOCAL_LLM_BASE_URL": "http://[::1]:8080/v1/",
            "SANPOLOID_LOCAL_LLM_MODEL": "local-japanese-model",
            "SANPOLOID_LOCAL_LLM_API_TOKEN": "secret-token",
            "SANPOLOID_LOCAL_LLM_TIMEOUT_SECONDS": "12.5",
            "SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS": "8000",
        }
    )

    assert config.base_url == "http://[::1]:8080/v1"
    assert config.model == "local-japanese-model"
    assert config.timeout_seconds == 12.5
    assert config.max_prompt_chars == 8_000
    assert config.api_token == "secret-token"
    assert "secret-token" not in repr(config)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://example.com/v1",
        "http://192.168.1.20:1234/v1",
        "http://user:password@127.0.0.1:1234/v1",
        "ftp://127.0.0.1/v1",
        "http://127.0.0.1:1234/v1?token=secret",
    ],
)
def test_non_loopback_or_ambiguous_endpoints_are_rejected(base_url: str) -> None:
    with pytest.raises(ValueError):
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_BASE_URL": base_url})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SANPOLOID_LOCAL_LLM_TIMEOUT_SECONDS", "0"),
        ("SANPOLOID_LOCAL_LLM_TIMEOUT_SECONDS", "nan"),
        ("SANPOLOID_LOCAL_LLM_TIMEOUT_SECONDS", "301"),
        ("SANPOLOID_LOCAL_LLM_TIMEOUT_SECONDS", "not-a-number"),
        ("SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS", "0"),
        ("SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS", "1000001"),
        ("SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS", "not-a-number"),
    ],
)
def test_invalid_numeric_limits_are_rejected(name: str, value: str) -> None:
    with pytest.raises(ValueError):
        InferenceConfig.from_env({name: value})


def test_model_identifier_is_bounded() -> None:
    with pytest.raises(ValueError, match="512"):
        InferenceConfig.from_env({"SANPOLOID_LOCAL_LLM_MODEL": "x" * 513})
