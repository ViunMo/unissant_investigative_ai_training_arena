"""L2: the interview turn loop.

question -> simulated subject answers -> assistant assesses the exchange -> scripted evidence
release -> budget check -> ... -> finding committed and locked -> independent scoring.

The same `step` drives human practice sessions and the bake-off's fixed interviewer harness."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from app.agents.candidates import CandidateRegistry
from app.agents.context import AssistantContext, SubjectContext, TranscriptEntry, detect_topics, turns_to_entries
from app.scenarios.engine import ScenarioEngine
from app.schemas import Coaching, EvidenceItem, FinalFinding, Mode, Scenario, Session, Turn, now_iso
from app.scoring.scoring import debrief_session

# Live-feed hook: observe(kind, fields). Only data the assistant itself may see is ever passed.
Observe = Callable[[str, dict], None] | None


@dataclass
class StepResult:
    session: Session
    turn: Turn
    coaching_visible: bool


def build_assistant_context(scenario: Scenario, turns: list[Turn], evidence: list[EvidenceItem], policy: dict) -> AssistantContext:
    """Isolation boundary: only public packet, transcript and released evidence cross it."""
    return AssistantContext(
        public=scenario.public,
        transcript=turns_to_entries(turns),
        released_evidence=list(evidence),
        policy=policy,
    )


def harness_question(scenario: Scenario, turns: list[Turn], last_coaching: Coaching | None, relay_assistant: bool) -> str:
    """Fixed interviewer harness for bake-offs: a common opening question, then either the
    assistant's proposed follow-up (interactive track) or the public question bank in order
    (frozen transcripts for the replay track)."""
    public = scenario.public
    if not turns:
        return public.initial_question
    if relay_assistant and last_coaching and last_coaching.suggested_follow_up.strip():
        return last_coaching.suggested_follow_up.strip()
    covered: set[str] = set()
    for t in turns:
        covered.update(detect_topics(t.question, public.topic_keywords))
    for topic in public.key_topics:
        if topic not in covered:
            return public.question_bank[topic]
    return "Is there anything else about this that you think I should know?"


def coaching_summary(c: Coaching) -> str:
    if c.rationale.startswith("[assistant output invalid"):
        return "invalid model output after validation retries; conservative fallback used"
    return (f"{len(c.flags)} flag(s) · interim {c.interim_finding.value} ({c.confidence:.2f}) · question quality {c.question_quality}/4"
            + (f" · follow-up: {c.suggested_follow_up[:140]}" if c.suggested_follow_up else ""))


class InterviewLoop:
    def __init__(self, engine: ScenarioEngine, registry: CandidateRegistry) -> None:
        self.engine = engine
        self.registry = registry

    # ---- session lifecycle --------------------------------------------------
    def start(self, mode: Mode, investigator: str, case_id: str, assistant_id: str, subject_id: str, max_turns: int | None = None) -> tuple[Session, Scenario]:
        scenario = self.engine.lock(case_id)
        self.registry.spec(assistant_id)
        self.registry.spec(subject_id)
        session = Session(
            mode=mode,
            investigator=investigator,
            case_id=case_id,
            assistant_id=assistant_id,
            subject_id=subject_id,
            max_turns=max_turns or scenario.public.max_turns,
            released_evidence=self.engine.initial_evidence(scenario),
        )
        return session, scenario

    def _coach(self, session: Session, scenario: Scenario, turn: Turn, observe: Observe) -> None:
        spec = self.registry.spec(session.assistant_id)
        ctx = build_assistant_context(scenario, session.turns + [turn], session.released_evidence, spec.policy)
        if observe:
            observe("assistant_input", {"turn": turn.index, "text": f"assessing T{turn.index}", "model_input": ctx.turn_text()})
        turn.coaching = self.registry.assistant(session.assistant_id).coach(ctx)
        session.assistant_inputs.extend(ctx.audit)
        if observe:
            observe("assistant_coached", {"turn": turn.index, "text": coaching_summary(turn.coaching), "latency_ms": turn.coaching.latency_ms,
                                          "model_output": turn.coaching.model_dump_json(indent=1, exclude={"input_tokens", "output_tokens", "cost_usd"})})

    def step(self, session: Session, scenario: Scenario, question: str, coach: bool = True, observe: Observe = None) -> StepResult:
        if session.status != "active":
            raise ValueError(f"session is {session.status}; no more questions can be asked")
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        idx = len(session.turns) + 1
        subject = self.registry.subject(session.subject_id)
        if observe:
            observe("subject_asked", {"turn": idx, "text": question})
        t0 = time.perf_counter()
        reply = subject.answer(SubjectContext(
            public=scenario.public, private=scenario.private,
            transcript=turns_to_entries(session.turns), question=question, turn_index=idx,
        ))
        if observe:  # the reply only; tactic and compliance stay hidden until the trial is locked
            observe("subject_answered", {"turn": idx, "text": reply.reply, "latency_ms": int((time.perf_counter() - t0) * 1000)})
        turn = Turn(index=idx, question=question, answer=reply.reply, tactic=reply.tactic,
                    compliant=reply.compliant, facts_used=reply.facts_used)
        if coach:
            self._coach(session, scenario, turn, observe)
        newly = self.engine.evidence_for_turn(scenario, idx)
        session.released_evidence.extend(newly)
        turn.evidence_released = newly
        if newly and observe:
            observe("evidence_released", {"turn": idx, "text": "; ".join(f"{e.id} {e.title}" for e in newly)})
        session.turns.append(turn)
        if idx >= session.max_turns:
            session.status = "awaiting_finding"
        return StepResult(session=session, turn=turn, coaching_visible=(session.mode == Mode.practice))

    def assistant_commit(self, session: Session, scenario: Scenario, observe: Observe = None) -> FinalFinding:
        """The assistant locks its own finding from the full transcript and released records."""
        spec = self.registry.spec(session.assistant_id)
        ctx = build_assistant_context(scenario, session.turns, session.released_evidence, spec.policy)
        if observe:
            observe("assistant_input", {"text": "committing a final finding", "model_input": ctx.final_text()})
        t0 = time.perf_counter()
        session.assistant_final = self.registry.assistant(session.assistant_id).final_finding(ctx)
        session.assistant_inputs.extend(ctx.audit)
        if observe:
            f = session.assistant_final
            observe("assistant_final", {"text": f"finding {f.finding.value} ({f.confidence:.2f})", "latency_ms": int((time.perf_counter() - t0) * 1000),
                                        "model_output": f.model_dump_json(indent=1)})
        return session.assistant_final

    def commit(self, session: Session, scenario: Scenario, finding: FinalFinding) -> Session:
        if session.status == "locked":
            raise ValueError("finding already locked")
        if not session.turns:
            raise ValueError("ask at least one question before committing a finding")
        session.final_finding = finding
        self.assistant_commit(session, scenario)
        session.status = "locked"
        session.locked_at = now_iso()
        session.debrief = debrief_session(session, scenario)
        return session

    # ---- scripted interviews (used by the bake-off loop) ----------------------
    def run_scripted(self, scenario: Scenario, assistant_id: str, subject_id: str, max_turns: int, relay_assistant: bool,
                     coach: bool = True, observe: Observe = None) -> Session:
        session, _ = self.start(Mode.assessment, "harness", scenario.public.case_id, assistant_id, subject_id, max_turns)
        last: Coaching | None = None
        while session.status == "active":
            q = harness_question(scenario, session.turns, last, relay_assistant)
            res = self.step(session, scenario, q, coach=coach, observe=observe)
            last = res.turn.coaching
        if coach:
            session.final_finding = self.assistant_commit(session, scenario, observe)
            session.status = "locked"
            session.locked_at = now_iso()
        return session

    def replay(self, frozen: Session, scenario: Scenario, assistant_id: str, observe: Observe = None) -> Session:
        """Replay track: an assistant assesses a frozen transcript turn by turn, seeing exactly
        the evidence that had been released at each point, then commits a finding."""
        session, _ = self.start(Mode.assessment, "harness", scenario.public.case_id, assistant_id, frozen.subject_id, frozen.max_turns)
        for t in frozen.turns:
            turn = t.model_copy(update={"coaching": None})
            self._coach(session, scenario, turn, observe)
            session.released_evidence.extend(turn.evidence_released)
            if turn.evidence_released and observe:
                observe("evidence_released", {"turn": turn.index, "text": "; ".join(f"{e.id} {e.title}" for e in turn.evidence_released)})
            session.turns.append(turn)
        session.final_finding = self.assistant_commit(session, scenario, observe)
        session.status = "locked"
        session.locked_at = now_iso()
        return session
