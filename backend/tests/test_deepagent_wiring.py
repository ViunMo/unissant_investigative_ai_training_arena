"""Exercises the deepagents runtimes with a fake chat model (no API key needed)."""
import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.agents.context import SubjectContext, TranscriptEntry
from app.agents.llm import DeepAgentAssistant, DeepAgentSubject
from app.loops.interview_loop import build_assistant_context
from app.schemas import CandidateSpec, Finding, Turn


class FakeToolModel(GenericFakeChatModel):
    bound: list = []

    def bind_tools(self, tools, **kw):
        type(self).bound = [getattr(t, "name", None) or t.get("name") for t in tools]
        return self


COACH_JSON = json.dumps({
    "flags": [{"turn_index": 1, "kind": "possible_evasion", "evidence_quote": "busy shift", "issue": "purpose unanswered"}],
    "question_quality": 3, "question_feedback": "ok", "suggested_follow_up": "What task required entry?",
    "interim_finding": "insufficient_evidence", "confidence": 0.4, "rationale": "one deflection",
})


def test_assistant_runtime_parses_coaching_and_strips_filesystem_tools(engine):
    spec = CandidateSpec(id="x", kind="assistant", label="x", version="1", model="claude-opus-5-5", prompt_version="v1",
                         runtime="deepagents", policy={"rubric_loop": False})
    model = FakeToolModel(messages=iter([AIMessage(content=COACH_JSON)]))
    s = engine.lock("case_A2")
    ctx = build_assistant_context(s, [Turn(index=1, question="Why did you enter?", answer="busy shift")], s.public.initial_documents, {})
    coaching = DeepAgentAssistant(spec, model).coach(ctx)
    assert coaching.flags[0].turn_index == 1 and coaching.interim_finding == Finding.insufficient_evidence
    assert set(FakeToolModel.bound) == {"lookup_turn", "list_released_evidence", "get_case_packet"}
    assert ctx.audit and "Why did you enter?" in ctx.audit[0]


def test_assistant_runtime_retries_bad_json(engine):
    spec = CandidateSpec(id="x", kind="assistant", label="x", version="1", model="claude-opus-5-5", prompt_version="v1", runtime="deepagents")
    model = FakeToolModel(messages=iter([AIMessage(content="I think the subject is evasive."), AIMessage(content=COACH_JSON)]))
    s = engine.lock("case_A2")
    ctx = build_assistant_context(s, [Turn(index=1, question="Why?", answer="busy")], [], {})
    assert DeepAgentAssistant(spec, model).coach(ctx).confidence == 0.4


def test_subject_runtime_builds_private_prompt_and_checks_compliance(engine):
    spec = CandidateSpec(id="s", kind="subject", label="s", version="1", model="claude-opus-5-5", prompt_version="v1", runtime="deepagents")
    s = engine.lock("case_A2")
    ctx = SubjectContext(public=s.public, private=s.private, transcript=[TranscriptEntry(1, "Why?", "Busy shift.")],
                         question="What did you bring in?", turn_index=2)
    runtime = DeepAgentSubject(spec, FakeToolModel(messages=iter([AIMessage(content='{"reply": "Just my laptop.", "tactic": "omission", "facts_used": ["equipment"]}')])))
    prompt = runtime._system(ctx)
    assert "Jordan Lee" in prompt and "polished" in prompt and "personal USB drive" in prompt
    reply = runtime.answer(ctx)
    assert reply.tactic.value == "omission" and reply.compliant
    leaky = DeepAgentSubject(spec, FakeToolModel(messages=iter([AIMessage(content='{"reply": "I copied the configuration backup to my personal USB drive.", "tactic": "truthful"}')])))
    assert not leaky.answer(ctx).compliant
