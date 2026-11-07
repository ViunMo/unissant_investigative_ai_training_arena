"""L3: the bake-off tournament loop.

1. Freeze candidates. 2. Generate frozen transcripts per (case, subject, repeat) with the fixed
harness. 3. Replay track: every assistant assesses the same transcripts. 4. Interactive track:
cross-pair every assistant with every subject under equal budgets, randomised order.
5. Commit findings before exposing labels, then score blind and build separate leaderboards.

Trials are independent, so each phase runs them on a small thread pool (`workers`); the per-vendor
rate limiters in `app.agents.llm` keep the combined request rate under each vendor's quota and the
response cache answers repeated calls from disk. Every model step is reported through
`BakeoffRun.events` / `BakeoffRun.active` so the UI can show what each model is being handed and
what it returns while the run is in progress. `request_stop` ends a run at its next model step."""
from __future__ import annotations

import random
import threading
import time
import traceback
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Callable

from app.loops.interview_loop import InterviewLoop
from app.schemas import BakeoffEvent, BakeoffRun, Role, Session, TrialResult, now_iso
from app.scoring.scoring import aggregate_assistants, aggregate_subjects, trial_from_session

ProgressFn = Callable[[BakeoffRun], None]
MAX_EVENTS = 240
MAX_TEXT = 4000
STAGES = {"subject_asked": "subject answering", "subject_answered": "subject answered",
          "assistant_input": "assistant assessing", "assistant_coached": "assistant coached",
          "assistant_final": "finding committed", "evidence_released": "evidence released"}


class BakeoffCancelled(RuntimeError):
    """Raised inside a trial when the user has asked for the run to stop."""


