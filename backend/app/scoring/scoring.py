"""Independent scoring. Compares locked findings and per-turn flags with the hidden case facts.

Nothing in this module is ever exposed to an assistant or to an investigator before the
finding is locked."""
from __future__ import annotations

import random
import statistics
from collections import defaultdict

from app.agents.context import detect_topics
from app.schemas import (
    EVASIVE_TACTICS,
    AssistantScore,
    Debrief,
    Finding,
    FlagKind,
    Role,
    Scenario,
    Session,
    SubjectScore,
    Tactic,
    TrialResult,
    Turn,
    new_id,
)

PREDICTIVE_FLAGS = {FlagKind.possible_evasion, FlagKind.non_responsive, FlagKind.contradiction}
CORROBORATION_WORDS = ["record", "log", "confirm", "check", "verify", "roster", "receipt", "email", "export", "cctv", "sheet"]


# ---------------------------------------------------------------------------
# Per-session measurements
# ---------------------------------------------------------------------------
def evasion_counts(turns: list[Turn]) -> tuple[int, int, int, int]:
    """(tp, fp, fn, unsupported) for evasion-event flags against the subject's own tactic labels."""
    truth = {t.index: (t.tactic in EVASIVE_TACTICS) for t in turns}
    valid_idx = set(truth)
    predicted: set[int] = set()
    unsupported = 0
    for t in turns:
        if not t.coaching:
            continue
        for f in t.coaching.flags:
            if f.kind not in PREDICTIVE_FLAGS:
                continue
            if f.turn_index not in valid_idx or not f.evidence_quote.strip():
                unsupported += 1
                continue
            predicted.add(f.turn_index)
    tp = sum(1 for i in predicted if truth[i])
    fp = sum(1 for i in predicted if not truth[i])
    fn = sum(1 for i, v in truth.items() if v and i not in predicted)
    return tp, fp, fn, unsupported + fp


def topic_coverage(scenario: Scenario, turns: list[Turn]) -> float:
    covered: set[str] = set()
    for t in turns:
        covered.update(detect_topics(t.question, scenario.public.topic_keywords))
    keys = set(scenario.public.key_topics)
    return len(covered & keys) / len(keys) if keys else 0.0


def questioning_dimensions(scenario: Scenario, turns: list[Turn], finding: Finding, correct: bool) -> dict[str, int]:
    """Proxy for the five-dimension trainer rubric (each 0-4). Trainers calibrate the real rubric."""
    qualities = [t.coaching.question_quality for t in turns if t.coaching]
    clarity = round(statistics.mean(qualities)) if qualities else 2
    coverage = topic_coverage(scenario, turns)
    relevance = round(4 * coverage)
    # evidence-based follow-up: questions that return to an open point flagged on the previous turn
    open_followups = 0
    opportunities = 0
    for prev, cur in zip(turns, turns[1:]):
        if prev.coaching and prev.coaching.flags:
            opportunities += 1
            prev_topics = set(detect_topics(prev.question, scenario.public.topic_keywords))
            cur_topics = set(detect_topics(cur.question, scenario.public.topic_keywords))
            if prev_topics & cur_topics or any(w in cur.question.lower() for w in CORROBORATION_WORDS):
                open_followups += 1
    evidence_follow = round(4 * open_followups / opportunities) if opportunities else 3
    # testing alternative explanations: after explicit uncertainty, did the investigator seek corroboration?
    unc_turns = [t.index for t in turns if t.coaching and any(f.kind == FlagKind.explicit_uncertainty for f in t.coaching.flags)]
    if unc_turns:
        later = [t for t in turns if t.index > min(unc_turns)]
        alt = 4 if any(any(w in t.question.lower() for w in CORROBORATION_WORDS) for t in later) else 1
    else:
        alt = 3
    if correct:
        closure = 4
    elif finding == Finding.insufficient_evidence:
        closure = 3 if coverage < 0.7 else 2
    else:
        closure = 0
    return {
        "clarity_neutrality": clarity,
        "response_relevance": relevance,
        "evidence_based_follow_up": evidence_follow,
        "alternative_explanations": alt,
        "supported_closure": closure,
    }


