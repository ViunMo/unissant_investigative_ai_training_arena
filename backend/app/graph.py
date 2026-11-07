"""Optional Neo4j evidence graph.

The JSON store stays the system of record. When `ARENA_NEO4J_URI` is set, every locked session is also written to
Neo4j as the same nodes and relationships the Overview page draws for one session, so questions that span sessions
(which records get contradicted, which lines of questioning are skipped on deceptive cases, how often an assistant's
flags cite a turn that was actually evasive, how an investigator's questioning path changes) become Cypher queries.
Without a URI every method is a no-op and the app behaves exactly as before.

Model:
  (Investigator)-[:CONDUCTED]->(Session)-[:ON_CASE]->(Case)-[:HAS_RECORD]->(Record)
  (Session)-[:COACHED_BY]->(Candidate)   (Session)-[:INTERVIEWED]->(Candidate)
  (Session)-[:HAS_TURN]->(Turn)-[:NEXT]->(Turn)   (Turn)-[:COVERS]->(Topic)   (Turn)-[:RELEASED]->(Record)
  (Session)-[:RAISED]->(Flag)-[:CITES]->(Turn)   (Flag)-[:CONTRADICTS]->(Record)   (Case)-[:HAS_TOPIC]->(Topic)
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from app.agents.context import detect_topics
from app.schemas import Scenario, Session

logger = logging.getLogger(__name__)

EVASIVE = {"omission", "deflection", "minimisation", "contradiction"}

SCHEMA = [
    "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT case_id IF NOT EXISTS FOR (c:Case) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT investigator_name IF NOT EXISTS FOR (i:Investigator) REQUIRE i.name IS UNIQUE",
    "CREATE CONSTRAINT candidate_id IF NOT EXISTS FOR (c:Candidate) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT turn_id IF NOT EXISTS FOR (t:Turn) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT record_id IF NOT EXISTS FOR (r:Record) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT flag_id IF NOT EXISTS FOR (f:Flag) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
]

WRITE_SESSION = """
MERGE (i:Investigator {name: $investigator})
MERGE (c:Case {id: $case_id}) SET c.title = $case_title, c.family = $family
MERGE (a:Candidate {id: $assistant_id}) SET a.kind = 'assistant'
MERGE (sub:Candidate {id: $subject_id}) SET sub.kind = 'subject'
MERGE (s:Session {id: $session_id})
SET s.mode = $mode, s.locked_at = $locked_at, s.finding = $finding, s.correct = $correct, s.role = $role,
    s.score = $score, s.assistant_finding = $assistant_finding, s.assistant_correct = $assistant_correct,
    s.turns = $n_turns, s.investigator = $investigator, s.case_id = $case_id
MERGE (i)-[:CONDUCTED]->(s)
MERGE (s)-[:ON_CASE]->(c)
MERGE (s)-[:COACHED_BY]->(a)
MERGE (s)-[:INTERVIEWED]->(sub)
WITH s, c
FOREACH (name IN $topics | MERGE (tp:Topic {name: name}) MERGE (c)-[:HAS_TOPIC]->(tp))
FOREACH (r IN $records | MERGE (rec:Record {id: r.id}) SET rec.code = r.code, rec.title = r.title, rec.content = r.content, rec.case_id = $case_id
                         MERGE (c)-[:HAS_RECORD]->(rec))
FOREACH (t IN $turns | MERGE (tn:Turn {id: t.id})
                       SET tn.index = t.index, tn.question = t.question, tn.answer = t.answer, tn.tactic = t.tactic,
                           tn.evasive = t.evasive, tn.quality = t.quality, tn.session_id = $session_id
                       MERGE (s)-[:HAS_TURN]->(tn)
                       FOREACH (name IN t.topics | MERGE (tp:Topic {name: name}) MERGE (tn)-[:COVERS]->(tp))
                       FOREACH (rid IN t.released | MERGE (rec:Record {id: rid}) MERGE (tn)-[:RELEASED]->(rec)))
