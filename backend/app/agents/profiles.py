"""Harness profile: investigative agents must not get filesystem, shell or subagent tools.

deepagents adds those by default; the profile strips them for every Anthropic model
(and for the fake chat model used in tests)."""
from __future__ import annotations

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile

_ARENA_PROFILE = HarnessProfile(
    excluded_tools=frozenset({"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute", "task"}),
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
)
_registered: set[str] = set()


def ensure_profiles(model=None) -> None:
    """Register the arena profile for Anthropic models and for `model`'s provider key."""
    keys = {"anthropic"}
    if model is not None:
        from deepagents._models import get_model_provider

        provider = get_model_provider(model)
        if provider:
            keys.add(provider)
    for key in keys - _registered:
        register_harness_profile(key, _ARENA_PROFILE)
        _registered.add(key)
