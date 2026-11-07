"""Provider resolution and candidate registration for the hosted three-vendor configuration."""
import pytest

from app.agents.candidates import CandidateRegistry
from app.config import Settings, vendor_for


@pytest.fixture(autouse=True)
def no_vendor_keys(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_vendor_is_inferred_from_the_model_id():
    assert vendor_for("gpt-6-luna") == "openai"
    assert vendor_for("claude-haiku-5-5") == "anthropic"
    assert vendor_for("gemini-3.5-flash-lite") == "google"
    assert vendor_for("llama3.1:8b") is None


def test_auto_provider_prefers_gateway_then_cloud_then_mock():
    assert Settings(provider="auto", _env_file=None).resolved_provider == "mock"
    assert Settings(provider="auto", google_key="g", _env_file=None).resolved_provider == "cloud"
    assert Settings(provider="auto", google_key="g", gateway_base_url="http://x", gateway_api_key="k", _env_file=None).resolved_provider == "openai_compatible"
    assert Settings(provider="anthropic", _env_file=None).resolved_provider == "cloud"  # legacy name


def test_cloud_registers_one_candidate_per_model_and_flags_missing_keys():
    s = Settings(provider="cloud", models="gpt-6-luna,claude-haiku-5-5,gemini-3.5-flash-lite",
                 openai_key="o", google_key="g", _env_file=None)
    assert s.models_for("subject") == s.models_for("assistant") and s.model_for("grader") == "gpt-6-luna"
    assert s.provider_label == "OpenAI · Anthropic · Google Gemini"
    reg = CandidateRegistry(s)
    assistants = reg.list("assistant")
    ids = [c["id"] for c in assistants]
    assert ids[:4] == ["asst-gpt-6-luna-v1", "asst-claude-haiku-5-5-v1", "asst-gemini-3.5-flash-lite-v1", "asst-gpt-6-luna-rubric-v1"]
    by_id = {c["id"]: c for c in assistants}
    assert by_id["asst-gpt-6-luna-v1"]["available"] is True and by_id["asst-gpt-6-luna-v1"]["vendor"] == "openai"
    assert by_id["asst-claude-haiku-5-5-v1"]["available"] is False
    assert "ANTHROPIC_API_KEY" in by_id["asst-claude-haiku-5-5-v1"]["unavailable_reason"]
    assert reg.first_available("assistant") == "asst-gpt-6-luna-v1"
    assert [c["id"] for c in reg.list("subject")][:3] == ["subj-gpt-6-luna-v1", "subj-claude-haiku-5-5-v1", "subj-gemini-3.5-flash-lite-v1"]


def test_build_chat_model_dispatches_on_vendor():
    from app.agents.llm import build_chat_model

    s = Settings(provider="cloud", openai_key="o", anthropic_key="a", google_key="g", _env_file=None)
    assert type(build_chat_model("gpt-6-luna", "low", settings=s)).__name__ == "ChatOpenAI"
    assert type(build_chat_model("gemini-3.5-flash-lite", "low", settings=s)).__name__ == "ChatGoogleGenerativeAI"
    haiku = build_chat_model("claude-haiku-5-5", "low", settings=s)
    assert type(haiku).__name__ == "ChatAnthropic" and not haiku.betas  # no server-side fallback on Haiku 5.5
    with pytest.raises(ValueError):
        build_chat_model("llama3.1:8b", settings=s)
