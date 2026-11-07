"""Bring-your-own cases: parse an uploaded file, compile a short "case brief" into the full three-packet
Scenario, and check it before it enters the engine.

Two input shapes are accepted, in JSON or YAML, one case or a list of cases:

* a **case brief**: the author-friendly form below (title, context, persona, lines of questioning with a
  truthful and, for deceptive roles, a concealing answer, scripted evidence). Everything the engine needs but the
  author did not write (keywords, question bank, isolation canaries, ids) is derived here.
* a **full scenario**: the engine's own ``{"version", "split", "public", "private", "evaluator"}`` object, as
  returned by ``GET /api/scenarios/{case_id}/export``.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.agents.context import detect_topics
from app.schemas import (
    EvaluatorPacket,
    EvidenceItem,
    PrivateSubjectPacket,
    PublicCasePacket,
    Role,
    Scenario,
    Tactic,
    TopicScript,
)

TRUTHFUL_OBJECTIVE = "Answer accurately from what you know. Say when you do not know."
CONCEALING_CANARY = "if concealing, you may say"
STOPWORDS = {
    "what", "when", "who", "where", "which", "how", "why", "can", "could", "you", "your", "the", "a", "an", "and", "or",
    "of", "to", "in", "on", "at", "for", "with", "from", "that", "this", "those", "these", "was", "were", "is", "are",
    "did", "do", "does", "have", "has", "had", "tell", "me", "about", "walk", "through", "describe", "please", "any",
    "there", "their", "them", "they", "it", "its", "into", "than", "then", "been", "being", "would", "should", "will",
    "exactly", "happened", "happen", "took", "take", "place", "before", "after", "during", "between", "while", "also",
}


# ---------------------------------------------------------------------------
# The case brief
# ---------------------------------------------------------------------------
class BriefEvidence(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    release_after_turn: int = Field(default=0, ge=0)
    contradicts: list[str] = Field(default_factory=list)  # phrases in the subject's answers this record conflicts with


class BriefTopic(BaseModel):
    topic: str = Field(min_length=1)
    question: str = Field(min_length=1)  # the neutral question the coach may suggest
    keywords: list[str] = Field(default_factory=list)  # derived from the topic and question when omitted
    truthful_answer: str = Field(min_length=1)
    deceptive_answer: str | None = None  # deceptive cases: what the subject says to conceal
    tactic: Tactic = Tactic.omission  # how the deceptive answer evades
    sensitive: bool | None = None  # touches the violation; defaults to "has a deceptive answer"
    uncertain: bool = False  # a truthful subject genuinely does not recall


class BriefSubject(BaseModel):
    name: str = Field(min_length=1)
    position: str = Field(min_length=1)
    communication_style: str = Field(min_length=1)
    known_facts: list[str] = Field(min_length=1)
    may_disclose: list[str] = Field(default_factory=list)
    must_not_disclose: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    objective: str | None = None


class CaseBrief(BaseModel):
    case_id: str | None = None
    family_id: str | None = None
    title: str = Field(min_length=1)
    role: Role
    split: Literal["development", "hidden"] = "hidden"
    difficulty: Literal["low", "medium", "high"] = "medium"
    objective: str = Field(min_length=1)
    context: str = Field(min_length=1)
    known_timeline: list[str] = Field(min_length=1)
    interview_context: str = "Voluntary interview. Subject has been told the topic of the interview."
    initial_question: str = Field(min_length=1)
    max_turns: int = Field(default=12, ge=2, le=20)
    initial_documents: list[BriefEvidence] = Field(default_factory=list)
    subject: BriefSubject
    topics: list[BriefTopic] = Field(min_length=2)
    evidence_release: list[BriefEvidence] = Field(default_factory=list)
    violation: str | None = None
    canonical_facts: list[str] = Field(min_length=1)
    material_contradictions: list[str] = Field(default_factory=list)
    resolution_criteria: str | None = None
    version: str = "uploaded"


class DraftedCases(BaseModel):
    """What the drafting model must return: one or more briefs."""

    cases: list[CaseBrief] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------
def slug(text: str, max_len: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:max_len].rstrip("_") or "case"


def _phrase(question: str) -> str:
    """The distinctive tail of a question: strip the opener and punctuation, keep the rest as one long keyword."""
    q = re.sub(r"[^a-z0-9' ]+", " ", question.lower())
    words = q.split()
    while words and words[0] in STOPWORDS:
        words.pop(0)
    return " ".join(words[:6])


def derive_keywords(topic: str, question: str) -> list[str]:
    """Keywords that make the topic's own question detect that topic first (longest keyword wins in detect_topics)."""
    kws: list[str] = []
    phrase = _phrase(question)
    if phrase:
        kws.append(phrase)
    kws.append(topic.replace("_", " ").lower())
    for w in re.findall(r"[a-z0-9'-]+", question.lower()):
        if len(w) >= 4 and w not in STOPWORDS and w not in kws:
            kws.append(w)
    return kws


