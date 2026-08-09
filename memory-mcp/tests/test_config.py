"""Tests for fail-closed memory server configuration."""

from pathlib import Path

import pytest

import memory_mcp.config as config_module
from memory_mcp.config import MemoryConfig, ServerConfig


def test_memory_backend_is_selected_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_BACKEND", "sqlite")

    assert MemoryConfig.from_env().backend == "sqlite"


def test_unknown_memory_backend_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_BACKEND", "mystery")

    with pytest.raises(ValueError, match="MEMORY_BACKEND"):
        MemoryConfig.from_env()


def test_direct_memory_config_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="backend"):
        MemoryConfig("/tmp/memory", "memories", backend="mystery")


@pytest.mark.parametrize(
    ("chroma_available", "expected"),
    [(True, "chroma"), (False, "sqlite")],
)
def test_auto_backend_preserves_rich_installs_and_lightens_clean_installs(
    monkeypatch: pytest.MonkeyPatch,
    chroma_available: bool,
    expected: str,
) -> None:
    monkeypatch.delenv("MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("MEMORY_DB_PATH", raising=False)
    monkeypatch.setattr(
        config_module,
        "find_spec",
        lambda _name: object() if chroma_available else None,
    )

    config = MemoryConfig.from_env()

    assert config.backend == expected
    assert Path(config.db_path).name == expected


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
