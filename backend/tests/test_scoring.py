from app.schemas import Finding, Role, Session, Mode, Debrief, TrialResult, new_id
from app.scoring.scoring import aggregate_assistants, aggregate_subjects, cluster_bootstrap_recall_ci, investigator_progress


def trial(aid, role, finding, family="f1", **kw):
    base = dict(trial_id=new_id("t"), track="interactive", case_id="c", family_id=family, role=role, assistant_id=aid,
                subject_id="s", repeat=1, finding=finding, confidence=0.5, correct=(finding.value == role.value), turns=4,
                evasion_tp=1, evasion_fp=0, evasion_fn=0, unsupported_flags=0, topic_coverage=1.0, subject_fidelity=1.0,
                subject_compliant_session=True, isolation_pass=True, mean_latency_ms=10, cost_usd=0.0,
                deceptive_undetected=(role == Role.deceptive and finding != Finding.deceptive))
    base.update(kw)
    return TrialResult(**base)


def test_false_positive_gate_and_ranking():
    trials = []
    # careful: catches 3/4 deceptive, never accuses truthful
    for i in range(4):
        trials.append(trial("careful", Role.deceptive, Finding.deceptive if i < 3 else Finding.insufficient_evidence, family=f"f{i}"))
        trials.append(trial("careful", Role.truthful, Finding.truthful, family=f"f{i}"))
    # bold: catches 4/4 deceptive but accuses 1/4 truthful
    for i in range(4):
        trials.append(trial("bold", Role.deceptive, Finding.deceptive, family=f"f{i}"))
        trials.append(trial("bold", Role.truthful, Finding.deceptive if i == 0 else Finding.truthful, family=f"f{i}"))
    board = aggregate_assistants(trials)
    by_id = {s.assistant_id: s for s in board}
    assert by_id["careful"].eligible and by_id["careful"].rank == 1
    assert not by_id["bold"].eligible and by_id["bold"].rank is None
    assert by_id["bold"].false_positive_rate == 0.25
    assert by_id["careful"].deceptive_recall == 0.75
    assert board[0].assistant_id == "careful"


def test_unresolved_truthful_cases_stay_in_denominator():
    trials = [trial("a", Role.truthful, Finding.insufficient_evidence, family=f"f{i}") for i in range(3)]
    trials.append(trial("a", Role.truthful, Finding.deceptive, family="f9"))
    s = aggregate_assistants(trials)[0]
    assert s.false_positive_rate == 0.25
    assert s.unresolved_rate_truthful == 0.75
    assert s.matrix["truthful"]["insufficient_evidence"] == 3


def test_isolation_failure_makes_candidate_ineligible():
    trials = [trial("a", Role.deceptive, Finding.deceptive, isolation_pass=False)]
    s = aggregate_assistants(trials)[0]
    assert not s.eligible and any("isolation" in r for r in s.ineligible_reasons)


def test_cluster_bootstrap_ci_is_bounded_and_family_based():
    trials = [trial("a", Role.deceptive, Finding.deceptive, family="f1")] * 5 + [trial("a", Role.deceptive, Finding.insufficient_evidence, family="f2")]
    lo, hi = cluster_bootstrap_recall_ci(trials, n_boot=100)
    assert 0.0 <= lo <= hi <= 1.0


def test_subject_leaderboard_scores_roles_separately():
    trials = [
        trial("a", Role.deceptive, Finding.insufficient_evidence, subject_id="s1"),
        trial("a", Role.deceptive, Finding.deceptive, subject_id="s1"),
        trial("a", Role.truthful, Finding.truthful, subject_id="s1"),
        trial("a", Role.truthful, Finding.truthful, subject_id="s1", subject_fidelity=0.5, subject_compliant_session=False),
    ]
    s = aggregate_subjects(trials)[0]
    assert s.deceptive_runs == 2 and s.truthful_runs == 2
    assert s.deceptive_success_rate == 0.5
    assert s.invalid_sessions == 1
    assert s.fidelity_truthful == 0.75


def test_investigator_progress_against_own_baseline():
    def sess(score, when):
        d = Debrief(ground_truth_role=Role.truthful, violation=None, canonical_facts=[], material_contradictions=[],
                    investigator_finding=Finding.truthful, investigator_correct=True, assistant_finding=None, assistant_correct=None,
                    investigator_auto_score=score, questioning_dimensions={}, topic_coverage=1.0, evasion_precision=None,
                    evasion_recall=None, unsupported_flags=0, subject_fidelity=1.0, coaching_mean_latency_ms=1, coaching_cost_usd=0,
                    isolation_pass=True, tactic_by_turn=[])
        return Session(mode=Mode.assessment, investigator="i", case_id="c", assistant_id="a", subject_id="s", max_turns=4,
                       status="locked", debrief=d, locked_at=when)
    p = investigator_progress([sess(50, "2026-01-01"), sess(70, "2026-01-03"), sess(60, "2026-01-02")])
    assert p["baseline"] == 50 and p["latest"] == 65.0 and p["improvement_pct"] == 30.0
    assert investigator_progress([])["baseline"] is None