def derive_topic_keywords(topics: list[tuple[str, str, list[str]]]) -> dict[str, list[str]]:
    """Per-topic keywords; explicit lists are kept as written, derived single words shared by several topics are
    dropped so that a question about one line of questioning is not credited to another."""
    derived = {topic: derive_keywords(topic, question) for topic, question, given in topics if not given}
    counts: dict[str, int] = {}
    for kws in derived.values():
        for k in kws[1:]:  # [0] is the question phrase; [1] the topic name (kept, but it claims the word)
            counts[k] = counts.get(k, 0) + 1
    out: dict[str, list[str]] = {}
    for topic, _question, given in topics:
        kws = given or [k for i, k in enumerate(derived[topic]) if i < 2 or counts.get(k, 0) == 1]
        out[topic] = list(dict.fromkeys(k.strip().lower() for k in kws if k.strip()))
    return out


def _evidence(items: list[BriefEvidence], prefix: str, start: int) -> list[EvidenceItem]:
    out = []
    for n, e in enumerate(items, start=start):
        out.append(EvidenceItem(id=e.id or f"{prefix}-E{n}", title=e.title, content=e.content,
                                release_after_turn=e.release_after_turn, conflicts_with_keywords=e.contradicts))
    return out


def compile_brief(brief: CaseBrief) -> Scenario:
    role = brief.role
    family_id = brief.family_id or f"fam_{slug(brief.title)}"
    case_id = brief.case_id or f"case_{slug(brief.title, 24)}_{'t' if role == Role.truthful else 'd'}"
    prefix = re.sub(r"[^A-Z0-9]", "", case_id.upper())[:6] or "X"

    topic_keywords = derive_topic_keywords([(t.topic, t.question, t.keywords) for t in brief.topics])
    question_bank = {t.topic: t.question for t in brief.topics}
    public = PublicCasePacket(
        case_id=case_id, family_id=family_id, title=brief.title, objective=brief.objective, context=brief.context,
        known_timeline=brief.known_timeline, initial_documents=_evidence(brief.initial_documents, prefix, 0),
        interview_context=brief.interview_context, difficulty=brief.difficulty, initial_question=brief.initial_question,
        key_topics=[t.topic for t in brief.topics], topic_keywords=topic_keywords, question_bank=question_bank,
        max_turns=brief.max_turns,
    )

    deceptive = role == Role.deceptive
    scripts = []
    for t in brief.topics:
        sensitive = t.sensitive if t.sensitive is not None else bool(t.deceptive_answer)
        scripts.append(TopicScript(
            topic=t.topic, keywords=topic_keywords[t.topic], truthful_answer=t.truthful_answer,
            deceptive_answer=t.deceptive_answer if deceptive else None,
            deceptive_tactic=t.tactic if (deceptive and t.deceptive_answer) else Tactic.truthful,
            sensitive=sensitive if deceptive else False, uncertain_truthful=t.uncertain,
        ))
    subj = brief.subject
    if deceptive:
        objective = subj.objective or f"Keep the following undiscovered while staying inside the scenario facts: {brief.violation or 'the violation'}"
        behaviours = [Tactic.truthful, Tactic.omission, Tactic.deflection, Tactic.minimisation, Tactic.contradiction]
        may = subj.may_disclose or ["the public timeline", "general duties of the role"]
        must_not = subj.must_not_disclose
    else:
        objective = subj.objective or TRUTHFUL_OBJECTIVE
        behaviours = [Tactic.truthful, Tactic.uncertain]
        may = subj.may_disclose or ["all known facts"]
        must_not = subj.must_not_disclose or ["anything the subject does not actually know"]
    private = PrivateSubjectPacket(
        role=role, persona_name=subj.name, persona_position=subj.position, communication_style=subj.communication_style,
        known_facts=subj.known_facts, may_disclose=may, must_not_disclose=must_not,
        uncertainty_notes=subj.uncertainty_notes, objective=objective, permitted_behaviors=behaviours, topics=scripts,
    )

    canaries = [f"ROLE={role.value}", f"assigned role: {role.value}", objective]
    if deceptive:
        canaries.append(CONCEALING_CANARY)
    criteria = brief.resolution_criteria or (
        "Deceptive if the subject's account conflicts with released records and the subject does not reconcile it."
        if deceptive else "Truthful if the subject's account is corroborated by the released records."
    )
    evaluator = EvaluatorPacket(
        assigned_role=role, violation=brief.violation if deceptive else None, canonical_facts=brief.canonical_facts,
        material_contradictions=brief.material_contradictions,
        evidence_release=_evidence(brief.evidence_release, prefix, len(brief.initial_documents)),
        resolution_criteria=criteria, isolation_canaries=canaries,
    )
    return Scenario(version=brief.version, split=brief.split, public=public, private=private, evaluator=evaluator)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_scenario(s: Scenario) -> list[str]:
    """Problems that would make a case misbehave in an interview or a bake-off (warnings, not hard errors)."""
    w: list[str] = []
    p, pr, ev = s.public, s.private, s.evaluator
    if pr.role != ev.assigned_role:
        w.append("private role and evaluator assigned_role differ")
    for topic, q in p.question_bank.items():
        got = detect_topics(q, p.topic_keywords)
        if not got or got[0] != topic:
            w.append(f"question for '{topic}' is detected as {got[:1] or 'no topic'}: add a distinctive keyword")
    missing = [t for t in p.key_topics if t not in {ts.topic for ts in pr.topics}]
    if missing:
        w.append(f"subject has no script for topics {missing}")
    if pr.role == Role.deceptive:
        if not ev.violation:
            w.append("deceptive case has no violation")
        if not any(t.sensitive and t.deceptive_answer for t in pr.topics):
            w.append("deceptive case has no sensitive topic with a concealing answer: the subject will simply tell the truth")
        if not pr.must_not_disclose:
            w.append("deceptive case lists nothing under must_not_disclose; compliance cannot be checked")
    else:
        if any(t.deceptive_answer for t in pr.topics):
            w.append("truthful case carries deceptive answers (they are ignored)")
    ids = [e.id for e in p.initial_documents + ev.evidence_release]
    if len(ids) != len(set(ids)):
        w.append("duplicate evidence ids")
    late = [e.id for e in ev.evidence_release if e.release_after_turn > p.max_turns]
    if late:
        w.append(f"records {late} release after the exchange budget ({p.max_turns}) and will never appear")
    if not ev.evidence_release:
        w.append("no scripted evidence release: contradiction flags can only rest on the initial records")
    if not ev.isolation_canaries:
        w.append("no isolation canaries: leaks of the private packet cannot be detected")
    return w


