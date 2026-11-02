"""Scenario engine: locks case facts per trial, releases evidence on a script, and keeps
role labels and scoring keys away from investigators and assistants."""
from __future__ import annotations

import copy
import random

from app.scenarios.library import ALL_SCENARIOS
from app.schemas import EvidenceItem, PublicCasePacket, Scenario


class ScenarioEngine:
    def __init__(self, scenarios: list[Scenario] | None = None) -> None:
        self._scenarios: dict[str, Scenario] = {s.public.case_id: s for s in (scenarios or ALL_SCENARIOS)}

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

    def random_case(self, rng: random.Random | None = None, split: str | None = None) -> str:
        rng = rng or random.Random()
        return rng.choice(self.case_ids(split))

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
