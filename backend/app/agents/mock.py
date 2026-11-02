"""Deterministic runtimes.

They make the whole arena runnable and testable without any model key, and they act as
fixed baselines in bake-offs. Two assistant policies are provided on purpose: an
evidence-first policy that respects the false-positive constraint, and an aggressive
policy that treats uncertainty as evasion and is expected to fail the 5% gate.
"""
from __future__ import annotations

import time

from app.agents.context import (
    AssistantContext,
    SubjectContext,
    detect_topics,
    is_accusatory,
    is_deflection,
    is_neutral_opener,
    is_non_answer,
    is_uncertain,
)
from app.schemas import (
    CandidateSpec,
    Coaching,
    FinalFinding,
    Finding,
    Flag,
    FlagKind,
    Role,
    SubjectReply,
    Tactic,
)


class MockSubject:
    def __init__(self, spec: CandidateSpec) -> None:
        self.spec = spec

    def answer(self, ctx: SubjectContext) -> SubjectReply:
        t0 = time.perf_counter()
        private = ctx.private
        topics = detect_topics(ctx.question, {s.topic: s.keywords for s in private.topics})
        script = next((s for s in private.topics if s.topic == topics[0]), None) if topics else None
        if script is None:
            reply = SubjectReply(reply="Sorry, could you be more specific about what you're asking?", tactic=Tactic.truthful)
        elif private.role == Role.deceptive and script.sensitive and script.deceptive_answer:
            reply = SubjectReply(reply=script.deceptive_answer, tactic=script.deceptive_tactic, facts_used=[script.topic])
        else:
            tactic = Tactic.uncertain if script.uncertain_truthful else Tactic.truthful
            reply = SubjectReply(reply=script.truthful_answer, tactic=tactic, facts_used=[script.topic])
        reply.compliant = reply.tactic in private.permitted_behaviors and not any(
            s.lower() in reply.reply.lower() for s in private.must_not_disclose if private.role == Role.deceptive
        )
        reply.latency_ms = int((time.perf_counter() - t0) * 1000)
        return reply


