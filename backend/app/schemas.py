"""Pydantic models shared by the scenario engine, agents, loops, scoring and API."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class Role(str, Enum):
    truthful = "truthful"
    deceptive = "deceptive"


class Finding(str, Enum):
    truthful = "truthful"
    deceptive = "deceptive"
    insufficient_evidence = "insufficient_evidence"


class Mode(str, Enum):
    practice = "practice"
    assessment = "assessment"


class FlagKind(str, Enum):
    non_responsive = "non_responsive"
    contradiction = "contradiction"
    explicit_uncertainty = "explicit_uncertainty"
    possible_evasion = "possible_evasion"


class Tactic(str, Enum):
    """Behaviour a simulated subject reports for each turn. Hidden from assistants."""

    truthful = "truthful"
    uncertain = "uncertain"
    omission = "omission"
    deflection = "deflection"
    minimisation = "minimisation"
    contradiction = "contradiction"


EVASIVE_TACTICS = {Tactic.omission, Tactic.deflection, Tactic.minimisation, Tactic.contradiction}


# ---------------------------------------------------------------------------
# Scenario packets
# ---------------------------------------------------------------------------
class EvidenceItem(BaseModel):
    id: str
    title: str
    content: str
    release_after_turn: int = 0  # 0 = available at interview start
    conflicts_with_keywords: list[str] = Field(default_factory=list)  # answer phrases this record contradicts


class TopicScript(BaseModel):
    """How a subject responds to one line of questioning. Private to the subject."""

    topic: str
    keywords: list[str]
    truthful_answer: str
    deceptive_answer: str | None = None
    deceptive_tactic: Tactic = Tactic.truthful
    sensitive: bool = False  # touches the assigned violation
    uncertain_truthful: bool = False  # truthful subject genuinely does not recall


class PublicCasePacket(BaseModel):
    case_id: str
    family_id: str
    title: str
    objective: str
    context: str
    known_timeline: list[str]
    initial_documents: list[EvidenceItem]
    interview_context: str
    difficulty: Literal["low", "medium", "high"]
    initial_question: str
    key_topics: list[str]
    topic_keywords: dict[str, list[str]]
    question_bank: dict[str, str]  # topic -> neutral question
    max_turns: int = 12


class PrivateSubjectPacket(BaseModel):
    role: Role
    persona_name: str
    persona_position: str
    communication_style: str
    known_facts: list[str]
    may_disclose: list[str]
    must_not_disclose: list[str]
    uncertainty_notes: list[str]
    objective: str
    permitted_behaviors: list[Tactic]
    topics: list[TopicScript]


class EvaluatorPacket(BaseModel):
    assigned_role: Role
    violation: str | None
    canonical_facts: list[str]
    material_contradictions: list[str]
    evidence_release: list[EvidenceItem]
    resolution_criteria: str
    isolation_canaries: list[str]  # private strings that must never reach an assistant


class Scenario(BaseModel):
    version: str
    split: Literal["development", "hidden"] = "hidden"
    public: PublicCasePacket
    private: PrivateSubjectPacket
    evaluator: EvaluatorPacket


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------
class CandidateSpec(BaseModel):
    id: str
    kind: Literal["assistant", "subject"]
    label: str
    version: str
    model: str | None = None
    prompt_version: str
    policy: dict[str, Any] = Field(default_factory=dict)
    runtime: Literal["deepagents", "mock"] = "mock"
    description: str = ""


# ---------------------------------------------------------------------------
# Interview artefacts
# ---------------------------------------------------------------------------
class Flag(BaseModel):
    turn_index: int
    kind: FlagKind
    evidence_quote: str
    issue: str  # missing fact or conflicting statement


class Coaching(BaseModel):
    flags: list[Flag] = Field(default_factory=list)
    question_quality: int = Field(ge=0, le=4, default=2)
    question_feedback: str = ""
    suggested_follow_up: str = ""
    interim_finding: Finding = Finding.insufficient_evidence
    confidence: float = Field(ge=0.0, le=1.0, default=0.3)
    rationale: str = ""
    rubric_iterations: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class SubjectReply(BaseModel):
    reply: str
    tactic: Tactic = Tactic.truthful
    facts_used: list[str] = Field(default_factory=list)
    compliant: bool = True
    compliance_note: str = ""
    latency_ms: int = 0


class FinalFinding(BaseModel):
    finding: Finding
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class Turn(BaseModel):
    index: int
    question: str
    answer: str
    tactic: Tactic = Tactic.truthful  # hidden until debrief
    compliant: bool = True  # hidden until debrief
    facts_used: list[str] = Field(default_factory=list)
    coaching: Coaching | None = None
    evidence_released: list[EvidenceItem] = Field(default_factory=list)
    timestamp: str = Field(default_factory=now_iso)


class TrainerRating(BaseModel):
    clarity_neutrality: int = Field(ge=0, le=4)
    response_relevance: int = Field(ge=0, le=4)
    evidence_based_follow_up: int = Field(ge=0, le=4)
    alternative_explanations: int = Field(ge=0, le=4)
    supported_closure: int = Field(ge=0, le=4)

    @property
    def total(self) -> int:
        s = (
            self.clarity_neutrality
            + self.response_relevance
            + self.evidence_based_follow_up
            + self.alternative_explanations
            + self.supported_closure
        )
        return s * 5


class Debrief(BaseModel):
    ground_truth_role: Role
    violation: str | None
    canonical_facts: list[str]
    material_contradictions: list[str]
    investigator_finding: Finding
    investigator_correct: bool
    assistant_finding: Finding | None
    assistant_correct: bool | None
    investigator_auto_score: int  # 0-100 proxy from per-turn question quality + closure
    questioning_dimensions: dict[str, int]
    topic_coverage: float
    evasion_precision: float | None
    evasion_recall: float | None
    unsupported_flags: int
    subject_fidelity: float
    coaching_mean_latency_ms: int
    coaching_cost_usd: float
    isolation_pass: bool
    tactic_by_turn: list[str]
    notes: list[str] = Field(default_factory=list)


class Session(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sess"))
    mode: Mode
    investigator: str
    case_id: str
    assistant_id: str
    subject_id: str
    max_turns: int
    status: Literal["active", "awaiting_finding", "locked"] = "active"
    turns: list[Turn] = Field(default_factory=list)
    released_evidence: list[EvidenceItem] = Field(default_factory=list)
    final_finding: FinalFinding | None = None
    assistant_final: FinalFinding | None = None
    trainer_rating: TrainerRating | None = None
    debrief: Debrief | None = None
    assistant_inputs: list[str] = Field(default_factory=list)  # audit log for isolation checks
    created_at: str = Field(default_factory=now_iso)
    locked_at: str | None = None


# ---------------------------------------------------------------------------
# Bake-off
# ---------------------------------------------------------------------------
class BakeoffRequest(BaseModel):
    assistant_ids: list[str]
    subject_ids: list[str]
    case_ids: list[str] | None = None  # default: all hidden-eval cases
    repeats: int = Field(ge=1, le=5, default=1)
    max_turns: int = Field(ge=2, le=20, default=8)
    tracks: list[Literal["replay", "interactive"]] = Field(default_factory=lambda: ["replay", "interactive"])
    seed: int = 7
    label: str = ""


class TrialResult(BaseModel):
    trial_id: str
    track: str
    case_id: str
    family_id: str
    role: Role
    assistant_id: str
    subject_id: str
    repeat: int
    finding: Finding
    confidence: float
    correct: bool
    turns: int
    evasion_tp: int
    evasion_fp: int
    evasion_fn: int
    unsupported_flags: int
    topic_coverage: float
    subject_fidelity: float
    subject_compliant_session: bool
    isolation_pass: bool
    mean_latency_ms: int
    cost_usd: float
    deceptive_undetected: bool


class AssistantScore(BaseModel):
    assistant_id: str
    trials: int
    deceptive_recall: float
    recall_ci95: tuple[float, float]
    false_positive_rate: float
    ppv: float | None
    unresolved_rate_truthful: float
    unresolved_rate_deceptive: float
    matrix: dict[str, dict[str, int]]
    evasion_precision: float | None
    evasion_recall: float | None
    questioning_quality: float
    unsupported_flag_rate: float
    isolation_pass: bool
    mean_latency_ms: int
    p95_latency_ms: int
    total_cost_usd: float
    eligible: bool
    ineligible_reasons: list[str]
    rank: int | None = None


class SubjectScore(BaseModel):
    subject_id: str
    truthful_runs: int
    deceptive_runs: int
    fidelity_truthful: float
    fidelity_deceptive: float
    invalid_sessions: int
    deceptive_success_rate: float  # undetected within budget while compliant
    truthful_recognised_rate: float
    misleading_clearance_rate: float
    unresolved_rate: float


class BakeoffEvent(BaseModel):
    """One step of a bake-off trial for the live feed. Hidden labels never appear until the trial is locked."""

    ts: str = Field(default_factory=now_iso)
    kind: str  # phase | trial_started | subject_answered | assistant_input | assistant_coached | evidence_released | assistant_final | trial_done
    track: str = ""
    case_id: str = ""
    assistant_id: str = ""
    subject_id: str = ""
    turn: int | None = None
    text: str = ""
    model_input: str | None = None  # the exact data handed to the model (truncated)
    model_output: str | None = None
    latency_ms: int | None = None


class BakeoffRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("bake"))
    request: BakeoffRequest
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    progress: int = 0
    total: int = 0
    phase: str = ""
    current: dict[str, Any] | None = None  # the most recently updated trial and stage (kept for older clients)
    active: list[dict[str, Any]] = Field(default_factory=list)  # every trial running right now (trials run concurrently)
    workers: int = 1
    events: list[BakeoffEvent] = Field(default_factory=list)  # oldest first, capped by the loop
    frozen_total: int = 0
    error: str | None = None
    results: list[TrialResult] = Field(default_factory=list)
    assistant_leaderboard: list[AssistantScore] = Field(default_factory=list)
    subject_leaderboard: list[SubjectScore] = Field(default_factory=list)
    role_prevalence: dict[str, int] = Field(default_factory=dict)
    frozen_transcripts: int = 0
    created_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None