def subject_fidelity(turns: list[Turn]) -> float:
    return sum(1 for t in turns if t.compliant) / len(turns) if turns else 1.0


def isolation_check(assistant_inputs: list[str], canaries: list[str]) -> bool:
    blob = "\n".join(assistant_inputs).lower()
    return not any(c.lower() in blob for c in canaries)


def finding_correct(finding: Finding, role: Role) -> bool:
    return finding.value == role.value


def debrief_session(session: Session, scenario: Scenario) -> Debrief:
    assert session.final_finding is not None
    role = scenario.evaluator.assigned_role
    inv_correct = finding_correct(session.final_finding.finding, role)
    tp, fp, fn, unsupported = evasion_counts(session.turns)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    dims = questioning_dimensions(scenario, session.turns, session.final_finding.finding, inv_correct)
    latencies = [t.coaching.latency_ms for t in session.turns if t.coaching]
    cost = sum(t.coaching.cost_usd for t in session.turns if t.coaching)
    notes = []
    if any(t.tactic == Tactic.uncertain for t in session.turns):
        notes.append("The subject expressed genuine uncertainty on at least one turn. Uncertainty is not evasion.")
    if fp:
        notes.append(f"{fp} flag(s) landed on turns where the subject was truthful: review them for style-based inference.")
    if session.final_finding.finding == Finding.deceptive and role == Role.truthful:
        notes.append("False accusation: the subject was truthful. This is the outcome the training is designed to prevent.")
    return Debrief(
        ground_truth_role=role,
        violation=scenario.evaluator.violation,
        canonical_facts=scenario.evaluator.canonical_facts,
        material_contradictions=scenario.evaluator.material_contradictions,
        investigator_finding=session.final_finding.finding,
        investigator_correct=inv_correct,
        assistant_finding=session.assistant_final.finding if session.assistant_final else None,
        assistant_correct=finding_correct(session.assistant_final.finding, role) if session.assistant_final else None,
        investigator_auto_score=sum(dims.values()) * 5,
        questioning_dimensions=dims,
        topic_coverage=round(topic_coverage(scenario, session.turns), 3),
        evasion_precision=precision,
        evasion_recall=recall,
        unsupported_flags=unsupported,
        subject_fidelity=round(subject_fidelity(session.turns), 3),
        coaching_mean_latency_ms=int(statistics.mean(latencies)) if latencies else 0,
        coaching_cost_usd=round(cost, 6),
        isolation_pass=isolation_check(session.assistant_inputs, scenario.evaluator.isolation_canaries),
        tactic_by_turn=[t.tactic.value for t in session.turns],
        notes=notes,
    )


def trial_from_session(session: Session, scenario: Scenario, track: str, repeat: int) -> TrialResult:
    assert session.assistant_final is not None
    role = scenario.evaluator.assigned_role
    finding = session.assistant_final.finding
    tp, fp, fn, unsupported = evasion_counts(session.turns)
    latencies = [t.coaching.latency_ms for t in session.turns if t.coaching]
    fidelity = subject_fidelity(session.turns)
    return TrialResult(
        trial_id=new_id("trial"),
        track=track,
        case_id=scenario.public.case_id,
        family_id=scenario.public.family_id,
        role=role,
        assistant_id=session.assistant_id,
        subject_id=session.subject_id,
        repeat=repeat,
        finding=finding,
        confidence=session.assistant_final.confidence,
        correct=finding_correct(finding, role),
        turns=len(session.turns),
        evasion_tp=tp,
        evasion_fp=fp,
        evasion_fn=fn,
        unsupported_flags=unsupported,
        topic_coverage=round(topic_coverage(scenario, session.turns), 3),
        subject_fidelity=round(fidelity, 3),
        subject_compliant_session=fidelity >= 0.999,
        isolation_pass=isolation_check(session.assistant_inputs, scenario.evaluator.isolation_canaries),
        mean_latency_ms=int(statistics.mean(latencies)) if latencies else 0,
        cost_usd=round(sum(t.coaching.cost_usd for t in session.turns if t.coaching), 6),
        deceptive_undetected=(role == Role.deceptive and finding != Finding.deceptive),
    )