class MockAssistant:
    """Rule-based coach. policy['style'] is 'evidence_first' or 'aggressive'."""

    def __init__(self, spec: CandidateSpec) -> None:
        self.spec = spec
        self.style = spec.policy.get("style", "evidence_first")

    # ---- per-turn coaching -------------------------------------------------
    def coach(self, ctx: AssistantContext) -> Coaching:
        t0 = time.perf_counter()
        ctx.record(ctx.snapshot())
        latest = ctx.latest
        q_topics = detect_topics(latest.question, ctx.public.topic_keywords)
        flags = self._turn_flags(ctx) + self._contradictions(ctx)
        quality, feedback = self._question_quality(latest.question, q_topics, ctx)
        follow_up = self._follow_up(ctx, q_topics, flags)
        finding, confidence, rationale = self._interim(ctx, self._all_flags(ctx))
        c = Coaching(flags=flags, question_quality=quality, question_feedback=feedback, suggested_follow_up=follow_up,
                     interim_finding=finding, confidence=confidence, rationale=rationale)
        c.latency_ms = int((time.perf_counter() - t0) * 1000)
        return c

    def _turn_flags(self, ctx: AssistantContext) -> list[Flag]:
        """Flags that concern only the latest exchange."""
        latest = ctx.latest
        q_topics = detect_topics(latest.question, ctx.public.topic_keywords)
        flags: list[Flag] = []

        if is_deflection(latest.answer):
            flags.append(Flag(turn_index=latest.index, kind=FlagKind.possible_evasion, evidence_quote=latest.answer,
                              issue=f"Deflects instead of addressing {', '.join(q_topics) or 'the question'}."))
        elif is_uncertain(latest.answer):
            flags.append(Flag(turn_index=latest.index, kind=FlagKind.explicit_uncertainty, evidence_quote=latest.answer,
                              issue="Subject states uncertainty; request corroborating records rather than inferring evasion."))
        elif q_topics and is_non_answer(latest.answer):
            flags.append(Flag(turn_index=latest.index, kind=FlagKind.non_responsive, evidence_quote=latest.answer,
                              issue=f"Answer does not address {q_topics[0]}."))
        return flags

    def _contradictions(self, ctx: AssistantContext) -> list[Flag]:
        """Statements anywhere in the transcript that conflict with a released record."""
        flags: list[Flag] = []
        for ev in ctx.released_evidence:
            for entry in ctx.transcript:
                if any(k in entry.answer.lower() for k in ev.conflicts_with_keywords):
                    if not any(f.turn_index == entry.index for f in flags):
                        flags.append(Flag(turn_index=entry.index, kind=FlagKind.contradiction, evidence_quote=entry.answer,
                                          issue=f"Conflicts with {ev.id} ({ev.title}): {ev.content}"))
        return flags

    def final_finding(self, ctx: AssistantContext) -> FinalFinding:
        ctx.record(ctx.snapshot())
        all_flags = self._all_flags(ctx)
        finding, confidence, rationale = self._interim(ctx, all_flags)
        return FinalFinding(finding=finding, confidence=confidence, rationale=rationale)

    # ---- helpers -------------------------------------------------------------
    def _all_flags(self, ctx: AssistantContext) -> list[Flag]:
        """Per-turn flags for every turn so far plus contradictions against released records."""
        flags: list[Flag] = []
        for i in range(1, len(ctx.transcript) + 1):
            sub = AssistantContext(public=ctx.public, transcript=ctx.transcript[:i],
                                   released_evidence=ctx.released_evidence, policy=ctx.policy)
            flags.extend(self._turn_flags(sub))
        return flags + self._contradictions(ctx)

    def _question_quality(self, question: str, q_topics: list[str], ctx: AssistantContext) -> tuple[int, str]:
        if not question.strip():
            return 0, "Empty question."
        if is_accusatory(question):
            return 1, "Accusatory framing. Ask a neutral, open question about the facts instead."
        previously = set()
        for e in ctx.prior:
            previously.update(detect_topics(e.question, ctx.public.topic_keywords))
        if q_topics and not (set(q_topics) & previously) and is_neutral_opener(question):
            return 4, f"Neutral, open question that opens a new line ({q_topics[0]})."
        if q_topics:
            return 3, f"Relevant follow-up on {q_topics[0]}."
        return 2, "Generic question. Tie it to a specific fact, record or time."

    def _follow_up(self, ctx: AssistantContext, q_topics: list[str], flags: list[Flag]) -> str:
        bank = ctx.public.question_bank
        asked: dict[str, int] = {}
        for e in ctx.transcript:
            for t in detect_topics(e.question, ctx.public.topic_keywords)[:1]:
                asked[t] = asked.get(t, 0) + 1
        # Re-ask an evaded point once; after that move on and let the record speak.
        if flags and q_topics and flags[0].kind in (FlagKind.possible_evasion, FlagKind.non_responsive) and asked.get(q_topics[0], 0) < 2:
            return f"The {q_topics[0].replace('_', ' ')} point is still open. {bank.get(q_topics[0], '')}".strip()
        if any(f.kind == FlagKind.contradiction for f in flags):
            f = next(f for f in flags if f.kind == FlagKind.contradiction)
            return f"Earlier you said: '{f.evidence_quote[:80]}'. The record shows something different. Can you help me reconcile that?"
        covered = ctx.covered_topics()
        for topic in ctx.public.key_topics:
            if topic not in covered:
                return bank[topic]
        return "Is there anything else about that evening you think I should know?"

    def _interim(self, ctx: AssistantContext, flags: list[Flag]) -> tuple[Finding, float, str]:
        evasive = sum(1 for f in flags if f.kind in (FlagKind.possible_evasion, FlagKind.non_responsive))
        contradictions = sum(1 for f in flags if f.kind == FlagKind.contradiction)
        uncertain = sum(1 for f in flags if f.kind == FlagKind.explicit_uncertainty)
        coverage = ctx.coverage()
        if self.style == "aggressive":
            if evasive + uncertain + contradictions >= 2:
                return Finding.deceptive, 0.75, "Multiple evasive or uncertain answers."
            if coverage >= 0.6 and not flags:
                return Finding.truthful, 0.7, "Consistent answers so far."
            return Finding.insufficient_evidence, 0.4, "Need more coverage."
        # evidence_first
        if contradictions >= 1 and evasive >= 1:
            return Finding.deceptive, 0.85, "A record contradiction plus evasive answers on the same line of questioning."
        if evasive >= 3:
            return Finding.deceptive, 0.7, "Repeated deflection across lines of questioning; corroborate with records before closing."
        if coverage >= 0.8 and evasive == 0 and contradictions == 0:
            return Finding.truthful, 0.75, "Key lines of questioning covered with responsive answers; uncertainty is explicit, not evasive."
        return Finding.insufficient_evidence, 0.4, "Coverage or corroboration still incomplete."
