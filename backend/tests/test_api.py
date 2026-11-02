import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app(Settings(provider="mock"), persist=False))


def test_health_and_catalogue_hide_private_data(client):
    assert client.get("/api/health").json()["provider"] == "mock"
    cases = client.get("/api/scenarios").json()
    assert len(cases) == 6
    blob = str(cases).lower()
    assert "deceptive" not in blob and "personal usb drive" not in blob and "birthday" not in blob and "tr-0099" not in blob
    cands = client.get("/api/candidates?kind=assistant").json()
    assert any(c["effective_runtime"].startswith("mock (fallback") for c in cands if c["runtime"] == "deepagents")


def test_assessment_mode_hides_coaching_until_lock(client):
    s = client.post("/api/sessions", json={"investigator": "i", "mode": "assessment", "case_id": "case_A1",
                                           "assistant_id": "asst-mock-evidence-v1", "subject_id": "subj-mock-v1", "max_turns": 3}).json()
    a = client.post(f"/api/sessions/{s['id']}/ask", json={"question": "Why did you enter the server room?"}).json()
    assert a["turn"]["coaching"] is None and "tactic" not in a["turn"]
    assert client.get(f"/api/sessions/{s['id']}").json()["assistant_final"] is None
    client.post(f"/api/sessions/{s['id']}/ask", json={"question": "Which work order?"})
    client.post(f"/api/sessions/{s['id']}/ask", json={"question": "What time did you leave?"})
    assert client.post(f"/api/sessions/{s['id']}/ask", json={"question": "again"}).status_code == 400
    f = client.post(f"/api/sessions/{s['id']}/finding", json={"finding": "truthful", "confidence": 0.6, "rationale": "x"}).json()
    assert f["status"] == "locked" and f["debrief"]["ground_truth_role"] == "truthful"
    assert f["turns"][0]["coaching"] is not None and f["turns"][0]["tactic"] == "truthful"
    r = client.post(f"/api/sessions/{s['id']}/trainer-rating", json={"clarity_neutrality": 4, "response_relevance": 3,
                    "evidence_based_follow_up": 3, "alternative_explanations": 2, "supported_closure": 4})
    assert r.status_code == 200
    p = client.get("/api/investigators/i/progress").json()
    assert p["sessions"] == 1 and p["history"][0]["trainer_score"] == 80


def test_bakeoff_endpoint_runs_in_background(client):
    b = client.post("/api/bakeoffs", json={"assistant_ids": ["asst-mock-evidence-v1"], "subject_ids": ["subj-mock-v1"],
                                           "case_ids": ["case_B1", "case_B2"], "tracks": ["interactive"], "max_turns": 6})
    assert b.status_code == 202
    for _ in range(100):
        st = client.get(f"/api/bakeoffs/{b.json()['id']}").json()
        if st["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert st["status"] == "completed", st.get("error")
    assert st["assistant_leaderboard"][0]["trials"] == 2
    assert "results" not in st
    assert len(client.get(f"/api/bakeoffs/{b.json()['id']}?include_results=true").json()["results"]) == 2
    assert client.post("/api/bakeoffs", json={"assistant_ids": ["nope"], "subject_ids": ["subj-mock-v1"]}).status_code == 404
