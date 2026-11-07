"""Scenario engine: locks case facts per trial, releases evidence on a script, and keeps
role labels and scoring keys away from investigators and assistants.

Cases come from two places: the built-in synthetic library and uploaded cases, which are kept as one JSON file
each under ``<data_dir>/scenarios`` so they survive a restart."""
from __future__ import annotations

import copy
import logging
import random
import threading
from pathlib import Path

from app.scenarios.library import ALL_SCENARIOS
from app.schemas import EvidenceItem, PublicCasePacket, Scenario

logger = logging.getLogger(__name__)


class ScenarioEngine:
    def __init__(self, scenarios: list[Scenario] | None = None, store_dir: Path | None = None) -> None:
        self._scenarios: dict[str, Scenario] = {s.public.case_id: s for s in (scenarios or ALL_SCENARIOS)}
        self._sources: dict[str, str] = {cid: "builtin" for cid in self._scenarios}
        self._lock = threading.Lock()
        self.store_dir = store_dir
        if store_dir:
            store_dir.mkdir(parents=True, exist_ok=True)
            for f in sorted(store_dir.glob("*.json")):
                try:
                    s = Scenario.model_validate_json(f.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("skipping uploaded case %s: %s", f.name, exc)
                    continue
                self._scenarios[s.public.case_id] = s
                self._sources[s.public.case_id] = "uploaded"

    # ---- catalogue -------------------------------------------------------
    def list_public(self) -> list[PublicCasePacket]:
        return [s.public for s in self._scenarios.values()]

    def case_ids(self, split: str | None = None) -> list[str]:
        return [cid for cid, s in self._scenarios.items() if split is None or s.split == split]

    def families(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for cid, s in self._scenarios.items():
            out.setdefault(s.public.family_id, []).append(cid)
        return out

    def public(self, case_id: str) -> PublicCasePacket:
        return self._scenario(case_id).public

    def source(self, case_id: str) -> str:
        """'builtin' for library cases, 'uploaded' for cases brought in through the API."""
        self._scenario(case_id)
        return self._sources[case_id]

    def random_case(self, rng: random.Random | None = None, split: str | None = None) -> str:
        rng = rng or random.Random()
        return rng.choice(self.case_ids(split))

    # ---- uploaded cases --------------------------------------------------
    def add(self, scenario: Scenario, replace: bool = False) -> str:
        """Register an uploaded case. Built-in cases are never overwritten; uploaded ones only with replace=True."""
        cid = scenario.public.case_id
        with self._lock:
            if cid in self._scenarios:
                if self._sources[cid] == "builtin":
                    raise ValueError(f"{cid} is a built-in case; choose another case_id")
                if not replace:
                    raise ValueError(f"{cid} already exists; tick replace to overwrite it")
            self._scenarios[cid] = copy.deepcopy(scenario)
            self._sources[cid] = "uploaded"
            if self.store_dir:
                (self.store_dir / f"{cid}.json").write_text(scenario.model_dump_json(indent=1), encoding="utf-8")
        return cid

    def remove(self, case_id: str) -> None:
        with self._lock:
            if self._sources.get(case_id) != "uploaded":
                raise ValueError(f"{case_id} is not an uploaded case" if case_id in self._scenarios else f"unknown case {case_id}")
            self._scenarios.pop(case_id)
            self._sources.pop(case_id)
            if self.store_dir:
                (self.store_dir / f"{case_id}.json").unlink(missing_ok=True)

    # ---- locked trial view ----------------------------------------------
    def lock(self, case_id: str) -> Scenario:
        """Return a deep copy so that nothing a trial does can mutate the ground truth."""
        return copy.deepcopy(self._scenario(case_id))

    def initial_evidence(self, scenario: Scenario) -> list[EvidenceItem]:
        return [e for e in scenario.public.initial_documents if e.release_after_turn == 0]

    def evidence_for_turn(self, scenario: Scenario, turn_index: int) -> list[EvidenceItem]:
        """Scripted release: records whose release_after_turn equals the completed turn."""
        return [e for e in scenario.evaluator.evidence_release if e.release_after_turn == turn_index]

    def _scenario(self, case_id: str) -> Scenario:
        if case_id not in self._scenarios:
            raise KeyError(f"unknown case {case_id}")
        return self._scenarios[case_id]


def investigator_view(packet: PublicCasePacket) -> dict:
    """The public packet without the deterministic-baseline hints."""
    d = packet.model_dump()
    for doc in d["initial_documents"]:
        doc.pop("conflicts_with_keywords", None)
    return d
