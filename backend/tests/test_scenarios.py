from app.agents.context import detect_topics
from app.schemas import Role


def test_every_family_has_matched_truthful_and_deceptive_variants(engine):
    for family, cases in engine.families().items():
        roles = {engine.lock(c).evaluator.assigned_role for c in cases}
        assert roles == {Role.truthful, Role.deceptive}, family
        difficulties = {engine.public(c).difficulty for c in cases}
        assert len(difficulties) == 1, "matched variants must share difficulty"


def test_question_bank_questions_map_to_their_own_topic(engine):
    for p in engine.list_public():
        for topic, q in p.question_bank.items():
            got = detect_topics(q, p.topic_keywords)
            assert got and got[0] == topic, (p.case_id, topic, got)


def test_communication_style_is_independent_of_role(engine):
    styles = {}
    for cid in engine.case_ids():
        s = engine.lock(cid)
        styles.setdefault(s.private.role, []).append(s.private.communication_style)
    truthful, deceptive = " ".join(styles[Role.truthful]), " ".join(styles[Role.deceptive])
    assert "nervous" in truthful or "anxious" in truthful
    assert "nervous" in deceptive or "anxious" in deceptive
    assert "polished" in truthful and "polished" in deceptive


def test_evidence_release_is_scripted_and_locked(engine):
    s = engine.lock("case_A2")
    assert [e.id for e in engine.evidence_for_turn(s, 2)] == ["A-E1"]
    assert [e.id for e in engine.evidence_for_turn(s, 4)] == ["A-E2"]
    assert engine.evidence_for_turn(s, 3) == []
    s.evaluator.canonical_facts.append("mutated")
    assert "mutated" not in engine.lock("case_A2").evaluator.canonical_facts


def test_deceptive_private_packets_declare_a_violation_and_sensitive_topics(engine):
    for cid in engine.case_ids():
        s = engine.lock(cid)
        if s.private.role == Role.deceptive:
            assert s.evaluator.violation
            assert any(t.sensitive and t.deceptive_answer for t in s.private.topics)
        else:
            assert s.evaluator.violation is None
            assert all(t.deceptive_answer is None for t in s.private.topics)
