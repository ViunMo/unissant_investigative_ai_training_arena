"""Contexts handed to agents.

The AssistantContext is the isolation boundary: it is built only from the public packet,
the transcript and released evidence. Private and evaluator packets never enter it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas import EvidenceItem, PrivateSubjectPacket, PublicCasePacket, Turn

DEFLECTION_PATTERNS = [
    r"\bbusy\b", r"does it matter", r"not relevant", r"why does", r"move on", r"all the time",
    r"wouldn't read much", r"nothing worth", r"you know how", r"same as always", r"i'd have to check",
    r"have to check", r"don't memori", r"the number's the number", r"probably miscount",
]
UNCERTAINTY_PATTERNS = [
    r"don't remember", r"do not remember", r"don't recall", r"not sure", r"not certain", r"\bmaybe\b",
    r"\baround\b", r"i think", r"honestly, i don't know", r"i don't know", r"pretty sure",
]
NON_ANSWER_PATTERNS = [r"more specific", r"what do you mean", r"not sure what you're asking", r"what are you asking", r"^\s*(yes|no)\.?\s*$"]
ACCUSATORY_PATTERNS = [r"\blying\b", r"\badmit\b", r"\bsteal\b", r"\bstole\b", r"you did it", r"confess", r"\bliar\b", r"cover(ing)? up"]
NEUTRAL_OPENERS = [r"^\s*(what|when|who|where|which|how|can you|could you|walk me|tell me|describe|help me understand)"]


def _any(patterns: list[str], text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def detect_topics(text: str, topic_keywords: dict[str, list[str]]) -> list[str]:
    """Topics mentioned in `text`, strongest match first (longest matching keyword wins)."""
    t = text.lower()
    scored = []
    for topic, kws in topic_keywords.items():
        best = max((len(k) for k in kws if k in t), default=0)
        if best:
            scored.append((best, topic))
    scored.sort(key=lambda x: -x[0])
    return [topic for _, topic in scored]


def is_deflection(text: str) -> bool:
    return _any(DEFLECTION_PATTERNS, text)


def is_uncertain(text: str) -> bool:
    return _any(UNCERTAINTY_PATTERNS, text)


def is_non_answer(text: str) -> bool:
    return _any(NON_ANSWER_PATTERNS, text) or len(text.split()) < 3


def is_accusatory(text: str) -> bool:
    return _any(ACCUSATORY_PATTERNS, text)


def is_neutral_opener(text: str) -> bool:
    return _any(NEUTRAL_OPENERS, text)


@dataclass
class TranscriptEntry:
    index: int
    question: str
    answer: str


@dataclass
class AssistantContext:
    """Everything an investigative assistant may see. Nothing else."""

    public: PublicCasePacket
    transcript: list[TranscriptEntry]
    released_evidence: list[EvidenceItem]
    policy: dict[str, Any] = field(default_factory=dict)
    audit: list[str] = field(default_factory=list)

    @property
    def latest(self) -> TranscriptEntry:
        return self.transcript[-1]

    @property
    def prior(self) -> list[TranscriptEntry]:
        return self.transcript[:-1]

    def covered_topics(self) -> set[str]:
        covered: set[str] = set()
        for e in self.transcript:
            covered.update(detect_topics(e.question, self.public.topic_keywords))
        return covered

    def coverage(self) -> float:
        if not self.public.key_topics:
            return 0.0
        return len(self.covered_topics() & set(self.public.key_topics)) / len(self.public.key_topics)

    def transcript_text(self) -> str:
        lines = []
        for e in self.transcript:
            lines.append(f"[T{e.index}] INVESTIGATOR: {e.question}")
            lines.append(f"[T{e.index}] SUBJECT: {e.answer}")
        return "\n".join(lines)

    def evidence_text(self) -> str:
        if not self.released_evidence:
            return "(none released yet)"
        return "\n".join(f"- {e.id} {e.title}: {e.content}" for e in self.released_evidence)

    def case_text(self) -> str:
        p = self.public
        return (
            f"Case {p.case_id}: {p.title}\nObjective: {p.objective}\nContext: {p.context}\n"
            f"Known timeline:\n" + "\n".join(f"- {t}" for t in p.known_timeline)
            + f"\nInterview context: {p.interview_context}\nLines of questioning: {', '.join(p.key_topics)}"
        )

    def record(self, payload: str) -> None:
        self.audit.append(payload)

    def snapshot(self) -> str:
        return json.dumps(
            {
                "case": self.public.model_dump(),
                "transcript": [e.__dict__ for e in self.transcript],
                "evidence": [e.model_dump() for e in self.released_evidence],
            },
            default=str,
        )


@dataclass
class SubjectContext:
    public: PublicCasePacket
    private: PrivateSubjectPacket
    transcript: list[TranscriptEntry]  # prior turns
    question: str
    turn_index: int


def turns_to_entries(turns: list[Turn]) -> list[TranscriptEntry]:
    return [TranscriptEntry(index=t.index, question=t.question, answer=t.answer) for t in turns]
