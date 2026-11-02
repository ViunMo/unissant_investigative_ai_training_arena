import pytest

from app.schemas import FinalFinding, Finding, Mode


def ask(loop, session, scenario, q):
    return loop.step(session, scenario, q)


def test_practice_session_on_deceptive_case_surfaces_contradiction(loop, engine):
    session, scenario = loop.start(Mode.practice, "tester", "case_A2", "asst-mock-evidence-v1", "subj-mock-v1", max_turns=6)
    assert [e.id for e in session.released_evidence] == ["A-E0"]
    qs = ["Why did you enter the server room?", "Which work order covered it?", "Who authorized the entry?",
          "What time did you leave?", "What equipment did you take out?"]
    for q in qs:
        ask(loop, session, scenario, q)
    assert [e.id for e in session.released_evidence] == ["A-E0", "A-E1", "A-E2"]
    assert session.turns[1].evidence_released[0].id == "A-E1"
    last = session.turns[-1].coaching
    assert any(f.kind.value == "contradiction" and f.turn_index == 3 for f in last.flags)
    assert last.interim_finding == Finding.deceptive
    loop.commit(session, scenario, FinalFinding(finding=Finding.deceptive, confidence=0.8, rationale="roster conflict"))
    assert session.status == "locked"
    assert session.debrief.investigator_correct and session.debrief.assistant_correct
    assert session.debrief.isolation_pass
    assert session.debrief.evasion_precision == 1.0


def test_truthful_uncertain_subject_is_not_accused(loop, engine):
    scenario = engine.lock("case_C1")
    session = loop.run_scripted(scenario, "asst-mock-evidence-v1", "subj-mock-v1", 8, relay_assistant=True)
    assert session.assistant_final.finding == Finding.truthful
    kinds = [f.kind.value for t in session.turns for f in t.coaching.flags]
    assert "explicit_uncertainty" in kinds and "possible_evasion" not in kinds


def test_turn_budget_is_enforced(loop):
    session, scenario = loop.start(Mode.assessment, "tester", "case_B1", "asst-mock-evidence-v1", "subj-mock-v1", max_turns=2)
    ask(loop, session, scenario, "How was the count carried out?")
    ask(loop, session, scenario, "Who counted with you?")
    assert session.status == "awaiting_finding"
    with pytest.raises(ValueError):
        ask(loop, session, scenario, "one more")
    loop.commit(session, scenario, FinalFinding(finding=Finding.insufficient_evidence, confidence=0.3))
    with pytest.raises(ValueError):
        loop.commit(session, scenario, FinalFinding(finding=Finding.truthful, confidence=0.3))


def test_replay_track_sees_only_evidence_released_at_each_point(loop, engine):
    scenario = engine.lock("case_C2")
    frozen = loop.run_scripted(scenario, "asst-mock-evidence-v1", "subj-mock-v1", 6, relay_assistant=False, coach=False)
    assert all(t.coaching is None for t in frozen.turns)
    replayed = loop.replay(frozen, scenario, "asst-mock-evidence-v1")
    assert [t.question for t in replayed.turns] == [t.question for t in frozen.turns]
    assert all(t.coaching is not None for t in replayed.turns)
    assert replayed.assistant_final is not None
