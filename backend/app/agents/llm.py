"""deepagents runtimes for investigative assistants and simulated subjects.

Loops used here:
- L0 validation loop (`validated_call`): parse-validate-retry around every model call.
- L1 rubric loop (`RubricMiddleware`): the assistant self-evaluates its coaching against a
  rubric and revises before the result leaves the agent (when the candidate policy enables it).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.agents.context import AssistantContext, SubjectContext
from app.agents.profiles import ensure_profiles
from app.agents.prompts import (
    ASSISTANT_FINAL_PROMPT_V1,
    ASSISTANT_FINAL_RUBRIC_V1,
    ASSISTANT_PROMPT_V1,
    ASSISTANT_RUBRIC_V1,
    SUBJECT_PROMPT_V1,
)
from app.agents.validation_loop import ValidationLoopError, validated_call
from app.schemas import Finding

logger = logging.getLogger(__name__)
from app.schemas import CandidateSpec, Coaching, FinalFinding, SubjectReply

# USD per million tokens (input, output). Used for leaderboard cost disclosure.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


def build_chat_model(model_id: str, effort: str = "medium", max_tokens: int = 4096, settings=None) -> BaseChatModel:
    """Chat model for the configured provider.

    - openai_compatible: any OpenAI-style gateway (chat completions API), e.g. gpt-oss-20b.
    - anthropic: Claude with adaptive thinking, explicit effort and server-side refusal fallbacks.
    """
    from app.config import get_settings

    settings = settings or get_settings()
    if settings.resolved_provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_id,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            reasoning_effort=effort if effort in ("low", "medium", "high") else "medium",
            max_tokens=max_tokens,
            max_retries=2,
            timeout=120,
        )
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=model_id,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        betas=["server-side-fallback-2026-07-01"],
        model_kwargs={"fallbacks": "default"},
        max_retries=2,
    )


def estimate_cost(model_id: str | None, input_tokens: int, output_tokens: int) -> float:
    if not model_id or model_id not in PRICES:
        return 0.0
    pin, pout = PRICES[model_id]
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 6)


def _usage(messages: list[Any]) -> tuple[int, int]:
    tin = tout = 0
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "usage_metadata", None):
            tin += int(m.usage_metadata.get("input_tokens", 0) or 0)
            tout += int(m.usage_metadata.get("output_tokens", 0) or 0)
    return tin, tout


def _last_text(messages: list[Any]) -> str:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            c = m.content
            if isinstance(c, str):
                return c
            return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


class DeepAgentAssistant:
    def __init__(self, spec: CandidateSpec, model: BaseChatModel, grader_model: BaseChatModel | str | None = None) -> None:
        ensure_profiles(model)
        self.spec = spec
        self.model = model
        self.grader_model = grader_model
        self.prompt = ASSISTANT_PROMPT_V1
        self.rubric_loop = bool(spec.policy.get("rubric_loop"))

    def _agent(self, ctx: AssistantContext):
        from deepagents import create_deep_agent

        @tool
        def lookup_turn(turn_index: int) -> str:
            """Return the exact investigator question and subject answer for a transcript turn."""
            for e in ctx.transcript:
                if e.index == turn_index:
                    return json.dumps({"turn_index": e.index, "question": e.question, "answer": e.answer})
            return json.dumps({"error": f"no turn {turn_index}"})

        @tool
        def list_released_evidence() -> str:
            """Return every record released to the investigator so far."""
            return json.dumps([{"id": e.id, "title": e.title, "content": e.content} for e in ctx.released_evidence])

        @tool
        def get_case_packet() -> str:
            """Return the public case packet (objective, context, timeline, lines of questioning)."""
            return ctx.case_text()

        middleware = []
        if self.rubric_loop and self.grader_model is not None:
            from deepagents import RubricMiddleware

            middleware.append(RubricMiddleware(model=self.grader_model, max_iterations=int(self.spec.policy.get("rubric_max_iterations", 2))))
        return create_deep_agent(
            model=self.model,
            tools=[lookup_turn, list_released_evidence, get_case_packet],
            system_prompt=SystemMessage(content=self.prompt),
            middleware=middleware,
            name=self.spec.id,
        )

    def _run(self, ctx: AssistantContext, user_text: str, model_cls, rubric: str | None, record: bool = True):
        """One agent call under the L0 validation loop (and the L1 rubric loop when enabled)."""
        agent = self._agent(ctx)
        messages: list[Any] = [HumanMessage(content=user_text)]
        if record:
            ctx.record(self.prompt + "\n" + user_text)
        state: dict[str, Any] = {}
        iterations = 0

        def invoke(correction: str | None) -> str:
            nonlocal state, iterations
            if correction:
                messages.extend(state.get("messages", [])[len(messages):])  # keep agent's own messages
                messages.append(HumanMessage(content=correction))
            payload: dict[str, Any] = {"messages": list(messages)}
            if self.rubric_loop and rubric:
                payload["rubric"] = rubric
            state = agent.invoke(payload)
            iterations += 1
            return _last_text(state.get("messages", []))

        parsed, _ = validated_call(invoke, model_cls)
        tin, tout = _usage(state.get("messages", []))
        return parsed, tin, tout, iterations

    def coach(self, ctx: AssistantContext) -> Coaching:
        t0 = time.perf_counter()
        latest = ctx.latest
        user_text = (
            f"{ctx.case_text()}\n\nRELEASED RECORDS:\n{ctx.evidence_text()}\n\nTRANSCRIPT SO FAR:\n{ctx.transcript_text()}\n\n"
            f"LATEST TURN TO ASSESS: T{latest.index}\nINVESTIGATOR QUESTION: {latest.question}\nSUBJECT ANSWER: {latest.answer}\n\n"
            "Produce the coaching JSON for this turn."
        )
        try:
            parsed, tin, tout, iterations = self._run(ctx, user_text, Coaching, ASSISTANT_RUBRIC_V1)
        except ValidationLoopError as exc:  # degrade conservatively instead of failing the interview
            logger.error("assistant %s coaching failed validation: %s", self.spec.id, exc)
            parsed, tin, tout, iterations = Coaching(rationale=f"[assistant output invalid: {str(exc)[:160]}]"), 0, 0, 0
        parsed.latency_ms = int((time.perf_counter() - t0) * 1000)
        parsed.input_tokens, parsed.output_tokens = tin, tout
        parsed.cost_usd = estimate_cost(self.spec.model, tin, tout)
        parsed.rubric_iterations = iterations
        return parsed

    def final_finding(self, ctx: AssistantContext) -> FinalFinding:
        user_text = (
            f"{ctx.case_text()}\n\nRELEASED RECORDS:\n{ctx.evidence_text()}\n\nFULL TRANSCRIPT:\n{ctx.transcript_text()}\n\n"
            + ASSISTANT_FINAL_PROMPT_V1
        )
        try:
            parsed, _, _, _ = self._run(ctx, user_text, FinalFinding, ASSISTANT_FINAL_RUBRIC_V1)
        except ValidationLoopError as exc:
            logger.error("assistant %s final finding failed validation: %s", self.spec.id, exc)
            parsed = FinalFinding(finding=Finding.insufficient_evidence, confidence=0.0,
                                  rationale=f"[assistant output invalid: {str(exc)[:160]}]")
        return parsed


class DeepAgentSubject:
    def __init__(self, spec: CandidateSpec, model: BaseChatModel) -> None:
        ensure_profiles(model)
        self.spec = spec
        self.model = model

    def _system(self, ctx: SubjectContext) -> str:
        p = ctx.private
        guide = "\n".join(
            f"- {t.topic}: honest answer = '{t.truthful_answer}'"
            + (f"; if concealing, you may say '{t.deceptive_answer}' ({t.deceptive_tactic.value})" if t.deceptive_answer else "")
            for t in p.topics
        )
        return SUBJECT_PROMPT_V1.format(
            persona_name=p.persona_name,
            persona_position=p.persona_position,
            style=p.communication_style,
            known_facts="\n".join(f"- {f}" for f in p.known_facts),
            may_disclose="; ".join(p.may_disclose),
            must_not_disclose="; ".join(p.must_not_disclose),
            uncertainty="; ".join(p.uncertainty_notes) or "none",
            objective=p.objective,
            behaviors=", ".join(b.value for b in p.permitted_behaviors),
            topic_guide=guide,
        )

    def answer(self, ctx: SubjectContext) -> SubjectReply:
        from deepagents import create_deep_agent

        t0 = time.perf_counter()
        agent = create_deep_agent(model=self.model, tools=[], system_prompt=SystemMessage(content=self._system(ctx)), name=self.spec.id)
        history: list[Any] = []
        for e in ctx.transcript:
            history.append(HumanMessage(content=e.question))
            history.append(AIMessage(content=json.dumps({"reply": e.answer, "tactic": "truthful", "facts_used": []})))
        history.append(HumanMessage(content=ctx.question))
        state: dict[str, Any] = {}

        def invoke(correction: str | None) -> str:
            nonlocal state
            msgs = list(history)
            if correction:
                msgs = list(state.get("messages", [])) + [HumanMessage(content=correction)]
            state = agent.invoke({"messages": msgs})
            return _last_text(state.get("messages", []))

        reply, _ = validated_call(invoke, SubjectReply)
        p = ctx.private
        reply.compliant = reply.tactic in p.permitted_behaviors and not any(
            s.lower() in reply.reply.lower() for s in p.must_not_disclose if p.role.value == "deceptive"
        )
        if not reply.compliant:
            reply.compliance_note = "tactic outside permitted behaviours or forbidden disclosure"
        reply.latency_ms = int((time.perf_counter() - t0) * 1000)
        return reply
