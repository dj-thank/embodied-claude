"""Explicit sampling profiles used for reproducible local-model evaluation."""

from typing import Literal

GenerationProfile = Literal["runtime_default", "lfm2_5_jp"]

_GENERATION_PROFILES: dict[str, dict[str, int | float]] = {
    "runtime_default": {},
    "lfm2_5_jp": {"top_k": 50, "repeat_penalty": 1.05},
}


def available_generation_profiles() -> tuple[str, ...]:
    """Return explicit profiles without changing MCP or runtime defaults."""
    return tuple(_GENERATION_PROFILES)


def generation_parameters(
    profile: GenerationProfile | str,
) -> dict[str, int | float]:
    """Resolve one named, inspectable set of backend sampling parameters."""
    if not isinstance(profile, str) or profile not in _GENERATION_PROFILES:
        choices = ", ".join(_GENERATION_PROFILES)
        raise ValueError(f"generation_profile must be one of: {choices}")
    return dict(_GENERATION_PROFILES[profile])