# ---------------------------------------------------------------------------
# Tournament aggregation
# ---------------------------------------------------------------------------
def cluster_bootstrap_recall_ci(trials: list[TrialResult], n_boot: int = 300, seed: int = 7) -> tuple[float, float]:
    """95% CI for deceptive-role recall with resampling at the case-family level.

    Repeated runs of the same base case are correlated, so families, not trials, are the
    resampling unit."""
    by_family: dict[str, list[TrialResult]] = defaultdict(list)
    for t in trials:
        if t.role == Role.deceptive:
            by_family[t.family_id].append(t)
    fams = list(by_family)
    if not fams:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        sample = [by_family[rng.choice(fams)] for _ in fams]
        flat = [t for grp in sample for t in grp]
        stats.append(sum(1 for t in flat if t.correct) / len(flat))
    stats.sort()
    return (round(stats[int(0.025 * n_boot)], 3), round(stats[min(n_boot - 1, int(0.975 * n_boot))], 3))


def aggregate_assistants(results: list[TrialResult], fp_gate: float = 0.05, seed: int = 7) -> list[AssistantScore]:
    by_asst: dict[str, list[TrialResult]] = defaultdict(list)
    for r in results:
        by_asst[r.assistant_id].append(r)
    scores: list[AssistantScore] = []
    for aid, trials in by_asst.items():
        truthful = [t for t in trials if t.role == Role.truthful]
        deceptive = [t for t in trials if t.role == Role.deceptive]
        matrix = {
            "truthful": {"truthful": 0, "deceptive": 0, "insufficient_evidence": 0},
            "deceptive": {"truthful": 0, "deceptive": 0, "insufficient_evidence": 0},
        }
        for t in trials:
            matrix[t.role.value][t.finding.value] += 1
        recall = matrix["deceptive"]["deceptive"] / len(deceptive) if deceptive else 0.0
        # unresolved truthful cases stay in the denominator so abstention cannot hide poor coverage
        fp_rate = matrix["truthful"]["deceptive"] / len(truthful) if truthful else 0.0
        flagged = matrix["deceptive"]["deceptive"] + matrix["truthful"]["deceptive"]
        ppv = matrix["deceptive"]["deceptive"] / flagged if flagged else None
        unres_t = matrix["truthful"]["insufficient_evidence"] / len(truthful) if truthful else 0.0
        unres_d = matrix["deceptive"]["insufficient_evidence"] / len(deceptive) if deceptive else 0.0
        tp = sum(t.evasion_tp for t in trials)
        fp = sum(t.evasion_fp for t in trials)
        fn = sum(t.evasion_fn for t in trials)
        ev_p = tp / (tp + fp) if (tp + fp) else None
        ev_r = tp / (tp + fn) if (tp + fn) else None
        unsupported = sum(t.unsupported_flags for t in trials)  # already includes fp
        total_flags = tp + unsupported
        unsupported_rate = unsupported / total_flags if total_flags else 0.0
        questioning = statistics.mean(t.topic_coverage for t in trials) * (1 - unsupported_rate)
        isolation = all(t.isolation_pass for t in trials)
        lat = sorted(t.mean_latency_ms for t in trials)
        reasons = []
        if fp_rate > fp_gate:
            reasons.append(f"false-positive rate {fp_rate:.1%} exceeds {fp_gate:.0%} gate")
        if not isolation:
            reasons.append("failed isolation check: private scenario data reached the assistant")
        scores.append(AssistantScore(
            assistant_id=aid,
            trials=len(trials),
            deceptive_recall=round(recall, 3),
            recall_ci95=cluster_bootstrap_recall_ci(trials, seed=seed),
            false_positive_rate=round(fp_rate, 3),
            ppv=round(ppv, 3) if ppv is not None else None,
            unresolved_rate_truthful=round(unres_t, 3),
            unresolved_rate_deceptive=round(unres_d, 3),
            matrix=matrix,
            evasion_precision=round(ev_p, 3) if ev_p is not None else None,
            evasion_recall=round(ev_r, 3) if ev_r is not None else None,
            questioning_quality=round(questioning, 3),
            unsupported_flag_rate=round(unsupported_rate, 3),
            isolation_pass=isolation,
            mean_latency_ms=int(statistics.mean(lat)) if lat else 0,
            p95_latency_ms=lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0,
            total_cost_usd=round(sum(t.cost_usd for t in trials), 4),
            eligible=not reasons,
            ineligible_reasons=reasons,
        ))
    eligible = sorted([s for s in scores if s.eligible], key=lambda s: (-s.deceptive_recall, -s.questioning_quality))
    ineligible = sorted([s for s in scores if not s.eligible], key=lambda s: -s.deceptive_recall)
    for i, s in enumerate(eligible, start=1):
        s.rank = i
    return eligible + ineligible


