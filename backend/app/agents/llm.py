"""deepagents runtimes for investigative assistants and simulated subjects.

Loops used here:
- L0 validation loop (`validated_call`): parse-validate-retry around every model call.
- L1 rubric loop (`RubricMiddleware`): the assistant self-evaluates its coaching against a
  rubric and revises before the result leaves the agent (when the candidate policy enables it).
"""
from __future__ import annotations

import json
import logging
import threading
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
# Anthropic rates from the Claude API price list; gpt-6-luna and gemini-3.5-flash-lite rates from third-party price
# aggregators (eesel.ai, anotherwrapper.com, Oct 2026) - verify against the vendors' pages before billing on them.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-6-luna": (0.10, 0.50),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}


_limiters: dict[str, Any] = {}
_limiters_lock = threading.Lock()


def rate_limiter_for(vendor: str | None, rpm: int):
    """One token bucket per vendor shared by every model instance, so concurrent bake-off trials and practice
    sessions together stay under the vendor's requests-per-minute quota instead of collecting 429s."""
    if not vendor or rpm <= 0:
        return None
    with _limiters_lock:
        if vendor not in _limiters:
            from langchain_core.rate_limiters import InMemoryRateLimiter

            _limiters[vendor] = InMemoryRateLimiter(requests_per_second=rpm / 60.0, check_every_n_seconds=0.1, max_bucket_size=max(1, rpm // 4))
        return _limiters[vendor]


def build_chat_model(model_id: str, effort: str = "medium", max_tokens: int = 4096, settings=None) -> BaseChatModel:
    """Chat model for the configured provider.

    - cloud: hosted vendor APIs, vendor inferred from the model id. OpenAI (`gpt-*`) and Gemini (`gemini-*`) take
      the candidate's effort as `reasoning_effort`; Claude (`claude-*`) runs adaptive thinking with explicit effort.
    - openai_compatible: any OpenAI-style gateway (chat completions API), e.g. gpt-oss-20b or a local Ollama.
    """
    from app.config import get_settings, vendor_for

    settings = settings or get_settings()
    effort = effort if effort in ("low", "medium", "high") else "medium"
    if settings.resolved_provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        # reasoning_effort is a gpt-oss feature; Llama/Mistral-style gateway models reject or ignore it.
        extra = {"reasoning_effort": effort} if "gpt-oss" in model_id else {}
        return ChatOpenAI(
            model=model_id,
            base_url=settings.gateway_base_url,
            api_key=settings.gateway_api_key,
            temperature=settings.openai_temperature,
            max_tokens=max_tokens,
            max_retries=2,
            timeout=300,  # local CPU inference of a 20B model can take minutes per call
            **extra,
        )
    vendor = vendor_for(model_id)
    limiter = rate_limiter_for(vendor, settings.rpm_for_vendor(vendor))
    if vendor == "openai":
        from langchain_openai import ChatOpenAI

        # gpt-6 is a reasoning model: it rejects any non-default temperature; reasoning_effort sets thinking depth.
        return ChatOpenAI(model=model_id, api_key=settings.openai_key, max_tokens=max_tokens,
                          reasoning_effort=effort, max_retries=2, timeout=120, rate_limiter=limiter)
    if vendor == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        # Gemini 3.5 uses fixed sampling defaults (temperature is ignored); reasoning_effort maps to thinking level.
        # The free tier allows 15 requests/min, so the shared limiter plus more retries matter most here.
        return ChatGoogleGenerativeAI(model=model_id, google_api_key=settings.google_key, max_output_tokens=max_tokens,
                                      reasoning_effort=effort, max_retries=4, timeout=120, rate_limiter=limiter)
    if vendor == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # Server-side refusal fallbacks exist for Opus/Sonnet 5.5 but not for Haiku 5.5, which rejects the parameter.
        fallback = {} if "haiku" in model_id else {"betas": ["server-side-fallback-2026-07-01"], "model_kwargs": {"fallbacks": "default"}}
        return ChatAnthropic(model=model_id, api_key=settings.anthropic_key, max_tokens=max_tokens,
                             thinking={"type": "adaptive"}, output_config={"effort": effort}, max_retries=2,
                             rate_limiter=limiter, **fallback)
    raise ValueError(f"cannot infer the vendor of model '{model_id}'; use a gpt-*, claude-* or gemini-* id or configure a gateway")


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
