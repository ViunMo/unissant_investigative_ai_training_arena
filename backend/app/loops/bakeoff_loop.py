"""L3: the bake-off tournament loop.

1. Freeze candidates. 2. Generate frozen transcripts per (case, subject, repeat) with the fixed
harness. 3. Replay track: every assistant assesses the same transcripts. 4. Interactive track:
cross-pair every assistant with every subject under equal budgets, randomised order.
5. Commit findings before exposing labels, then score blind and build separate leaderboards."""
from __future__ import annotations

import random
import traceback
from typing import Callable

from app.loops.interview_loop import InterviewLoop
from app.schemas import BakeoffRun, Role, Session, TrialResult, now_iso
from app.scoring.scoring import aggregate_assistants, aggregate_subjects, trial_from_session

ProgressFn = Callable[[BakeoffRun], None]


class BakeoffLoop:
    def __init__(self, loop: InterviewLoop) -> None:
        self.loop = loop
        self.engine = loop.engine

    def plan(self, run: BakeoffRun) -> list[str]:
        req = run.request
        cases = req.case_ids or self.engine.case_ids("hidden")
        for c in cases:
            self.engine.public(c)
        return cases

    def run(self, run: BakeoffRun, on_progress: ProgressFn | None = None) -> BakeoffRun:
        req = run.request
        rng = random.Random(req.seed)
        try:
            cases = self.plan(run)
            n_frozen = len(cases) * len(req.subject_ids) * req.repeats
            total = 0
            if "replay" in req.tracks:
                total += n_frozen * len(req.assistant_ids)
            if "interactive" in req.tracks:
                total += n_frozen * len(req.assistant_ids)
            run.total, run.progress, run.status = total, 0, "running"
            self._emit(run, on_progress)

            results: list[TrialResult] = []
            frozen: list[tuple[Session, str, int]] = []
            if "replay" in req.tracks:
                jobs = [(c, s, r) for c in cases for s in req.subject_ids for r in range(1, req.repeats + 1)]
                rng.shuffle(jobs)
                for case_id, subject_id, repeat in jobs:
                    scenario = self.engine.lock(case_id)
                    frozen.append((self.loop.run_scripted(scenario, req.assistant_ids[0], subject_id, req.max_turns, relay_assistant=False, coach=False), case_id, repeat))
                run.frozen_transcripts = len(frozen)
                replay_jobs = [(f, a) for f in frozen for a in req.assistant_ids]
                rng.shuffle(replay_jobs)
                for (transcript, case_id, repeat), assistant_id in replay_jobs:
                    scenario = self.engine.lock(case_id)
                    session = self.loop.replay(transcript, scenario, assistant_id)
                    results.append(trial_from_session(session, scenario, "replay", repeat))
                    run.progress += 1
                    self._emit(run, on_progress)

            if "interactive" in req.tracks:
                jobs = [(c, a, s, r) for c in cases for a in req.assistant_ids for s in req.subject_ids for r in range(1, req.repeats + 1)]
                rng.shuffle(jobs)
                for case_id, assistant_id, subject_id, repeat in jobs:
                    scenario = self.engine.lock(case_id)
                    session = self.loop.run_scripted(scenario, assistant_id, subject_id, req.max_turns, relay_assistant=True)
                    results.append(trial_from_session(session, scenario, "interactive", repeat))
                    run.progress += 1
                    self._emit(run, on_progress)

            run.results = results
            run.assistant_leaderboard = aggregate_assistants(results, seed=req.seed)
            run.subject_leaderboard = aggregate_subjects(results)
            run.role_prevalence = {
                Role.truthful.value: sum(1 for r in results if r.role == Role.truthful),
                Role.deceptive.value: sum(1 for r in results if r.role == Role.deceptive),
            }
            run.status, run.completed_at = "completed", now_iso()
        except Exception as exc:  # the run record must always end in a terminal state
            run.status = "failed"
            run.error = f"{exc}\n{traceback.format_exc()[-1500:]}"
        self._emit(run, on_progress)
        return run

    @staticmethod
    def _emit(run: BakeoffRun, fn: ProgressFn | None) -> None:
        if fn:
            fn(run)