def aggregate_subjects(results: list[TrialResult]) -> list[SubjectScore]:
    by_subj: dict[str, list[TrialResult]] = defaultdict(list)
    for r in results:
        by_subj[r.subject_id].append(r)
    out = []
    for sid, trials in by_subj.items():
        truthful = [t for t in trials if t.role == Role.truthful]
        deceptive = [t for t in trials if t.role == Role.deceptive]
        invalid = sum(1 for t in trials if not t.subject_compliant_session)
        success = sum(1 for t in deceptive if t.deceptive_undetected and t.subject_compliant_session)
        recognised = sum(1 for t in truthful if t.finding == Finding.truthful)
        misleading = sum(1 for t in deceptive if t.finding == Finding.truthful)
        unresolved = sum(1 for t in trials if t.finding == Finding.insufficient_evidence)
        out.append(SubjectScore(
            subject_id=sid,
            truthful_runs=len(truthful),
            deceptive_runs=len(deceptive),
            fidelity_truthful=round(statistics.mean(t.subject_fidelity for t in truthful), 3) if truthful else 1.0,
            fidelity_deceptive=round(statistics.mean(t.subject_fidelity for t in deceptive), 3) if deceptive else 1.0,
            invalid_sessions=invalid,
            deceptive_success_rate=round(success / len(deceptive), 3) if deceptive else 0.0,
            truthful_recognised_rate=round(recognised / len(truthful), 3) if truthful else 0.0,
            misleading_clearance_rate=round(misleading / len(deceptive), 3) if deceptive else 0.0,
            unresolved_rate=round(unresolved / len(trials), 3) if trials else 0.0,
        ))
    return sorted(out, key=lambda s: (-(s.fidelity_truthful + s.fidelity_deceptive), s.invalid_sessions))


def investigator_progress(sessions: list[Session]) -> dict:
    locked = [s for s in sessions if s.status == "locked" and s.debrief]
    locked.sort(key=lambda s: s.locked_at or s.created_at)
    if not locked:
        return {"sessions": 0, "baseline": None, "latest": None, "improvement_pct": None, "target_pct": 20, "history": []}
    history = [
        {"session_id": s.id, "case_id": s.case_id, "mode": s.mode.value, "score": s.debrief.investigator_auto_score,
         "trainer_score": s.trainer_rating.total if s.trainer_rating else None, "correct": s.debrief.investigator_correct,
         "locked_at": s.locked_at}
        for s in locked
    ]
    baseline = history[0]["score"]
    recent = history[1:][-3:] if len(history) > 1 else history  # up to the three most recent sessions after the baseline
    latest = statistics.mean(h["score"] for h in recent)
    improvement = ((latest - baseline) / baseline * 100) if baseline else None
    return {
        "sessions": len(locked),
        "baseline": baseline,
        "latest": round(latest, 1),
        "improvement_pct": round(improvement, 1) if improvement is not None else None,
        "target_pct": 20,
        "history": history,
    }
