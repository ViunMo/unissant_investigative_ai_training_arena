"""HTTP API. Role labels, tactics and scoring keys are only revealed after a finding is locked."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.candidates import CandidateRegistry
from app.auth import AuthError, UserStore
from app.loops.bakeoff_loop import BakeoffLoop
from app.loops.interview_loop import InterviewLoop
from app.scenarios.engine import ScenarioEngine, investigator_view
from app.schemas import BakeoffRequest, BakeoffRun, FinalFinding, Mode, Session, TrainerRating, Turn
from app.scoring.scoring import investigator_progress
from app.store import Store

logger = logging.getLogger(__name__)


class Services:
    def __init__(self, engine: ScenarioEngine, registry: CandidateRegistry, store: Store, users: UserStore) -> None:
        self.engine = engine
        self.registry = registry
        self.store = store
        self.users = users
        self.interviews = InterviewLoop(engine, registry)
        self.bakeoffs = BakeoffLoop(self.interviews, workers=registry.settings.bakeoff_workers)
        self.executor = ThreadPoolExecutor(max_workers=2)


def svc(request: Request) -> Services:
    return request.app.state.services


def require_user(request: Request) -> dict | None:
    """Bearer-token login for every route except /health and /auth/*."""
    s = svc(request)
    if not s.registry.settings.auth_required:
        return None
    header = request.headers.get("authorization", "")
    user = s.users.user_for_token(header[7:] if header.lower().startswith("bearer ") else None)
    if not user:
        raise HTTPException(401, "sign in to use the arena", headers={"WWW-Authenticate": "Bearer"})
    return user


public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


def require_available(s: Services, cid: str) -> None:
    """404 for an unknown candidate; 409 when its model cannot be called (missing vendor key, model not pulled)."""
    try:
        spec = s.registry.spec(cid)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    if s.registry.available(spec) is False:
        raise HTTPException(409, f"{cid} cannot run: {s.registry.unavailable_reason(spec)}")


def model_call_failed(exc: Exception) -> HTTPException:
    logger.exception("model call failed")
    return HTTPException(502, f"model call failed: {type(exc).__name__}: {str(exc)[:300]}")


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
    assistant_id: str | None = None  # default: first candidate whose model can be called
    subject_id: str | None = None
    max_turns: int | None = Field(default=None, ge=2, le=20)


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@public.get("/health")
def health(request: Request):
    s = svc(request)
    st = s.registry.settings
    return {"status": "ok", "provider": s.registry.provider, "provider_label": st.provider_label,
            "cases": len(s.engine.case_ids()), "auth_required": st.auth_required,
            "assistant_model": st.model_for("assistant"), "subject_model": st.model_for("subject"),
            "assistant_models": st.models_for("assistant"), "subject_models": st.models_for("subject"),
            "base_url": st.gateway_base_url if s.registry.provider == "openai_compatible" else None,
            "bakeoff_workers": st.bakeoff_workers, "rate_limits_rpm": {"openai": st.openai_rpm, "anthropic": st.anthropic_rpm, "google": st.google_rpm},
            "response_cache": request.app.state.llm_cache.stats() if getattr(request.app.state, "llm_cache", None) else None}


@public.post("/auth/login")
def login(body: Credentials, request: Request):
    s = svc(request)
    user = s.users.verify(body.username, body.password)
    if not user:
        raise HTTPException(401, "unknown username or wrong password")
    return {"token": s.users.issue_token(user["username"]), "user": user}


@public.post("/auth/register", status_code=201)
def register(body: Credentials, request: Request):
    s = svc(request)
    try:
        user = s.users.create(body.username, body.password)
    except AuthError as exc:
        raise HTTPException(409 if "taken" in str(exc) else 400, str(exc))
    return {"token": s.users.issue_token(user["username"]), "user": user}


@router.get("/auth/me")
def me(user: dict | None = Depends(require_user)):
    return user or {"username": "anonymous", "role": "investigator", "created_at": None}


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
    assistant_id = body.assistant_id or s.registry.first_available("assistant")
    subject_id = body.subject_id or s.registry.first_available("subject")
    require_available(s, assistant_id)
    require_available(s, subject_id)
    try:
        session, _ = s.interviews.start(body.mode, body.investigator, case_id, assistant_id, subject_id, body.max_turns)
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
    except Exception as exc:  # gateway/model failures surface as a readable 502 rather than a bare 500
        raise model_call_failed(exc)
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
    except Exception as exc:
        raise model_call_failed(exc)
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
        require_available(s, cid)
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
    return [r.model_dump(exclude={"results", "events"}) for r in runs]


@router.post("/bakeoffs/{bid}/stop")
def stop_bakeoff(bid: str, request: Request):
    s = svc(request)
    try:
        run = s.store.bakeoff(bid)
    except KeyError:
        raise HTTPException(404, "unknown bake-off")
    if run.status not in ("queued", "running"):
        raise HTTPException(400, f"bake-off is already {run.status}")
    s.bakeoffs.request_stop(bid)
    return {"id": bid, "status": "stopping"}


@router.delete("/bakeoffs")
def clear_bakeoffs(request: Request):
    """Remove every finished bake-off (completed, failed or cancelled); running ones are left alone."""
    return {"deleted": svc(request).store.clear_bakeoffs()}


@router.delete("/bakeoffs/{bid}")
def delete_bakeoff(bid: str, request: Request):
    s = svc(request)
    try:
        run = s.store.bakeoff(bid)
    except KeyError:
        raise HTTPException(404, "unknown bake-off")
    if run.status in ("queued", "running"):
        raise HTTPException(409, "stop the bake-off before deleting it")
    s.store.delete_bakeoff(bid)
    return {"deleted": 1}


@router.get("/bakeoffs/{bid}")
def get_bakeoff(bid: str, request: Request, include_results: bool = False):
    try:
        run = svc(request).store.bakeoff(bid)
    except KeyError:
        raise HTTPException(404, "unknown bake-off")
    return run.model_dump(exclude=set() if include_results else {"results"})
