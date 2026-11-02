"""HTTP API. Role labels, tactics and scoring keys are only revealed after a finding is locked."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.candidates import CandidateRegistry
from app.loops.bakeoff_loop import BakeoffLoop
from app.loops.interview_loop import InterviewLoop
from app.scenarios.engine import ScenarioEngine, investigator_view
from app.schemas import BakeoffRequest, BakeoffRun, FinalFinding, Mode, Session, TrainerRating, Turn
from app.scoring.scoring import investigator_progress
from app.store import Store

router = APIRouter(prefix="/api")


class Services:
    def __init__(self, engine: ScenarioEngine, registry: CandidateRegistry, store: Store) -> None:
        self.engine = engine
        self.registry = registry
        self.store = store
        self.interviews = InterviewLoop(engine, registry)
        self.bakeoffs = BakeoffLoop(self.interviews)
        self.executor = ThreadPoolExecutor(max_workers=2)


def svc(request: Request) -> Services:
    return request.app.state.services


# ---------------------------------------------------------------------------
# Views that hide ground truth until lock
# ---------------------------------------------------------------------------
def turn_view(t: Turn, session: Session) -> dict:
    locked = session.status == "locked"
    show_coaching = session.mode == Mode.practice or locked
    return {
        "index": t.index,
        "question": t.question,
        "answer": t.answer,
        "coaching": t.coaching.model_dump() if (t.coaching and show_coaching) else None,
        "evidence_released": [e.model_dump(exclude={"conflicts_with_keywords"}) for e in t.evidence_released],
        "timestamp": t.timestamp,
        **({"tactic": t.tactic.value, "compliant": t.compliant} if locked else {}),
    }


def session_view(s: Session) -> dict:
    return {
        "id": s.id,
        "mode": s.mode.value,
        "investigator": s.investigator,
        "case_id": s.case_id,
        "assistant_id": s.assistant_id,
        "subject_id": s.subject_id,
        "max_turns": s.max_turns,
        "turns_remaining": max(0, s.max_turns - len(s.turns)),
        "status": s.status,
        "turns": [turn_view(t, s) for t in s.turns],
        "released_evidence": [e.model_dump(exclude={"conflicts_with_keywords"}) for e in s.released_evidence],
        "final_finding": s.final_finding.model_dump() if s.final_finding else None,
        "assistant_final": s.assistant_final.model_dump() if (s.assistant_final and s.status == "locked") else None,
        "trainer_rating": s.trainer_rating.model_dump() if s.trainer_rating else None,
        "debrief": s.debrief.model_dump() if s.debrief else None,
        "created_at": s.created_at,
        "locked_at": s.locked_at,
    }


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class StartSession(BaseModel):
    investigator: str = Field(min_length=1, max_length=80)
    mode: Mode = Mode.practice
    case_id: str | None = None
    assistant_id: str = "asst-evidence-v1"
    subject_id: str = "subj-llm-v1"
    max_turns: int | None = Field(default=None, ge=2, le=20)


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/health")
def health(request: Request):
    s = svc(request)
    st = s.registry.settings
    return {"status": "ok", "provider": s.registry.provider, "cases": len(s.engine.case_ids()),
            "assistant_model": st.model_for("assistant"), "subject_model": st.model_for("subject"),
            "base_url": st.openai_base_url if s.registry.provider == "openai_compatible" else None}


@router.get("/scenarios")
def scenarios(request: Request):
    s = svc(request)
    return [{**investigator_view(p), "split": s.engine.lock(p.case_id).split} for p in s.engine.list_public()]


@router.get("/scenarios/{case_id}")
def scenario(case_id: str, request: Request):
    try:
        return investigator_view(svc(request).engine.public(case_id))
    except KeyError:
        raise HTTPException(404, "unknown case")


@router.get("/candidates")
def candidates(request: Request, kind: str | None = None):
    return svc(request).registry.list(kind)


@router.post("/sessions")
def start_session(body: StartSession, request: Request):
    s = svc(request)
    case_id = body.case_id or s.engine.random_case()
    try:
        session, _ = s.interviews.start(body.mode, body.investigator, case_id, body.assistant_id, body.subject_id, body.max_turns)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    s.store.save_session(session)
    return session_view(session)


@router.get("/sessions")
def list_sessions(request: Request, investigator: str | None = None):
    s = svc(request)
    items = s.store.sessions_for(investigator) if investigator else list(s.store.sessions.values())
    items.sort(key=lambda x: x.created_at, reverse=True)
    return [{k: v for k, v in session_view(x).items() if k not in ("turns", "released_evidence")} for x in items]


@router.get("/sessions/{sid}")
def get_session(sid: str, request: Request):
    try:
        return session_view(svc(request).store.session(sid))
    except KeyError:
        raise HTTPException(404, "unknown session")


@router.post("/sessions/{sid}/ask")
def ask(sid: str, body: Ask, request: Request):
    s = svc(request)
    try:
        session = s.store.session(sid)
    except KeyError:
        raise HTTPException(404, "unknown session")
    scenario = s.engine.lock(session.case_id)
    try:
        res = s.interviews.step(session, scenario, body.question)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    s.store.save_session(session)
    return {"turn": turn_view(res.turn, session), "status": session.status,
            "turns_remaining": max(0, session.max_turns - len(session.turns)),
            "released_evidence": [e.model_dump(exclude={"conflicts_with_keywords"}) for e in session.released_evidence]}


@router.post("/sessions/{sid}/finding")
def commit_finding(sid: str, body: FinalFinding, request: Request):
    s = svc(request)
    try:
        session = s.store.session(sid)
    except KeyError:
        raise HTTPException(404, "unknown session")
    scenario = s.engine.lock(session.case_id)
    try:
        s.interviews.commit(session, scenario, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    s.store.save_session(session)
    return session_view(session)


@router.post("/sessions/{sid}/trainer-rating")
def trainer_rating(sid: str, body: TrainerRating, request: Request):
    s = svc(request)
    try:
        session = s.store.session(sid)
    except KeyError:
        raise HTTPException(404, "unknown session")
    if session.status != "locked":
        raise HTTPException(400, "trainer ratings are entered after the finding is locked")
    session.trainer_rating = body
    s.store.save_session(session)
    return session_view(session)


@router.get("/investigators/{name}/progress")
def progress(name: str, request: Request):
    return investigator_progress(svc(request).store.sessions_for(name))


@router.post("/bakeoffs", status_code=202)
def start_bakeoff(body: BakeoffRequest, request: Request):
    s = svc(request)
    for cid in body.assistant_ids + body.subject_ids:
        try:
            s.registry.spec(cid)
        except KeyError:
            raise HTTPException(404, f"unknown candidate {cid}")
    run = BakeoffRun(request=body)
    try:
        s.bakeoffs.plan(run)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    s.store.save_bakeoff(run)
    s.executor.submit(s.bakeoffs.run, run, s.store.save_bakeoff)
    return {"id": run.id, "status": run.status}


@router.get("/bakeoffs")
def list_bakeoffs(request: Request):
    runs = sorted(svc(request).store.bakeoffs.values(), key=lambda r: r.created_at, reverse=True)
    return [r.model_dump(exclude={"results"}) for r in runs]


@router.get("/bakeoffs/{bid}")
def get_bakeoff(bid: str, request: Request, include_results: bool = False):
    try:
        run = svc(request).store.bakeoff(bid)
    except KeyError:
        raise HTTPException(404, "unknown bake-off")
    return run.model_dump(exclude=set() if include_results else {"results"})
