"""Neo4j evidence graph: parameter building and write plumbing, exercised with a recording fake driver."""
import pytest

from app.graph import GraphNotConfigured, GraphSync
from app.schemas import FinalFinding, Finding, Mode


class FakeResult(list):
    pass


class FakeSession:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.log.append((query.strip().split("\n")[0], params))
        return FakeResult()


class FakeDriver:
    def __init__(self):
        self.log = []
        self.closed = False

    def session(self, database=None):
        return FakeSession(self.log)

    def close(self):
        self.closed = True


def locked_session(loop, engine, case_id="case_A2"):
    s, sc = loop.start(Mode.practice, "jordan", case_id, "asst-mock-evidence-v1", "subj-mock-v1", 4)
    for q in [sc.public.initial_question, "Which work order covered the entry?", "What did you bring into the room?", "Who authorised it?"]:
        loop.step(s, sc, q)
    loop.commit(s, sc, FinalFinding(finding=Finding.deceptive, confidence=0.7, rationale="x"))
    return s, sc


def test_disabled_graph_is_a_silent_no_op(loop, engine):
    g = GraphSync(None)
    s, sc = locked_session(loop, engine)
    assert not g.enabled and g.sync_session(s, sc) is False and g.status()["configured"] is False
    with pytest.raises(GraphNotConfigured):
        g.insights()


def test_session_params_mirror_the_frontend_session_graph(loop, engine):
    s, sc = locked_session(loop, engine)
    p = GraphSync.session_params(s, sc)
    assert p["session_id"] == s.id and p["investigator"] == "jordan" and p["role"] == "deceptive" and p["correct"] is True
    assert [t["index"] for t in p["turns"]] == [1, 2, 3, 4] and len(p["edges"]) == 3
    assert all(t["id"].startswith(s.id + "#") for t in p["turns"])
    assert set(p["topics"]) == set(sc.public.key_topics)
    assert any(t["topics"] for t in p["turns"])  # harness questions hit the public topic keywords
    released = {rid for t in p["turns"] for rid in t["released"]}
    assert released and all(rid.startswith("case_A2:") for rid in released)  # record ids are namespaced per case
    for f in p["flags"]:
        assert f["cites"] in {t["id"] for t in p["turns"]} and isinstance(f["supported"], bool)


def test_sync_session_writes_nodes_edges_and_flags(loop, engine):
    drv = FakeDriver()
    g = GraphSync("bolt://fake", driver=drv)
    s, sc = locked_session(loop, engine)
    assert g.sync_session(s, sc) is True and g.synced == 1
    heads = [h for h, _ in drv.log]
    assert heads[0].startswith("MERGE (i:Investigator") and "UNWIND $edges AS e" in heads
    assert drv.log[0][1]["case_id"] == "case_A2"
    assert g.sync_all([s], engine.lock) == 1
    g.close()
    assert drv.closed


def test_graph_endpoints_report_not_configured():
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(provider="mock", neo4j_uri=None)  # independent of any Neo4j configured in .env
    client = TestClient(create_app(settings, persist=False))
    tok = client.post("/api/auth/login", json={"username": settings.admin_user, "password": settings.admin_password}).json()["token"]
    client.headers["Authorization"] = f"Bearer {tok}"
    assert client.get("/api/graph/status").json()["configured"] is False
    assert client.get("/api/graph/insights").status_code == 503
    assert client.get("/api/graph/sessions").status_code == 503
    assert client.post("/api/graph/rebuild").status_code == 503
