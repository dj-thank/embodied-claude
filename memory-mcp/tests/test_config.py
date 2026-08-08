"""Tests for fail-closed memory server configuration."""

import pytest

from memory_mcp.config import ServerConfig


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("false", False),
        ("unexpected", False),
        ("true", True),
        ("1", True),
    ],
)
def test_memory_deletion_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    expected: bool,
) -> None:
    if value is None:
        monkeypatch.delenv("MEMORY_DELETION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("MEMORY_DELETION_ENABLED", value)

    assert ServerConfig.from_env().deletion_enabled is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("invalid", 300), ("1", 30), ("9999", 3600), ("120", 120)],
)
def test_deletion_token_ttl_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: int,
) -> None:
    monkeypatch.setenv("MEMORY_DELETION_TOKEN_TTL_SECONDS", value)

    assert ServerConfig.from_env().deletion_token_ttl_seconds == expected