# ---------------------------------------------------------------------------
# Parsing an upload
# ---------------------------------------------------------------------------
class ImportItem(BaseModel):
    index: int
    case_id: str | None = None
    kind: Literal["brief", "scenario"] | None = None
    scenario: Scenario | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def parse_document(text: str, filename: str | None = None) -> list[dict]:
    """JSON or YAML text -> list of raw case objects (a single object, a list, or {"cases": [...]})."""
    if not text or not text.strip():
        raise ValueError("the file is empty")
    name = (filename or "").lower()
    data: Any
    if name.endswith(".json"):
        data = json.loads(text)
    elif name.endswith((".yaml", ".yml")):
        data = yaml.safe_load(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise ValueError(f"not valid JSON or YAML: {str(exc)[:200]}") from exc
    if isinstance(data, dict) and isinstance(data.get("cases"), list):
        data = data["cases"]
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ValueError("expected one case object, a list of cases, or {\"cases\": [...]}")
    bad = [i for i, d in enumerate(data) if not isinstance(d, dict)]
    if bad:
        raise ValueError(f"items {bad} are not objects")
    return data


def _fmt_validation(exc: ValidationError) -> list[str]:
    out = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e["loc"]) or "<root>"
        out.append(f"{loc}: {e['msg']}")
    return out[:12]


