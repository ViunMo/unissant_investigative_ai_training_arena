"""Bringing your own cases: brief compilation, upload validation, persistence, and running a session on one."""
import json
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agents.context import detect_topics
from app.config import Settings
from app.main import create_app
from app.scenarios import authoring
from app.scenarios.authoring import CaseBrief, build_items, check_scenario, compile_brief, parse_document, template
from app.scenarios.drafting import draft_cases
from app.scenarios.engine import ScenarioEngine
from app.schemas import Role, Scenario, Tactic
from tests.test_api import signed_in


def briefs() -> list[dict]:
    return yaml.safe_load(template("yaml"))["cases"]


# ---------------------------------------------------------------------------
# compile_brief
# ---------------------------------------------------------------------------
def test_template_compiles_into_a_matched_pair_without_warnings():
    items = build_items(parse_document(template("yaml"), "t.yaml"))
    assert [it.errors for it in items] == [[], []]
    assert [it.warnings for it in items] == [[], []]
    d, t = items[0].scenario, items[1].scenario
    assert d.private.role == Role.deceptive and t.private.role == Role.truthful
    assert d.public.family_id == t.public.family_id
    assert d.public.key_topics == t.public.key_topics
    assert d.evaluator.violation and t.evaluator.violation is None
    assert all(ts.deceptive_answer is None for ts in t.private.topics)
    assert sum(1 for ts in d.private.topics if ts.sensitive and ts.deceptive_answer) == 4
    assert "if concealing, you may say" in d.evaluator.isolation_canaries and "ROLE=deceptive" in d.evaluator.isolation_canaries
    assert d.evaluator.evidence_release[0].conflicts_with_keywords == ["day trip", "coffee and a sandwich"]
    assert d.evaluator.evidence_release[0].id == "CASEVE-E1"  # ids are generated after the initial records


def test_json_template_matches_yaml_template():
    assert json.loads(template("json")) == yaml.safe_load(template("yaml"))


def test_derived_keywords_make_each_bank_question_detect_its_own_topic():
    sc = compile_brief(CaseBrief.model_validate(briefs()[0]))
    for topic, q in sc.public.question_bank.items():
        assert detect_topics(q, sc.public.topic_keywords)[0] == topic
    # words shared by several questions are not credited to any one topic
    assert "june" not in sum(sc.public.topic_keywords.values(), [])


def test_defaults_ids_objectives_and_behaviours():
    raw = briefs()[1]
    for k in ("case_id", "family_id", "split", "difficulty", "interview_context", "max_turns"):
        raw.pop(k, None)
    sc = compile_brief(CaseBrief.model_validate(raw))
    assert sc.public.case_id == "case_vendor_gift_disclosure_t" and sc.public.family_id == "fam_vendor_gift_disclosure"
    assert sc.split == "hidden" and sc.public.difficulty == "medium" and sc.public.max_turns == 12
    assert sc.private.objective == authoring.TRUTHFUL_OBJECTIVE
    assert sc.private.permitted_behaviors == [Tactic.truthful, Tactic.uncertain]
    assert sc.private.must_not_disclose == ["anything the subject does not actually know"]
    assert sc.private.topics[4].uncertain_truthful is True
    dec = compile_brief(CaseBrief.model_validate({**briefs()[0], "subject": {**briefs()[0]["subject"], "objective": None}}))
    assert "undiscovered" in dec.private.objective and dec.private.objective in dec.evaluator.isolation_canaries
    assert Tactic.deflection in dec.private.permitted_behaviors


