"""Task-oriented prompt presets for small local Japanese models."""

from __future__ import annotations

from typing import Literal

PromptPreset = Literal["default", "strict", "concise", "json"]

_PRESETS = {
    "default": "",
    "strict": (
        "指示されたタスク、語句、長さ、出力形式を厳守してください。"
        "求められていない説明、前置き、補足、言い換えは出力しないでください。"
    ),
    "concise": (
        "日本語で簡潔に答えてください。要点だけを述べ、前置きや同じ内容の反復を"
        "避けてください。"
    ),
    "json": (
        "有効なJSONだけを出力してください。Markdownコードフェンス、説明、前置き、"
        "末尾の補足は出力しないでください。"
    ),
}


def available_prompt_presets() -> tuple[str, ...]:
    """Return stable preset names exposed through the MCP schema and CLI."""
    return tuple(_PRESETS)


def compose_system_prompt(preset: PromptPreset | str, system_prompt: str) -> str:
    """Compose one preset with caller instructions without hiding either source."""
    if not isinstance(preset, str) or preset not in _PRESETS:
        choices = ", ".join(_PRESETS)
        raise ValueError(f"preset must be one of: {choices}")
    preset_prompt = _PRESETS[preset]
    if preset_prompt and system_prompt:
        return f"{preset_prompt}\n\n{system_prompt}"
    return preset_prompt or system_prompt
