"""Runtime configuration for the Investigative AI Training Arena backend."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDERS = ("openai_compatible", "anthropic", "mock")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARENA_", env_file=".env", extra="ignore")

    provider: str = "auto"  # auto | openai_compatible | anthropic | mock

    # OpenAI-compatible gateway (e.g. the challenge-provided gpt-oss-20b endpoint)
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-oss-20b"

    # Anthropic
    assistant_model: str = "claude-opus-5-5"
    subject_model: str = "claude-opus-5-5"
    grader_model: str = "claude-sonnet-5-5"

    data_dir: Path = Path("./data")
    default_max_turns: int = 12
    coaching_latency_target_ms: int = 3000

    @property
    def resolved_provider(self) -> str:
        if self.provider in PROVIDERS:
            return self.provider
        if self.openai_base_url and self.openai_api_key:
            return "openai_compatible"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "mock"

    def model_for(self, role: str) -> str | None:
        """Model id used by deepagents candidates for a role (assistant | subject | grader)."""
        p = self.resolved_provider
        if p == "openai_compatible":
            return self.openai_model
        if p == "anthropic":
            return {"assistant": self.assistant_model, "subject": self.subject_model, "grader": self.grader_model}[role]
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