def test_check_scenario_flags_structural_problems():
    raw = briefs()[0]
    raw["violation"] = None
    raw["subject"]["must_not_disclose"] = []
    for t in raw["topics"]:
        t.pop("deceptive_answer", None)
    raw["evidence_release"] = [{"title": "late", "content": "x", "release_after_turn": 30}]
    raw["max_turns"] = 12
    w = check_scenario(compile_brief(CaseBrief.model_validate(raw)))
    assert any("no violation" in x for x in w)
    assert any("no sensitive topic" in x for x in w)
    assert any("must_not_disclose" in x for x in w)
    assert any("never appear" in x for x in w)
    # an uploaded full scenario with a keyword collision is reported, not rejected
    sc = compile_brief(CaseBrief.model_validate(briefs()[1]))
    sc.public.topic_keywords["register"] = ["hospitality or gifts did you receive"]
    assert any("detected as" in x for x in check_scenario(sc))


def test_brief_export_round_trips_through_compile():
    sc = ScenarioEngine().lock("case_A2")
    again = compile_brief(CaseBrief.model_validate(authoring.brief_from_scenario(sc)))
    assert again.public == sc.public
    assert again.private.topics == sc.private.topics
    assert again.evaluator.evidence_release == sc.evaluator.evidence_release
    assert again.evaluator.violation == sc.evaluator.violation


# ---------------------------------------------------------------------------
# parsing and item errors
# ---------------------------------------------------------------------------
def test_parse_document_accepts_json_yaml_single_list_and_wrapper():
    one = briefs()[0]
    assert len(parse_document(json.dumps(one))) == 1
    assert len(parse_document(json.dumps([one, one]))) == 2
    assert len(parse_document(yaml.safe_dump({"cases": [one]}), "x.yml")) == 1
    with pytest.raises(ValueError):
        parse_document("   ")
    with pytest.raises(ValueError):
        parse_document("- just\n- a list\n- of strings")
    with pytest.raises(ValueError):
        parse_document("{{{ not json", "x.json")


def test_build_items_reports_per_item_errors_and_duplicates():
    one = briefs()[0]
    broken = {k: v for k, v in one.items() if k not in ("title", "topics")}
    items = build_items([one, broken, one])
    assert items[0].errors == []
    assert any(e.startswith("title") for e in items[1].errors) and any(e.startswith("topics") for e in items[1].errors)
    assert any("appears twice" in e for e in items[2].errors)
    full = ScenarioEngine().lock("case_A1").model_dump()
    full["public"]["case_id"] = "case_copy"
    it = build_items([full])[0]
    assert it.kind == "scenario" and it.errors == [] and it.case_id == "case_copy"


# ---------------------------------------------------------------------------
# engine persistence
# ---------------------------------------------------------------------------
def test_engine_persists_uploaded_cases_and_protects_builtins(tmp_path):
    e = ScenarioEngine(store_dir=tmp_path)
    sc = compile_brief(CaseBrief.model_validate(briefs()[0]))
    assert e.add(sc) == "case_vendor_gift_d"
    assert (tmp_path / "case_vendor_gift_d.json").exists()
    with pytest.raises(ValueError):
        e.add(sc)  # same id without replace
    e.add(sc, replace=True)
    builtin = e.lock("case_A1")
    with pytest.raises(ValueError):
        e.add(builtin, replace=True)
    with pytest.raises(ValueError):
        e.remove("case_A1")
    (tmp_path / "junk.json").write_text("{not a case}")
    e2 = ScenarioEngine(store_dir=tmp_path)  # a restart reloads the upload and skips junk
    assert e2.source("case_vendor_gift_d") == "uploaded" and e2.source("case_A1") == "builtin"
    assert "case_vendor_gift_d" in e2.case_ids("hidden")
    e2.remove("case_vendor_gift_d")
    assert not (tmp_path / "case_vendor_gift_d.json").exists()
    with pytest.raises(KeyError):
        e2.public("case_vendor_gift_d")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.fixture
def trainer():
    return signed_in(Settings(provider="mock"))