def build_items(raw: list[dict]) -> list[ImportItem]:
    items = []
    for i, d in enumerate(raw):
        item = ImportItem(index=i)
        try:
            if {"public", "private", "evaluator"} <= set(d):
                item.kind = "scenario"
                item.scenario = Scenario.model_validate(d)
            else:
                item.kind = "brief"
                item.scenario = compile_brief(CaseBrief.model_validate(d))
            item.case_id = item.scenario.public.case_id
            item.warnings = check_scenario(item.scenario)
        except ValidationError as exc:
            item.errors = _fmt_validation(exc)
        except Exception as exc:  # pragma: no cover - defensive
            item.errors = [f"{type(exc).__name__}: {str(exc)[:200]}"]
        items.append(item)
    seen: dict[str, int] = {}
    for it in items:
        if it.case_id:
            if it.case_id in seen:
                it.errors.append(f"case_id {it.case_id} appears twice in the upload (items {seen[it.case_id]} and {it.index})")
            seen.setdefault(it.case_id, it.index)
    return items


def brief_from_scenario(s: Scenario) -> dict:
    """The reverse of compile_brief, for exporting an existing case as an editable starting point."""
    pr, ev, p = s.private, s.evaluator, s.public
    scripts = {t.topic: t for t in pr.topics}
    return {
        "case_id": p.case_id, "family_id": p.family_id, "title": p.title, "role": pr.role.value, "split": s.split,
        "difficulty": p.difficulty, "objective": p.objective, "context": p.context, "known_timeline": p.known_timeline,
        "interview_context": p.interview_context, "initial_question": p.initial_question, "max_turns": p.max_turns,
        "initial_documents": [{"id": e.id, "title": e.title, "content": e.content, "release_after_turn": e.release_after_turn,
                               "contradicts": e.conflicts_with_keywords} for e in p.initial_documents],
        "subject": {"name": pr.persona_name, "position": pr.persona_position, "communication_style": pr.communication_style,
                    "known_facts": pr.known_facts, "may_disclose": pr.may_disclose, "must_not_disclose": pr.must_not_disclose,
                    "uncertainty_notes": pr.uncertainty_notes, "objective": pr.objective},
        "topics": [{"topic": t, "question": p.question_bank.get(t, ""), "keywords": p.topic_keywords.get(t, []),
                    "truthful_answer": scripts[t].truthful_answer if t in scripts else "",
                    "deceptive_answer": scripts[t].deceptive_answer if t in scripts else None,
                    "tactic": scripts[t].deceptive_tactic.value if t in scripts else "omission",
                    "sensitive": scripts[t].sensitive if t in scripts else False,
                    "uncertain": scripts[t].uncertain_truthful if t in scripts else False} for t in p.key_topics],
        "evidence_release": [{"id": e.id, "title": e.title, "content": e.content, "release_after_turn": e.release_after_turn,
                              "contradicts": e.conflicts_with_keywords} for e in ev.evidence_release],
        "violation": ev.violation, "canonical_facts": ev.canonical_facts, "material_contradictions": ev.material_contradictions,
        "resolution_criteria": ev.resolution_criteria, "version": s.version,
    }


