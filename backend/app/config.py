"""Runtime configuration for the Investigative AI Training Arena backend."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

PROVIDERS = ("cloud", "openai_compatible", "mock")
# Hosted vendors used by the "cloud" provider. The vendor of a model is inferred from its id.
VENDOR_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google Gemini"}
VENDOR_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GEMINI_API_KEY"}
DEFAULT_CLOUD_MODELS = "gpt-6-luna,claude-haiku-5-5,gemini-3.5-flash-lite"


def vendor_for(model_id: str | None) -> str | None:
    """Hosted vendor inferred from a model id; None for gateway-only or unknown ids."""
    m = (model_id or "").lower()
    if m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gemini"):
        return "google"
    return None


def _split(raw: str | None) -> list[str]:
    return [m.strip() for m in (raw or "").split(",") if m.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARENA_", env_file=".env", extra="ignore", populate_by_name=True)

    provider: str = "auto"  # auto | cloud | openai_compatible | mock

    # Hosted vendor APIs ("cloud"): one deepagents candidate per listed model; the vendor is inferred from the id
    # (gpt-* -> OpenAI, claude-* -> Anthropic, gemini-* -> Google). Keys use the vendors' standard variable names.
    models: str = DEFAULT_CLOUD_MODELS
    subject_models: str | None = None  # defaults to the assistant list
    grader_model: str | None = None  # defaults to the first assistant model
    openai_key: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "openai_key"))
    anthropic_key: str | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "anthropic_key"))
    google_key: str | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "google_key"))

    # OpenAI-compatible gateway (e.g. the challenge-provided gpt-oss-20b endpoint, or a local Ollama server)
    gateway_base_url: str | None = Field(default=None, validation_alias=AliasChoices("ARENA_OPENAI_BASE_URL", "ARENA_GATEWAY_BASE_URL", "gateway_base_url"))
    gateway_api_key: str | None = Field(default=None, validation_alias=AliasChoices("ARENA_OPENAI_API_KEY", "ARENA_GATEWAY_API_KEY", "gateway_api_key"))
    openai_model: str = "gpt-oss-20b"
    # Optional comma-separated lists: one deepagents candidate is registered per model, so several gateway
    # models (e.g. gpt-oss:20b,llama3.1:8b,mistral-nemo:12b on Ollama) compete under equal budgets.
    openai_assistant_models: str | None = None
    openai_subject_models: str | None = None  # defaults to the assistant list
    openai_grader_model: str | None = None  # defaults to the first assistant model
    openai_temperature: float = 0.3

    # Login. The admin account is created on first start; investigators can also register themselves.
    admin_user: str = "trainer"
    admin_password: str = "arena-demo"
    secret_key: str | None = None  # bearer-token signing key; generated and stored in data_dir when unset
    auth_required: bool = True

    # Throughput. Requests per minute per vendor (0 = no client-side limit); the Gemini free tier allows 15/min.
    openai_rpm: int = 0
    anthropic_rpm: int = 0
    google_rpm: int = 14
    bakeoff_workers: int = 4  # trials run concurrently in a bake-off
    llm_cache: bool = True  # persist every model response in data_dir/llm_cache.sqlite and reuse identical calls

    # Optional Neo4j evidence graph (app/graph.py). Unset = off; the JSON store is always the system of record.
    neo4j_uri: str | None = None  # e.g. bolt://localhost:7687 or neo4j+s://xxxx.databases.neo4j.io
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"

    data_dir: Path = Path("./data")
    default_max_turns: int = 12
    coaching_latency_target_ms: int = 3000

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings: PydanticBaseSettingsSource, env_settings: PydanticBaseSettingsSource,
                                   dotenv_settings: PydanticBaseSettingsSource, file_secret_settings: PydanticBaseSettingsSource):
        # backend/.env wins over the process environment: a stale machine-wide OPENAI_API_KEY / ANTHROPIC_API_KEY
        # must not silently shadow the key configured for this project.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    # ----- provider resolution -------------------------------------------------------------------------------
    @property
    def resolved_provider(self) -> str:
        p = "cloud" if self.provider == "anthropic" else self.provider  # "anthropic" is the pre-cloud name
        if p in PROVIDERS:
            return p
        if self.gateway_base_url and self.gateway_api_key:
            return "openai_compatible"
        if any(self.key_for_vendor(v) for v in VENDOR_ENV):
            return "cloud"
        return "mock"

    @property
    def provider_label(self) -> str:
        p = self.resolved_provider
        if p == "openai_compatible":
            return "OpenAI-compatible gateway"
        if p == "cloud":
            vendors = dict.fromkeys(vendor_for(m) for m in self.models_for("assistant"))
            return " · ".join(VENDOR_LABELS.get(v, v or "unknown vendor") for v in vendors)
        return "mock runtime"

    # ----- credentials -----------------------------------------------------------------------------------------
    def rpm_for_vendor(self, vendor: str | None) -> int:
        return {"openai": self.openai_rpm, "anthropic": self.anthropic_rpm, "google": self.google_rpm}.get(vendor or "", 0)

    def key_for_vendor(self, vendor: str | None) -> str | None:
        return {"openai": self.openai_key, "anthropic": self.anthropic_key, "google": self.google_key}.get(vendor or "") or None

    def missing_credential(self, model_id: str | None) -> str | None:
        """Why a cloud model cannot be called right now (None when it can)."""
        v = vendor_for(model_id)
        if v is None:
            return f"cannot infer the vendor of model '{model_id}' (expected a gpt-*, claude-* or gemini-* id)"
        if not self.key_for_vendor(v):
            return f"no {VENDOR_LABELS[v]} credential: set {VENDOR_ENV[v]} in backend/.env"
        return None

    # ----- model lists -----------------------------------------------------------------------------------------
    def model_for(self, role: str) -> str | None:
        """First model id used by deepagents candidates for a role (assistant | subject | grader)."""
        models = self.models_for(role)
        return models[0] if models else None

    def models_for(self, role: str) -> list[str]:
        """All model ids registered for a role."""
        # The mock provider keeps the model-backed candidate ids so the whole UI works offline: the registry runs
        # them on the deterministic mock runtime and reports that as the effective runtime.
        if self.resolved_provider == "openai_compatible":
            raw = {
                "assistant": self.openai_assistant_models,
                "subject": self.openai_subject_models or self.openai_assistant_models,
                "grader": self.openai_grader_model or self.openai_assistant_models,
            }[role]
            return _split(raw) or [self.openai_model]
        assistants = _split(self.models) or _split(DEFAULT_CLOUD_MODELS)
        return {
            "assistant": assistants,
            "subject": _split(self.subject_models) or assistants,
            "grader": _split(self.grader_model)[:1] or assistants[:1],
        }[role]


@lru_cache
def get_settings() -> Settings:
    return Settings()