def test_import_is_trainer_only_and_validates_before_adding(trainer):
    c = TestClient(trainer.app)
    tok = c.post("/api/auth/register", json={"username": "inv", "password": "secret1"}).json()["token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    assert c.post("/api/scenarios/import", json={"content": template("yaml")}).status_code == 403
    assert c.get("/api/scenarios/template").status_code == 403
    assert c.delete("/api/scenarios/case_A1").status_code == 403

    t = trainer.get("/api/scenarios/template?format=json")
    assert t.status_code == 200 and json.loads(t.text)["cases"][0]["role"] == "deceptive"

    r = trainer.post("/api/scenarios/import", json={"content": template("yaml"), "filename": "t.yaml", "dry_run": True}).json()
    assert r["ok"] and r["dry_run"] and r["imported"] == [] and len(r["items"]) == 2
    assert r["items"][0]["role"] == "deceptive" and r["items"][0]["scenario"]["private"]["persona_name"] == "Casey Morgan"
    assert len(trainer.get("/api/scenarios").json()) == 6  # dry run adds nothing

    bad = yaml.safe_load(template("yaml"))
    del bad["cases"][1]["subject"]
    r = trainer.post("/api/scenarios/import", json={"content": json.dumps(bad)}).json()
    assert not r["ok"] and r["imported"] == [] and any(e.startswith("subject") for e in r["items"][1]["errors"])
    assert len(trainer.get("/api/scenarios").json()) == 6  # all-or-nothing: the valid sibling was not added either

    assert trainer.post("/api/scenarios/import", json={"content": "{{{ not a file"}).status_code == 400

    r = trainer.post("/api/scenarios/import", json={"content": template("yaml")}).json()
    assert r["ok"] and r["imported"] == ["case_vendor_gift_d", "case_vendor_gift_t"] and r["cases"] == 8
    cases = trainer.get("/api/scenarios").json()
    mine = [x for x in cases if x["source"] == "uploaded"]
    blob = str(mine).lower()
    assert len(mine) == 2 and "deceptive" not in blob and "role" not in blob and "brightline paid" not in blob  # public view only
    assert "canonical" not in blob and "must_not" not in blob and "harbour hotel" not in blob  # private and evaluator packets stay hidden

    again = trainer.post("/api/scenarios/import", json={"content": template("yaml")}).json()
    assert not again["ok"] and any("uploaded before" in e for e in again["items"][0]["errors"])
    assert trainer.post("/api/scenarios/import", json={"content": template("yaml"), "replace": True}).json()["ok"]

    clash = yaml.safe_load(template("yaml"))["cases"][0]
    clash["case_id"] = "case_A1"
    r = trainer.post("/api/scenarios/import", json={"content": json.dumps(clash), "replace": True}).json()
    assert not r["ok"] and any("built-in" in e for e in r["items"][0]["errors"])


def test_uploaded_case_runs_end_to_end_and_blocks_delete_while_in_use(trainer):
    assert trainer.post("/api/scenarios/import", json={"content": template("yaml")}).json()["ok"]
    s = trainer.post("/api/sessions", json={"investigator": "i", "case_id": "case_vendor_gift_d", "assistant_id": "asst-mock-evidence-v1",
                                            "subject_id": "subj-mock-v1", "max_turns": 4}).json()
    assert s["released_evidence"][0]["title"] == "Gift and hospitality register extract"
    a = trainer.post(f"/api/sessions/{s['id']}/ask", json={"question": "What hospitality or gifts did you receive from Brightline?"}).json()
    assert "coffee and a sandwich" in a["turn"]["answer"].lower()  # the concealing answer, keyed on the derived keywords
    a = trainer.post(f"/api/sessions/{s['id']}/ask", json={"question": "Which expenses did you claim for the June site visit?"}).json()
    assert [e["title"] for e in a["released_evidence"]][-1] == "Brightline hospitality invoice"  # scripted release after turn 2
    f = trainer.post(f"/api/sessions/{s['id']}/finding", json={"finding": "deceptive", "confidence": 0.7, "rationale": "invoice"}).json()
    assert f["status"] == "locked" and f["debrief"]["ground_truth_role"] == "deceptive" and f["debrief"]["investigator_correct"]
    assert f["debrief"]["violation"].startswith("Undeclared hospitality")
    assert f["turns"][0]["tactic"] == "minimisation"

    r = trainer.delete("/api/scenarios/case_vendor_gift_d")
    assert r.status_code == 409 and "referenced" in r.json()["detail"]
    assert trainer.delete("/api/scenarios/case_A1").status_code == 409
    assert trainer.delete("/api/scenarios/nope").status_code == 404
    assert trainer.delete("/api/scenarios/case_vendor_gift_t").json()["deleted"] == "case_vendor_gift_t"
    assert len(trainer.get("/api/scenarios").json()) == 7


def test_uploaded_hidden_cases_join_bakeoffs_by_default(trainer):
    assert trainer.post("/api/scenarios/import", json={"content": template("yaml")}).json()["ok"]
    b = trainer.post("/api/bakeoffs", json={"assistant_ids": ["asst-mock-evidence-v1"], "subject_ids": ["subj-mock-v1"],
                                            "tracks": ["interactive"], "max_turns": 4})
    assert b.status_code == 202
    for _ in range(200):
        st = trainer.get(f"/api/bakeoffs/{b.json()['id']}?include_results=true").json()
        if st["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert st["status"] == "completed", st.get("error")
    assert {r["case_id"] for r in st["results"]} >= {"case_vendor_gift_d", "case_vendor_gift_t"}
    assert any(r["family_id"] == "fam_vendor_gift" for r in st["results"])


def test_export_returns_the_full_case_as_a_brief(trainer):
    b = trainer.get("/api/scenarios/case_A2/export").json()
    assert b["role"] == "deceptive" and b["violation"] and b["topics"][0]["deceptive_answer"]
    assert trainer.get("/api/scenarios/case_A2/export?format=scenario").json()["evaluator"]["assigned_role"] == "deceptive"
    assert trainer.get("/api/scenarios/nope/export").status_code == 404
    # the export is a valid upload once the id changes
    b["case_id"], b["family_id"] = "case_A2_copy", "fam_copy"
    r = trainer.post("/api/scenarios/import", json={"content": json.dumps(b), "dry_run": True}).json()
    assert r["ok"] and r["items"][0]["warnings"] == []


# ---------------------------------------------------------------------------
# drafting with a (fake) model
# ---------------------------------------------------------------------------
def test_draft_cases_retries_until_valid_and_returns_editable_yaml():
    calls = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "```json\n{\"cases\": []}\n```"  # invalid: empty list
        return json.dumps({"cases": briefs()})

    out = draft_cases("A pharmacist signed out controlled drugs against a voided prescription.", ["truthful", "deceptive"], fake)
    assert out["retries"] == 1 and len(out["cases"]) == 2 and "previous reply was not valid" in calls[1]
    items = build_items(parse_document(out["yaml"], "d.yaml"))
    assert [it.errors for it in items] == [[], []]
    assert isinstance(Scenario.model_validate(items[0].scenario.model_dump()), Scenario)


def test_draft_endpoint_uses_injected_model_and_refuses_without_one(trainer):
    r = trainer.post("/api/scenarios/draft", json={"description": "A long enough description of an incident for the model."})
    assert r.status_code == 409  # mock provider: no hosted model
    trainer.app.state.draft_model = lambda prompt: json.dumps({"cases": briefs()[:1]})
    r = trainer.post("/api/scenarios/draft", json={"description": "A long enough description of an incident for the model.", "roles": ["deceptive"]})
    assert r.status_code == 200 and r.json()["cases"][0]["role"] == "deceptive" and "title: Vendor gift disclosure" in r.json()["yaml"]
    assert trainer.post("/api/scenarios/draft", json={"description": "short"}).status_code == 422
