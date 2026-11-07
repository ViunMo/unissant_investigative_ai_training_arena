from app.loops.bakeoff_loop import BakeoffLoop
from app.schemas import BakeoffRequest, BakeoffRun


def test_bakeoff_cross_pairs_candidates_and_applies_gates(loop):
    run = BakeoffRun(request=BakeoffRequest(assistant_ids=["asst-mock-evidence-v1", "asst-mock-aggressive-v1"],
                                            subject_ids=["subj-mock-v1"], repeats=1, max_turns=8))
    progress = []
    BakeoffLoop(loop).run(run, on_progress=lambda r: progress.append(r.progress))
    assert run.status == "completed", run.error
    assert run.total == 4 * 2 * 2 and run.progress == run.total  # 4 hidden cases x 2 assistants x 2 tracks
    assert run.frozen_transcripts == 4
    assert run.role_prevalence == {"truthful": 8, "deceptive": 8}
    by_id = {s.assistant_id: s for s in run.assistant_leaderboard}
    assert by_id["asst-mock-evidence-v1"].eligible
    assert by_id["asst-mock-evidence-v1"].false_positive_rate == 0.0
    assert by_id["asst-mock-evidence-v1"].deceptive_recall >= 0.75
    assert not by_id["asst-mock-aggressive-v1"].eligible
    assert all(s.isolation_pass for s in run.assistant_leaderboard)
    assert run.subject_leaderboard[0].subject_id == "subj-mock-v1"
    assert progress[-1] == run.total


def test_bakeoff_can_be_stopped(loop):
    run = BakeoffRun(request=BakeoffRequest(assistant_ids=["asst-mock-evidence-v1"], subject_ids=["subj-mock-v1"]))
    bl = BakeoffLoop(loop)
    bl.request_stop(run.id)  # requested while still queued: the loop stops at its first step
    bl.run(run)
    assert run.status == "cancelled" and run.error is None and run.active == []
    assert run.events[-1].text.startswith("stopped by the user")


def test_bakeoff_rejects_unknown_case(loop):
    run = BakeoffRun(request=BakeoffRequest(assistant_ids=["asst-mock-evidence-v1"], subject_ids=["subj-mock-v1"], case_ids=["nope"]))
    BakeoffLoop(loop).run(run)
    assert run.status == "failed" and "nope" in (run.error or "")
