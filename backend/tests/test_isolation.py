from app.loops.interview_loop import build_assistant_context
from app.scoring.scoring import isolation_check
from app.schemas import Turn


def test_assistant_context_cannot_see_private_or_evaluator_data(engine):
    for cid in engine.case_ids():
        s = engine.lock(cid)
        turns = [Turn(index=1, question="Why did you enter?", answer="busy shift")]
        ctx = build_assistant_context(s, turns, s.public.initial_documents, {})
        blob = ctx.snapshot().lower()
        assert isolation_check([blob], s.evaluator.isolation_canaries)
        assert s.private.role.value not in blob.replace("case_id", "")  # role word never in the context
        assert s.private.objective.lower() not in blob
        assert (s.evaluator.violation or "zzz").lower() not in blob


def test_isolation_check_catches_a_leak(engine):
    s = engine.lock("case_A2")
    leaked = ["public stuff", "ROLE=deceptive (hidden)"]
    assert not isolation_check(leaked, s.evaluator.isolation_canaries)


def test_full_mock_session_passes_isolation_gate(loop, engine):
    for cid in engine.case_ids():
        s = engine.lock(cid)
        session = loop.run_scripted(s, "asst-mock-evidence-v1", "subj-mock-v1", 8, relay_assistant=True)
        assert session.assistant_inputs
        assert isolation_check(session.assistant_inputs, s.evaluator.isolation_canaries), cid
