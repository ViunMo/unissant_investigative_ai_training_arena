"""In-memory store with JSON snapshots on disk."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from app.schemas import BakeoffRun, Session


class Store:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.sessions: dict[str, Session] = {}
        self.bakeoffs: dict[str, BakeoffRun] = {}
        self._lock = threading.Lock()
        self.data_dir = data_dir
        if data_dir:
            data_dir.mkdir(parents=True, exist_ok=True)
            self._load()

    def _load(self) -> None:
        assert self.data_dir
        for f in (self.data_dir / "sessions").glob("*.json") if (self.data_dir / "sessions").exists() else []:
            try:
                s = Session.model_validate_json(f.read_text())
                self.sessions[s.id] = s
            except Exception:
                continue
        for f in (self.data_dir / "bakeoffs").glob("*.json") if (self.data_dir / "bakeoffs").exists() else []:
            try:
                b = BakeoffRun.model_validate_json(f.read_text())
                if b.status in ("queued", "running"):
                    b.status, b.error = "failed", "interrupted by restart"
                self.bakeoffs[b.id] = b
            except Exception:
                continue

    def _write(self, sub: str, obj_id: str, payload: str) -> None:
        if not self.data_dir:
            return
        d = self.data_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{obj_id}.json").write_text(payload)

    def save_session(self, s: Session) -> None:
        with self._lock:
            self.sessions[s.id] = s
            self._write("sessions", s.id, s.model_dump_json())

    def session(self, sid: str) -> Session:
        if sid not in self.sessions:
            raise KeyError(sid)
        return self.sessions[sid]

    def sessions_for(self, investigator: str) -> list[Session]:
        return [s for s in self.sessions.values() if s.investigator == investigator]

    def save_bakeoff(self, b: BakeoffRun) -> None:
        with self._lock:
            self.bakeoffs[b.id] = b
            self._write("bakeoffs", b.id, b.model_dump_json())

    def delete_bakeoff(self, bid: str) -> None:
        with self._lock:
            self.bakeoffs.pop(bid, None)
            if self.data_dir:
                (self.data_dir / "bakeoffs" / f"{bid}.json").unlink(missing_ok=True)

    def clear_bakeoffs(self) -> int:
        """Delete every finished (completed, failed or cancelled) bake-off; running ones are kept."""
        finished = [b.id for b in self.bakeoffs.values() if b.status not in ("queued", "running")]
        for bid in finished:
            self.delete_bakeoff(bid)
        return len(finished)

    def bakeoff(self, bid: str) -> BakeoffRun:
        if bid not in self.bakeoffs:
            raise KeyError(bid)
        return self.bakeoffs[bid]
