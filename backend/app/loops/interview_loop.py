"""L2: the interview turn loop.

question -> simulated subject answers -> assistant assesses the exchange -> scripted evidence
release -> budget check -> ... -> finding committed and locked -> independent scoring.

The same `step` drives human practice sessions and the bake-off's fixed interviewer harness."""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.candidates import CandidateRegistry
from app.agents.context import AssistantContext, SubjectContext, TranscriptEntry, detect_topics, turns_to_entries
from app.scenarios.engine import ScenarioEngine
from app.schemas import Coaching, EvidenceItem, FinalFinding, Mode, Scenario, Session, Turn, now_iso
from app.scoring.scoring import debrief_session


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

    def step(self, session: Session, scenario: Scenario, question: str, coach: bool = True) -> StepResult:
        if session.status != "active":
            raise ValueError(f"session is {session.status}; no more questions can be asked")
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        idx = len(session.turns) + 1
        subject = self.registry.subject(session.subject_id)
        reply = subject.answer(SubjectContext(
            public=scenario.public, private=scenario.private,
            transcript=turns_to_entries(session.turns), question=question, turn_index=idx,
        ))
        turn = Turn(index=idx, question=question, answer=reply.reply, tactic=reply.tactic,
                    compliant=reply.compliant, facts_used=reply.facts_used)
        if coach:
            spec = self.registry.spec(session.assistant_id)
            ctx = build_assistant_context(scenario, session.turns + [turn], session.released_evidence, spec.policy)
            turn.coaching = self.registry.assistant(session.assistant_id).coach(ctx)
            session.assistant_inputs.extend(ctx.audit)
        newly = self.engine.evidence_for_turn(scenario, idx)
        session.released_evidence.extend(newly)
        turn.evidence_released = newly
        session.turns.append(turn)
        if idx >= session.max_turns:
            session.status = "awaiting_finding"
        return StepResult(session=session, turn=turn, coaching_visible=(session.mode == Mode.practice))

    def assistant_commit(self, session: Session, scenario: Scenario) -> FinalFinding:
        """The assistant locks its own finding from the full transcript and released records."""
        spec = self.registry.spec(session.assistant_id)
        ctx = build_assistant_context(scenario, session.turns, session.released_evidence, spec.policy)
        session.assistant_final = self.registry.assistant(session.assistant_id).final_finding(ctx)
        session.assistant_inputs.extend(ctx.audit)
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
    def run_scripted(self, scenario: Scenario, assistant_id: str, subject_id: str, max_turns: int, relay_assistant: bool, coach: bool = True) -> Session:
        session, _ = self.start(Mode.assessment, "harness", scenario.public.case_id, assistant_id, subject_id, max_turns)
        last: Coaching | None = None
        while session.status == "active":
            q = harness_question(scenario, session.turns, last, relay_assistant)
            res = self.step(session, scenario, q, coach=coach)
            last = res.turn.coaching
        if coach:
            session.final_finding = self.assistant_commit(session, scenario)
            session.status = "locked"
            session.locked_at = now_iso()
        return session

    def replay(self, frozen: Session, scenario: Scenario, assistant_id: str) -> Session:
        """Replay track: an assistant assesses a frozen transcript turn by turn, seeing exactly
        the evidence that had been released at each point, then commits a finding."""
        session, _ = self.start(Mode.assessment, "harness", scenario.public.case_id, assistant_id, frozen.subject_id, frozen.max_turns)
        spec = self.registry.spec(assistant_id)
        assistant = self.registry.assistant(assistant_id)
        for t in frozen.turns:
            turn = t.model_copy(update={"coaching": None})
            ctx = build_assistant_context(scenario, session.turns + [turn], session.released_evidence, spec.policy)
            turn.coaching = assistant.coach(ctx)
            session.assistant_inputs.extend(ctx.audit)
            session.released_evidence.extend(turn.evidence_released)
            session.turns.append(turn)
        session.final_finding = self.assistant_commit(session, scenario)
        session.status = "locked"
        session.locked_at = now_iso()
        return session