# ---------------------------------------------------------------------------
# Template handed to use-case providers
# ---------------------------------------------------------------------------
TEMPLATE_YAML = """# Investigative AI Training Arena - case brief
# One file can hold one case or a list of cases (put them under `cases:`). JSON works the same way.
# Best practice: upload a matched PAIR (same title/family, one truthful and one deceptive variant) so the
# role can never be guessed from the story alone. Everything marked (optional) can be left out.
cases:
  - title: Vendor gift disclosure
    role: deceptive                  # truthful | deceptive  (what the simulated subject really is)
    family_id: fam_vendor_gift       # (optional) cases sharing a family are a matched pair
    case_id: case_vendor_gift_d      # (optional) unique id; generated from the title and role if omitted
    split: hidden                    # hidden = used in bake-offs by default; development = practice only
    difficulty: medium               # low | medium | high
    objective: Determine whether procurement analyst Casey Morgan disclosed the hospitality received from Brightline Supplies before scoring its bid.
    context: >
      Brightline Supplies won a 2.1 million dollar contract on 18 June. The scoring panel included Casey Morgan.
      A later audit found a Brightline hospitality invoice for a two-night hotel stay in Casey's name dated 3 June.
      Policy requires any gift over 50 dollars to be declared before scoring.
    known_timeline:
      - "3 Jun - Brightline hospitality invoice: hotel stay, C. Morgan"
      - "11 Jun - Bid scoring panel meets; C. Morgan scores Brightline highest"
      - "18 Jun - Contract awarded to Brightline"
      - "2 Jul - Internal audit flags the invoice"
    interview_context: Voluntary interview. Subject has been told the topic is the Brightline award.   # (optional)
    initial_question: Can you tell me about your involvement in the Brightline bid evaluation?
    max_turns: 12                    # (optional) exchange budget
    initial_documents:               # records the investigator holds from the start
      - title: Gift and hospitality register extract
        content: "No entries for C. Morgan in 2026."
    subject:
      name: Casey Morgan
      position: Procurement analyst
      communication_style: calm, articulate and slightly impatient; answers in full sentences
      known_facts:                   # the fixed truth the subject knows (never changes)
        - Accepted a two-night hotel stay from Brightline on 3 June during a site visit.
        - Did not declare the stay on the hospitality register.
        - Scored Brightline highest on the 11 June panel.
      may_disclose:                  # (optional)
        - that a site visit to Brightline took place
        - the scoring process in general terms
      must_not_disclose:             # deceptive cases: phrases the subject must never say
        - hotel stay
        - Brightline paid
      uncertainty_notes: []          # (optional) things the subject genuinely does not recall
    topics:                          # lines of questioning; the coach suggests `question` when a topic is untouched
      - topic: site_visit
        question: What happened during your site visit to Brightline in June?
        truthful_answer: I visited their depot on 3 June and stayed two nights in a hotel that Brightline paid for.
        deceptive_answer: It was a standard site visit, a walk round the depot and a look at their systems. Nothing unusual.
        tactic: omission             # omission | deflection | minimisation | contradiction
      - topic: hospitality
        question: What hospitality or gifts did you receive from Brightline?
        truthful_answer: They covered my hotel for two nights.
        deceptive_answer: Coffee and a sandwich at the depot, which is hardly worth declaring.
        tactic: minimisation
      - topic: register
        question: What did you record on the gift and hospitality register?
        truthful_answer: Nothing. I never entered the hotel stay.
        deceptive_answer: There was nothing to record. I'd have put anything over the limit on there.
        tactic: contradiction
      - topic: scoring
        question: How did you arrive at your scores on the 11 June panel?
        truthful_answer: I scored against the published criteria; Brightline was strongest on delivery capacity.
        # no deceptive_answer: the subject answers this one truthfully in both variants
      - topic: expenses
        question: Which expenses did you claim for the June site visit?
        truthful_answer: Only mileage. The accommodation was not on my claim because Brightline covered it.
        deceptive_answer: Just mileage, it was a day trip as far as my claim goes.
        tactic: omission
    evidence_release:                # records released on a script as the interview proceeds
      - title: Brightline hospitality invoice
        content: "Invoice BL-2291, 3-5 Jun, Harbour Hotel, two nights, guest C. Morgan, billed to Brightline Supplies."
        release_after_turn: 2
        contradicts: [day trip, coffee and a sandwich]   # phrases in the subject's answers this record conflicts with
      - title: Expense claim
        content: "C. Morgan, 3 Jun: mileage 84 miles. No accommodation claimed."
        release_after_turn: 4
    violation: Undeclared hospitality from a bidder before scoring its bid.   # deceptive cases only
    canonical_facts:                 # the ground truth shown in the debrief
      - Brightline paid for a two-night hotel stay for C. Morgan on 3-5 June.
      - The stay was never declared on the hospitality register.
      - C. Morgan scored Brightline highest on 11 June.
    material_contradictions:         # (optional) statements a deceptive subject makes that records disprove
      - Subject describes the site visit as a day trip; the invoice shows a two-night stay.
    resolution_criteria: Deceptive if the subject's account of the visit or hospitality conflicts with the invoice and is not reconciled.   # (optional)

  - title: Vendor gift disclosure
    role: truthful
    family_id: fam_vendor_gift
    case_id: case_vendor_gift_t
    split: hidden
    difficulty: medium
    objective: Determine whether procurement analyst Casey Morgan disclosed the hospitality received from Brightline Supplies before scoring its bid.
    context: >
      Brightline Supplies won a 2.1 million dollar contract on 18 June. The scoring panel included Casey Morgan.
      A later audit found a Brightline hospitality invoice for a two-night hotel stay in Casey's name dated 3 June.
      Policy requires any gift over 50 dollars to be declared before scoring.
    known_timeline:
      - "3 Jun - Brightline hospitality invoice: hotel stay, C. Morgan"
      - "11 Jun - Bid scoring panel meets; C. Morgan scores Brightline highest"
      - "18 Jun - Contract awarded to Brightline"
      - "2 Jul - Internal audit flags the invoice"
    initial_question: Can you tell me about your involvement in the Brightline bid evaluation?
    initial_documents:
      - title: Gift and hospitality register extract
        content: "No entries for C. Morgan in 2026."
    subject:
      name: Casey Morgan
      position: Procurement analyst
      communication_style: nervous and apologetic; short sentences; checks whether an answer was enough
      known_facts:
        - Visited the Brightline depot on 3 June; the hotel was booked and paid by the subject's own employer.
        - Brightline's invoice is an error; it was raised against the wrong client account.
        - Declared nothing because nothing was received.
        - Not sure whether the hotel booking went through the travel desk or a manager.
      uncertainty_notes:
        - Genuinely unsure who made the hotel booking.
    topics:
      - topic: site_visit
        question: What happened during your site visit to Brightline in June?
        truthful_answer: I went down on the third, walked the depot and stayed two nights because the second day was a systems demo.
      - topic: hospitality
        question: What hospitality or gifts did you receive from Brightline?
        truthful_answer: Nothing beyond coffee. Our side paid for the hotel. I'm sorry if the invoice says otherwise, I don't understand that.
      - topic: register
        question: What did you record on the gift and hospitality register?
        truthful_answer: Nothing, because I didn't receive anything.
      - topic: scoring
        question: How did you arrive at your scores on the 11 June panel?
        truthful_answer: Against the criteria sheet. Brightline had the best delivery capacity.
      - topic: expenses
        question: Which expenses did you claim for the June site visit?
        truthful_answer: Mileage and the hotel, I think the hotel went through the travel desk rather than my claim. I'm not certain.
        uncertain: true
    evidence_release:
      - title: Brightline hospitality invoice
        content: "Invoice BL-2291, 3-5 Jun, Harbour Hotel, two nights, guest C. Morgan. Audit note: raised against the wrong client account; credited 9 Jul."
        release_after_turn: 2
      - title: Travel desk booking
        content: "Booking TD-5510, Harbour Hotel 3-5 Jun, C. Morgan, cost centre PROC-02 (employer paid)."
        release_after_turn: 4
    canonical_facts:
      - The employer's travel desk booked and paid for the hotel.
      - Brightline's invoice was raised in error and later credited.
      - No gift or hospitality was received.
"""


def template(fmt: str = "yaml") -> str:
    if fmt == "json":
        return json.dumps(yaml.safe_load(TEMPLATE_YAML), indent=2)
    return TEMPLATE_YAML