"""

WRITE_EDGES = """
UNWIND $edges AS e
MATCH (a:Turn {id: e.src}), (b:Turn {id: e.dst})
MERGE (a)-[:NEXT]->(b)
"""

WRITE_FLAGS = """
MATCH (s:Session {id: $session_id})
UNWIND $flags AS f
MERGE (fl:Flag {id: f.id})
SET fl.kind = f.kind, fl.issue = f.issue, fl.quote = f.quote, fl.supported = f.supported, fl.turn = f.turn_index
MERGE (s)-[:RAISED]->(fl)
WITH fl, f
MATCH (tn:Turn {id: f.cites})
MERGE (fl)-[:CITES]->(tn)
FOREACH (rid IN f.records | MERGE (rec:Record {id: rid}) MERGE (fl)-[:CONTRADICTS]->(rec))
"""

Q_CONTRADICTED = """
MATCH (f:Flag {kind: 'contradiction'})-[:CONTRADICTS]->(r:Record)
RETURN r.case_id AS case_id, r.code AS record, r.title AS title, count(DISTINCT f) AS flags
ORDER BY flags DESC, case_id, record LIMIT 10
"""

Q_SKIPPED = """
MATCH (s:Session)-[:ON_CASE]->(c:Case)-[:HAS_TOPIC]->(tp:Topic)
WHERE s.role IS NOT NULL AND NOT EXISTS { MATCH (s)-[:HAS_TURN]->(:Turn)-[:COVERS]->(tp) }
WITH s.role AS role, tp.name AS topic, count(DISTINCT s) AS skipped
MATCH (all:Session) WHERE all.role = role
WITH role, topic, skipped, count(DISTINCT all) AS sessions
RETURN role, topic, skipped, sessions, toFloat(skipped) / sessions AS rate
ORDER BY rate DESC, skipped DESC, topic LIMIT 10
"""

Q_FLAG_PRECISION = """
MATCH (s:Session)-[:COACHED_BY]->(a:Candidate)
OPTIONAL MATCH (s)-[:RAISED]->(f:Flag)
WITH a.id AS assistant_id, count(DISTINCT s) AS sessions, count(f) AS flags,
     sum(CASE WHEN f.supported THEN 1 ELSE 0 END) AS supported
RETURN assistant_id, sessions, flags, supported,
       CASE WHEN flags = 0 THEN null ELSE toFloat(supported) / flags END AS precision
ORDER BY sessions DESC, assistant_id
"""

Q_INVESTIGATORS = """
MATCH (i:Investigator)-[:CONDUCTED]->(s:Session)
OPTIONAL MATCH (s)-[:HAS_TURN]->(:Turn)-[:COVERS]->(tp:Topic)
WITH i, s, collect(DISTINCT tp.name) AS topics
ORDER BY s.locked_at
WITH i, collect({id: s.id, case_id: s.case_id, locked_at: s.locked_at, correct: s.correct, score: s.score, topics: topics}) AS sessions
RETURN i.name AS investigator, size(sessions) AS sessions,
       sessions[0].score AS first_score, sessions[-1].score AS latest_score, sessions AS history
ORDER BY sessions DESC, investigator
"""

Q_COUNTS = """
CALL () { MATCH (s:Session) RETURN count(s) AS sessions }
CALL () { MATCH (t:Turn) RETURN count(t) AS turns }
CALL () { MATCH (f:Flag) RETURN count(f) AS flags }
CALL () { MATCH (r:Record) RETURN count(r) AS records }
CALL () { MATCH (i:Investigator) RETURN count(i) AS investigators }
RETURN sessions, turns, flags, records, investigators
"""

Q_NETWORK = """
MATCH (i:Investigator)-[:CONDUCTED]->(s:Session)-[:ON_CASE]->(c:Case)
WHERE $investigator IS NULL OR i.name = $investigator
OPTIONAL MATCH (s)-[:HAS_TURN]->(:Turn)-[:COVERS]->(tp:Topic)
OPTIONAL MATCH (s)-[:RAISED]->(f:Flag {kind: 'contradiction'})-[:CONTRADICTS]->(r:Record)
WITH i, s, c, collect(DISTINCT tp.name) AS topics, collect(DISTINCT {id: r.id, code: r.code, title: r.title}) AS records
RETURN i.name AS investigator, s.id AS session_id, s.correct AS correct, s.finding AS finding, s.role AS role,
       s.score AS score, s.locked_at AS locked_at, c.id AS case_id, c.title AS case_title, topics, records
