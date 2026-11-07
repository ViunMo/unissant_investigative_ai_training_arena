"""Persistent response cache for every model call.

LangChain keys its cache on the exact rendered prompt plus the model's parameters (model id, effort, bound tools),
so a replayed transcript, a repeated bake-off or a re-run of the same scripted interview is answered from disk
instead of the vendor API. Cache hits report zero tokens and zero cost so the leaderboard's cost column stays
honest about what was actually bought.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Sequence

from langchain_core.caches import RETURN_VAL_TYPE, BaseCache
from langchain_core.load import dumps, loads
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, Generation

# Only our own serialised generations are ever read back; the explicit list keeps `loads` from loading anything else.
ALLOWED = [ChatGeneration, ChatGenerationChunk, Generation, AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage]


class SQLiteResponseCache(BaseCache):
    """Thread-safe SQLite cache of chat generations keyed by sha256(prompt + llm params)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, llm TEXT, created REAL, payload TEXT)")
        self._conn.commit()
        self.hits = 0
        self.misses = 0

    VOLATILE = {"id", "usage_metadata", "response_metadata"}

    @classmethod
    def _normalise(cls, prompt: str) -> str:
        """LangChain hands us the serialised message list. Message ids, token usage and vendor response metadata
        (including our own cache-hit marker) change between otherwise identical conversations, so they are dropped
        from the key; the content, roles, tool calls and tool results are what the model actually sees."""
        try:
            data = json.loads(prompt)
        except ValueError:
            return prompt

        def strip(node):
            if isinstance(node, dict):
                return {k: strip(v) for k, v in node.items() if k not in cls.VOLATILE}
            if isinstance(node, list):
                return [strip(v) for v in node]
            return node

        return json.dumps(strip(data), sort_keys=True, separators=(",", ":"))

    @classmethod
    def _key(cls, prompt: str, llm_string: str) -> str:
        return hashlib.sha256((llm_string + chr(0) + cls._normalise(prompt)).encode()).hexdigest()

    def lookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM responses WHERE key = ?", (self._key(prompt, llm_string),)).fetchone()
            if row is None:
                self.misses += 1
                return None
            self.hits += 1
        try:
            generations = loads(row[0], allowed_objects=ALLOWED)
        except Exception:  # unreadable entry (e.g. written by an older library version): treat as a miss
            return None
        for g in generations:
            msg = getattr(g, "message", None)
            if msg is not None:
                msg.usage_metadata = None  # nothing was bought for this answer
                msg.response_metadata = {**(msg.response_metadata or {}), "arena_cache": "hit"}
        return generations

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        try:
            payload = dumps(copy.deepcopy(list(return_val)))
        except Exception:
            return  # not serialisable: skip caching rather than fail the call
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO responses (key, llm, created, payload) VALUES (?, ?, ?, ?)",
                               (self._key(prompt, llm_string), llm_string[:200], time.time(), payload))
            self._conn.commit()

    def clear(self, **kwargs: Any) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM responses")
            self._conn.commit()

    def entries(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0])

    def stats(self) -> dict:
        return {"path": str(self.path), "entries": self.entries(), "hits": self.hits, "misses": self.misses}

    async def alookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        return self.lookup(prompt, llm_string)

    async def aupdate(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        self.update(prompt, llm_string, return_val)

    async def aclear(self, **kwargs: Any) -> None:
        self.clear(**kwargs)


def install_cache(path: Path | str) -> SQLiteResponseCache:
    """Make the cache the process-wide LangChain cache and return it (so health can report its stats)."""
    from langchain_core.globals import set_llm_cache

    cache = SQLiteResponseCache(path)
    set_llm_cache(cache)
    return cache


__all__: Sequence[str] = ("SQLiteResponseCache", "install_cache")
