"""Response cache and throughput controls."""
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration

from app.agents.cache import SQLiteResponseCache
from app.agents.llm import build_chat_model, rate_limiter_for
from app.config import Settings


def test_cache_round_trips_generations_and_zeroes_usage_on_hit(tmp_path):
    cache = SQLiteResponseCache(tmp_path / "c.sqlite")
    assert cache.lookup("prompt", "llm") is None
    msg = AIMessage(content='{"ok": true}', usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    cache.update("prompt", "llm", [ChatGeneration(message=msg)])
    hit = cache.lookup("prompt", "llm")
    assert hit and hit[0].message.content == '{"ok": true}'
    assert hit[0].message.usage_metadata is None and hit[0].message.response_metadata["arena_cache"] == "hit"
    assert cache.lookup("prompt", "other-params") is None  # same prompt, different model settings: miss
    assert cache.stats()["entries"] == 1 and cache.stats()["hits"] == 1 and cache.stats()["misses"] == 2
    reopened = SQLiteResponseCache(tmp_path / "c.sqlite")  # persists across processes
    assert reopened.lookup("prompt", "llm")[0].message.content == '{"ok": true}'


def test_rate_limiter_is_shared_per_vendor_and_optional():
    assert rate_limiter_for("openai", 0) is None
    a, b = rate_limiter_for("google", 14), rate_limiter_for("google", 14)
    assert a is b
    s = Settings(provider="cloud", google_key="g", openai_key="o", google_rpm=14, openai_rpm=0, _env_file=None)
    assert build_chat_model("gemini-3.5-flash-lite", "low", settings=s).rate_limiter is a
    assert build_chat_model("gpt-6-luna", "low", settings=s).rate_limiter is None


def test_cache_key_ignores_message_ids_usage_and_response_metadata(tmp_path):
    from langchain_core.load import dumps
    from langchain_core.messages import HumanMessage

    cache = SQLiteResponseCache(tmp_path / "k.sqlite")
    first = dumps([HumanMessage(content="hi", id="m1"), AIMessage(content="x", id="a1", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, response_metadata={"model": "m"})])
    second = dumps([HumanMessage(content="hi", id="m2"), AIMessage(content="x", id="a2", response_metadata={"arena_cache": "hit"})])
    changed = dumps([HumanMessage(content="hi", id="m2"), AIMessage(content="y", id="a2")])
    cache.update(first, "llm", [ChatGeneration(message=AIMessage(content="reply"))])
    assert cache.lookup(second, "llm")[0].message.content == "reply"
    assert cache.lookup(changed, "llm") is None