class BakeoffLoop:
    def __init__(self, loop: InterviewLoop, workers: int = 4) -> None:
        self.loop = loop
        self.engine = loop.engine
        self.workers = max(1, int(workers))
        self._stops: dict[str, threading.Event] = {}
        self._stops_lock = threading.Lock()

    def plan(self, run: BakeoffRun) -> list[str]:
        req = run.request
        cases = req.case_ids or self.engine.case_ids("hidden")
        for c in cases:
            self.engine.public(c)
        return cases

    def _stop_event(self, run_id: str) -> threading.Event:
        with self._stops_lock:
            return self._stops.setdefault(run_id, threading.Event())

    def request_stop(self, run_id: str) -> None:
        """Stop a queued or running bake-off: trials end at their next model step and the run is marked cancelled."""
        self._stop_event(run_id).set()

    def run(self, run: BakeoffRun, on_progress: ProgressFn | None = None) -> BakeoffRun:
        req = run.request
        rng = random.Random(req.seed)
        lock = threading.RLock()  # every mutation of `run` and every snapshot handed to on_progress happens under it
        stop = self._stop_event(run.id)
        run.workers = self.workers

        def check() -> None:
            if stop.is_set():
                raise BakeoffCancelled("stopped by the user")

        def emit() -> None:
            with lock:
                if on_progress:
                    on_progress(run)

        def event(cur: dict | None, kind: str, **fields) -> None:
            with lock:
                self._event(run, cur, kind, **fields)
                if cur is not None:
                    run.current = cur

        def phase(name: str) -> None:
            check()
            with lock:
                run.phase, run.current, run.active = name, None, []
            event(None, "phase", text=name)
            emit()

        def begin(track: str, case_id: str, assistant_id: str, subject_id: str, repeat: int) -> dict:
            check()
            cur = {"track": track, "case_id": case_id, "assistant_id": assistant_id, "subject_id": subject_id,
                   "repeat": repeat, "turn": 0, "max_turns": req.max_turns, "stage": "starting", "started_at": now_iso(),
                   "t0": time.perf_counter()}
            with lock:
                run.active.append(cur)
            event(cur, "trial_started", text=f"{track} · {case_id} · repeat {repeat}")
            emit()
            return cur

        def observer(cur: dict):
            def observe(kind: str, fields: dict) -> None:
                check()
                with lock:
                    if fields.get("turn"):
                        cur["turn"] = fields["turn"]
                    cur["stage"] = STAGES.get(kind, kind)
                event(cur, kind, **fields)
                emit()
            return observe

        def finish(cur: dict, text: str, scored: bool) -> None:
            with lock:
                if scored:
                    run.progress += 1
                run.active = [a for a in run.active if a is not cur]
            event(cur, "trial_done", text=text)
            with lock:
                run.current = run.active[-1] if run.active else None
            emit()

        def run_all(jobs: list, fn: Callable) -> list:
            """Run `fn(job)` for every job on the pool; the first failure cancels what has not started and is re-raised."""
            if not jobs:
                return []
            with ThreadPoolExecutor(max_workers=min(self.workers, len(jobs)), thread_name_prefix="bakeoff") as pool:
                futures = [pool.submit(fn, job) for job in jobs]
                done, _ = wait(futures, return_when=FIRST_EXCEPTION)
                failed = next((f for f in done if f.exception()), None)
                if failed:
                    for f in futures:
                        f.cancel()
                    raise failed.exception()  # type: ignore[misc]
                return [f.result() for f in futures]

        try:
            phase("planning")
            cases = self.plan(run)
            for cid in req.assistant_ids:  # build runtimes once, before trials fan out across threads
                self.loop.registry.assistant(cid)
            for cid in req.subject_ids:
                self.loop.registry.subject(cid)
            n_frozen = len(cases) * len(req.subject_ids) * req.repeats
            total = 0
            if "replay" in req.tracks:
                total += n_frozen * len(req.assistant_ids)
            if "interactive" in req.tracks:
                total += n_frozen * len(req.assistant_ids)
            with lock:
                run.total, run.progress, run.status = total, 0, "running"
            emit()

            results: list[TrialResult] = []
            if "replay" in req.tracks:
                phase("freezing transcripts")
                with lock:
                    run.frozen_total = n_frozen
                jobs = [(c, s, r) for c in cases for s in req.subject_ids for r in range(1, req.repeats + 1)]
                rng.shuffle(jobs)

                def freeze(job: tuple[str, str, int]) -> tuple[Session, str, int]:
                    case_id, subject_id, repeat = job
                    scenario = self.engine.lock(case_id)
                    cur = begin("freeze", case_id, "", subject_id, repeat)
                    transcript = self.loop.run_scripted(scenario, req.assistant_ids[0], subject_id, req.max_turns,
                                                        relay_assistant=False, coach=False, observe=observer(cur))
                    with lock:
                        run.frozen_transcripts += 1
                        n = run.frozen_transcripts
                    finish(cur, f"frozen transcript {n}/{n_frozen} ready", scored=False)
                    return transcript, case_id, repeat

                frozen = run_all(jobs, freeze)
                frozen.sort(key=lambda f: (f[1], f[0].subject_id, f[2]))  # deterministic order for the seeded shuffle below
                phase("replay track")
                replay_jobs = [(f, a) for f in frozen for a in req.assistant_ids]
                rng.shuffle(replay_jobs)

                def replay(job) -> TrialResult:
                    (transcript, case_id, repeat), assistant_id = job
                    scenario = self.engine.lock(case_id)
                    cur = begin("replay", case_id, assistant_id, transcript.subject_id, repeat)
                    session = self.loop.replay(transcript, scenario, assistant_id, observe=observer(cur))
                    result = trial_from_session(session, scenario, "replay", repeat)
                    finish(cur, self._done_text(session, result, cur["t0"]), scored=True)
                    return result

                results += run_all(replay_jobs, replay)

            if "interactive" in req.tracks:
                phase("interactive track")
                jobs = [(c, a, s, r) for c in cases for a in req.assistant_ids for s in req.subject_ids for r in range(1, req.repeats + 1)]
                rng.shuffle(jobs)

                def interactive(job: tuple[str, str, str, int]) -> TrialResult:
                    case_id, assistant_id, subject_id, repeat = job
                    scenario = self.engine.lock(case_id)
                    cur = begin("interactive", case_id, assistant_id, subject_id, repeat)
                    session = self.loop.run_scripted(scenario, assistant_id, subject_id, req.max_turns, relay_assistant=True, observe=observer(cur))
                    result = trial_from_session(session, scenario, "interactive", repeat)
                    finish(cur, self._done_text(session, result, cur["t0"]), scored=True)
                    return result

                results += run_all(jobs, interactive)

            phase("scoring")
            # completion order depends on thread timing; sort so the seeded bootstrap is reproducible
            results.sort(key=lambda r: tuple(str(getattr(r, k, "")) for k in ("track", "case_id", "assistant_id", "subject_id", "repeat")))
            with lock:
                run.results = results
                run.assistant_leaderboard = aggregate_assistants(results, seed=req.seed)
                run.subject_leaderboard = aggregate_subjects(results)
                run.role_prevalence = {
                    Role.truthful.value: sum(1 for r in results if r.role == Role.truthful),
                    Role.deceptive.value: sum(1 for r in results if r.role == Role.deceptive),
                }
                run.status, run.completed_at, run.phase, run.current, run.active = "completed", now_iso(), "completed", None, []
        except BakeoffCancelled:
            with lock:
                run.status, run.phase, run.active, run.current, run.completed_at = "cancelled", "cancelled", [], None, now_iso()
            event(None, "phase", text=f"stopped by the user after {run.progress} of {run.total} trials")
        except Exception as exc:  # the run record must always end in a terminal state
            with lock:
                run.status, run.phase, run.active = "failed", "failed", []
                run.error = f"{exc}\n{traceback.format_exc()[-1500:]}"
            event(None, "phase", text=f"failed: {str(exc)[:300]}")
        finally:
            with self._stops_lock:
                self._stops.pop(run.id, None)
        emit()
        return run

    @staticmethod
    def _done_text(session: Session, result: TrialResult, t0: float) -> str:
        return (f"locked {result.finding.value} ({result.confidence:.2f}) · truth {result.role.value} · "
                f"{'correct' if result.correct else 'incorrect'} · {session.max_turns} exchanges in {time.perf_counter() - t0:.0f}s")

    @staticmethod
    def _event(run: BakeoffRun, cur: dict | None, kind: str, **fields) -> None:
        cur = cur or {}
        for key in ("model_input", "model_output"):
            if fields.get(key) and len(fields[key]) > MAX_TEXT:
                fields[key] = fields[key][:MAX_TEXT] + f"\n… [{len(fields[key]) - MAX_TEXT} more characters]"
        run.events.append(BakeoffEvent(kind=kind, track=cur.get("track", ""), case_id=cur.get("case_id", ""),
                                       assistant_id=cur.get("assistant_id", ""), subject_id=cur.get("subject_id", ""), **fields))
        if len(run.events) > MAX_EVENTS:
            del run.events[: len(run.events) - MAX_EVENTS]