ORDER BY s.locked_at DESC LIMIT $limit
"""


class GraphNotConfigured(RuntimeError):
    pass


class GraphSync:
    def __init__(self, uri: str | None, user: str = "neo4j", password: str | None = None, database: str = "neo4j",
                 driver: Any | None = None) -> None:
        self.uri, self.user, self.password, self.database = uri or None, user, password, database
        self._driver = driver
        self._lock = threading.Lock()
        self._schema_done = driver is not None
        self.error: str | None = None
        self.synced = 0

    # ----- connection ------------------------------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.uri) or self._driver is not None

    def _get_driver(self):
        if not self.enabled:
            raise GraphNotConfigured("Neo4j is not configured: set ARENA_NEO4J_URI (and ARENA_NEO4J_PASSWORD) in backend/.env")
        with self._lock:
            if self._driver is None:
                from neo4j import GraphDatabase

                self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password or ""))
            if not self._schema_done:
                with self._driver.session(database=self.database) as sess:
                    for stmt in SCHEMA:
                        sess.run(stmt)
                self._schema_done = True
        return self._driver

    def _run(self, query: str, **params) -> list[dict]:
        driver = self._get_driver()
        with driver.session(database=self.database) as sess:
            return [dict(rec) for rec in sess.run(query, **params)]

    def status(self) -> dict:
        if not self.enabled:
            return {"configured": False, "connected": False, "uri": None, "error": None, "synced": 0}
        try:
            counts = self._run(Q_COUNTS)
            self.error = None
            return {"configured": True, "connected": True, "uri": self.uri, "error": None, "synced": self.synced,
                    "counts": counts[0] if counts else {}}
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {str(exc)[:200]}"
            return {"configured": True, "connected": False, "uri": self.uri, "error": self.error, "synced": self.synced}

    def close(self) -> None:
        if self._driver is not None and hasattr(self._driver, "close"):
            try:
                self._driver.close()
            except Exception:
                pass

    # ----- writes ----------------------------------------------------------------------------------------------
    @staticmethod
    def session_params(session: Session, scenario: Scenario) -> dict:
        """Everything the graph stores for one locked session. Only data the debrief already reveals is included."""
        public = scenario.public
        rec_id = lambda code: f"{session.case_id}:{code}"  # noqa: E731  record codes repeat across case variants
        records = [{"id": rec_id(e.id), "code": e.id, "title": e.title, "content": e.content} for e in session.released_evidence]
        by_title = {e.title.lower(): rec_id(e.id) for e in session.released_evidence}
        by_code = {e.id.lower(): rec_id(e.id) for e in session.released_evidence}
        turns, flags, edges = [], [], []
        tactic_of = {t.index: (t.tactic.value if t.tactic else None) for t in session.turns}
        for t in session.turns:
            tid = f"{session.id}#{t.index}"
            turns.append({
                "id": tid, "index": t.index, "question": t.question, "answer": t.answer,
                "tactic": tactic_of[t.index], "evasive": tactic_of[t.index] in EVASIVE,
                "quality": t.coaching.question_quality if t.coaching else None,
                "topics": detect_topics(t.question, public.topic_keywords),
                "released": [rec_id(e.id) for e in t.evidence_released],
            })
            if t.index > 1:
                edges.append({"src": f"{session.id}#{t.index - 1}", "dst": tid})
            for j, f in enumerate(t.coaching.flags if t.coaching else []):
                text = f"{f.issue} {f.evidence_quote}".lower()
                recs = sorted({rid for key, rid in list(by_code.items()) + list(by_title.items()) if key and key in text}) if f.kind.value == "contradiction" else []
                flags.append({
                    "id": f"{tid}/f{j}", "kind": f.kind.value, "issue": f.issue, "quote": f.evidence_quote,
                    "turn_index": f.turn_index, "cites": f"{session.id}#{f.turn_index}",
                    "supported": tactic_of.get(f.turn_index) in EVASIVE, "records": recs,
                })
        d = session.debrief
        return {
            "investigator": session.investigator, "session_id": session.id, "case_id": session.case_id,
            "case_title": public.title, "family": getattr(scenario, "family_id", None) or getattr(public, "family_id", None),
            "assistant_id": session.assistant_id, "subject_id": session.subject_id, "mode": session.mode.value,
            "locked_at": session.locked_at, "n_turns": len(session.turns),
            "finding": session.final_finding.finding.value if session.final_finding else None,
            "correct": d.investigator_correct if d else None, "role": d.ground_truth_role.value if d else None,
            "score": d.investigator_auto_score if d else None,
            "assistant_finding": session.assistant_final.finding.value if session.assistant_final else None,
            "assistant_correct": d.assistant_correct if d else None,
            "topics": list(public.key_topics), "records": records, "turns": turns, "edges": edges, "flags": flags,
        }

    def sync_session(self, session: Session, scenario: Scenario) -> bool:
        """Write one locked session; returns False (and logs) when the graph is off or unreachable."""
        if not self.enabled or session.status != "locked":
            return False
        params = self.session_params(session, scenario)
        try:
            driver = self._get_driver()
            with driver.session(database=self.database) as sess:
                sess.run(WRITE_SESSION, **params)
                if params["edges"]:
                    sess.run(WRITE_EDGES, edges=params["edges"])
                if params["flags"]:
                    sess.run(WRITE_FLAGS, session_id=params["session_id"], flags=params["flags"])
            self.synced += 1
            self.error = None
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.warning("neo4j sync failed for %s: %s", session.id, self.error)
            return False

    def sync_all(self, sessions: list[Session], lock_scenario) -> int:
        return sum(1 for s in sessions if s.status == "locked" and self.sync_session(s, lock_scenario(s.case_id)))

    # ----- reads -----------------------------------------------------------------------------------------------
    def insights(self) -> dict:
        return {
            "counts": (self._run(Q_COUNTS) or [{}])[0],
            "contradicted_records": self._run(Q_CONTRADICTED),
            "skipped_topics": self._run(Q_SKIPPED),
            "flag_precision": self._run(Q_FLAG_PRECISION),
            "investigators": self._run(Q_INVESTIGATORS),
        }

    def network(self, investigator: str | None = None, limit: int = 60) -> dict:
        """Cross-session graph in the frontend's node/link format."""
        rows = self._run(Q_NETWORK, investigator=investigator, limit=limit)
        nodes: dict[str, dict] = {}
        links: list[dict] = []

        def node(nid: str, **props) -> None:
            if nid not in nodes:
                nodes[nid] = {"id": nid, **props}

        for r in rows:
            inv, sid, cid = f"inv:{r['investigator']}", f"sess:{r['session_id']}", f"case:{r['case_id']}"
            node(inv, label=r["investigator"], group="actor", size=18)
            verdict = "correct" if r["correct"] else "wrong" if r["correct"] is not None else "open"
            node(sid, label=f"{r['session_id']} · {verdict}", group="finding", size=12,
                 title=f"{r['finding'] or 'no finding'} · truth {r['role'] or '?'} · score {r['score'] if r['score'] is not None else 'n/a'}")
            node(cid, label=r["case_title"] or r["case_id"], group="scenario", size=16, title=r["case_id"])
            links.append({"source": inv, "target": sid, "label": "conducted", "distance": 70})
            links.append({"source": sid, "target": cid, "label": r["role"] or "", "distance": 90})
            for tp in r["topics"] or []:
                node(f"topic:{tp}", label=tp.replace("_", " "), group="topic", size=11)
                links.append({"source": sid, "target": f"topic:{tp}", "label": "covered", "distance": 110})
            for rec in r["records"] or []:
                if not rec.get("id"):
                    continue
                node(f"rec:{rec['id']}", label=f"{rec['title']} ({rec['code']})", group="contradiction", size=11)
                links.append({"source": sid, "target": f"rec:{rec['id']}", "label": "contradiction", "color": "#d55181", "dashed": True})
        return {"nodes": list(nodes.values()), "links": links, "sessions": len(rows)}
