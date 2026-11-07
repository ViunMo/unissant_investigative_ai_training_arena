"""HTTP API. Role labels, tactics and scoring keys are only revealed after a finding is locked."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.agents.candidates import CandidateRegistry
from app.agents.llm import build_chat_model
from app.auth import AuthError, UserStore
from app.graph import GraphNotConfigured, GraphSync
from app.loops.bakeoff_loop import BakeoffLoop
from app.loops.interview_loop import InterviewLoop
from app.scenarios.authoring import brief_from_scenario, build_items, parse_document, template
from app.scenarios.drafting import draft_cases
from app.scenarios.engine import ScenarioEngine, investigator_view
from app.schemas import BakeoffRequest, BakeoffRun, FinalFinding, Mode, Session, TrainerRating, Turn
from app.scoring.scoring import investigator_progress
from app.store import Store

logger = logging.getLogger(__name__)


class Services:
    def __init__(self, engine: ScenarioEngine, registry: CandidateRegistry, store: Store, users: UserStore,
                 graph: GraphSync | None = None) -> None:
        self.engine = engine
        self.registry = registry
        self.store = store
        self.users = users
        self.graph = graph or GraphSync(None)
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


def require_trainer(user: dict | None = Depends(require_user)) -> dict | None:
    """Case authoring is for trainers: the seeded admin account and anyone given that role."""
    if user is not None and user.get("role") != "trainer":
        raise HTTPException(403, "only trainer accounts can add or remove cases")
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


class CaseUpload(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)  # the file text: JSON or YAML, briefs or full scenarios
    filename: str | None = None
    dry_run: bool = False  # validate and preview only
    replace: bool = False  # overwrite uploaded cases with the same case_id


class CaseDraftRequest(BaseModel):
    description: str = Field(min_length=20, max_length=20_000)
    roles: list[str] = Field(default_factory=lambda: ["truthful", "deceptive"])
    model: str | None = None  # defaults to the grader model (the first assistant model)


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
    return [{**investigator_view(p), "split": s.engine.lock(p.case_id).split, "source": s.engine.source(p.case_id)}
            for p in s.engine.list_public()]


# ---------------------------------------------------------------------------
# Bring your own cases (trainer only)
# ---------------------------------------------------------------------------
@router.get("/scenarios/template", dependencies=[Depends(require_trainer)])
def scenario_template(format: str = "yaml"):
    """A worked matched pair in the case-brief format, ready to edit."""
    fmt = "json" if format == "json" else "yaml"
    return PlainTextResponse(template(fmt), media_type="application/json" if fmt == "json" else "application/yaml",
                             headers={"Content-Disposition": f"attachment; filename=case-brief-template.{fmt}"})


def _preview(item) -> dict:
    sc = item.scenario
    return {"index": item.index, "case_id": item.case_id, "kind": item.kind, "errors": item.errors, "warnings": item.warnings,
            **({"title": sc.public.title, "family_id": sc.public.family_id, "role": sc.private.role.value, "split": sc.split,
                "difficulty": sc.public.difficulty, "topics": sc.public.key_topics, "persona": sc.private.persona_name,
                "initial_documents": len(sc.public.initial_documents), "evidence_release": len(sc.evaluator.evidence_release),
                "max_turns": sc.public.max_turns, "scenario": sc.model_dump()} if sc else {})}


@router.post("/scenarios/import", dependencies=[Depends(require_trainer)])
def import_scenarios(body: CaseUpload, request: Request):
    """Validate (and unless dry_run, register and persist) the cases in an uploaded JSON or YAML file.

    The whole upload is accepted or rejected together so a half-imported matched pair never ends up in a bake-off."""
    s = svc(request)
    try:
        items = build_items(parse_document(body.content, body.filename))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, f"could not read the file: {str(exc)[:300]}")
    for it in items:
        if it.case_id and not it.errors:
            try:
                src = s.engine.source(it.case_id)
            except KeyError:
                continue
            if src == "builtin":
                it.errors.append(f"{it.case_id} is a built-in case; choose another case_id")
            elif not body.replace:
                it.errors.append(f"{it.case_id} was uploaded before; tick replace to overwrite it")
            else:
                it.warnings.append(f"replaces the uploaded case {it.case_id}")
    ok = all(not it.errors for it in items)
    imported: list[str] = []
    if ok and not body.dry_run:
        for it in items:
            imported.append(s.engine.add(it.scenario, replace=body.replace))
    return {"ok": ok, "dry_run": body.dry_run, "imported": imported, "items": [_preview(it) for it in items],
            "cases": len(s.engine.case_ids())}


@router.post("/scenarios/draft", dependencies=[Depends(require_trainer)])
def draft_scenarios(body: CaseDraftRequest, request: Request):
    """Turn a plain-language incident description into editable case briefs with a hosted model."""
    s = svc(request)
    model = getattr(request.app.state, "draft_model", None)  # tests inject a fake model here
    if model is None:
        model_id = body.model or s.registry.settings.model_for("grader")
        if s.registry.provider == "mock" or not model_id:
            raise HTTPException(409, "drafting needs a hosted model: set ARENA_PROVIDER=cloud and a vendor key")
        missing = s.registry.settings.missing_credential(model_id)
        if missing:
            raise HTTPException(409, f"cannot draft with {model_id}: {missing}")
        try:
            model = build_chat_model(model_id, effort="medium", max_tokens=16000, settings=s.registry.settings)
        except Exception as exc:
            raise HTTPException(409, f"cannot build model {model_id}: {str(exc)[:200]}")
    try:
        return draft_cases(body.description, body.roles, model)
    except Exception as exc:
        raise model_call_failed(exc)


@router.get("/scenarios/{case_id}/export", dependencies=[Depends(require_trainer)])
def export_scenario(case_id: str, request: Request, format: str = "brief"):
    """The full case (role, private and evaluator packets included) as a brief or the raw scenario, for editing."""
    try:
        sc = svc(request).engine.lock(case_id)
    except KeyError:
        raise HTTPException(404, "unknown case")
    return brief_from_scenario(sc) if format == "brief" else sc.model_dump()


@router.delete("/scenarios/{case_id}", dependencies=[Depends(require_trainer)])
def delete_scenario(case_id: str, request: Request):
    """Remove an uploaded case. Refused while sessions or bake-offs still refer to it."""
    s = svc(request)
    try:
        src = s.engine.source(case_id)
    except KeyError:
        raise HTTPException(404, "unknown case")
    if src == "builtin":
        raise HTTPException(409, "built-in cases cannot be removed")
    used_by = [x.id for x in s.store.sessions.values() if x.case_id == case_id]
    used_by += [b.id for b in s.store.bakeoffs.values() if any(r.case_id == case_id for r in b.results) or (b.request.case_ids and case_id in b.request.case_ids)]
    if used_by:
        raise HTTPException(409, f"{case_id} is referenced by {len(used_by)} session(s) or bake-off(s); delete those first")
    s.engine.remove(case_id)
    return {"deleted": case_id, "cases": len(s.engine.case_ids())}


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
    if s.graph.enabled:  # mirror the locked session into Neo4j without holding up the debrief
        s.executor.submit(s.graph.sync_session, session, scenario)
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


# ---------------------------------------------------------------------------
# Neo4j evidence graph (optional)
# ---------------------------------------------------------------------------
def graph_or_503(s: Services) -> GraphSync:
    if not s.graph.enabled:
        raise HTTPException(503, "Neo4j is not configured: set ARENA_NEO4J_URI and ARENA_NEO4J_PASSWORD in backend/.env")
    return s.graph


@router.get("/graph/status")
def graph_status(request: Request):
    return svc(request).graph.status()


@router.get("/graph/insights")
def graph_insights(request: Request):
    g = graph_or_503(svc(request))
    try:
        return g.insights()
    except GraphNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Neo4j query failed: {type(exc).__name__}: {str(exc)[:300]}")


@router.get("/graph/sessions")
def graph_sessions(request: Request, investigator: str | None = None, limit: int = 60):
    g = graph_or_503(svc(request))
    try:
        return g.network(investigator or None, max(1, min(limit, 300)))
    except GraphNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Neo4j query failed: {type(exc).__name__}: {str(exc)[:300]}")


@router.post("/graph/rebuild")
def graph_rebuild(request: Request):
    """Write every locked session in the store to Neo4j (idempotent: MERGE throughout)."""
    s = svc(request)
    g = graph_or_503(s)
    n = g.sync_all(list(s.store.sessions.values()), s.engine.lock)
    if g.error:
        raise HTTPException(502, f"Neo4j sync failed: {g.error}")
    return {"synced": n, "status": g.status()}


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
