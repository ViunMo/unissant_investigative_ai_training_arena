"""Candidate registry: versioned combinations of model, prompt, tool configuration and policy."""
from __future__ import annotations

import re
import time

import httpx

from app.agents.mock import MockAssistant, MockSubject
from app.agents.runtime import AssistantRuntime, SubjectRuntime
from app.config import Settings, get_settings, vendor_for
from app.schemas import CandidateSpec


def _slug(model_id: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", model_id.lower()).strip("-")


def default_specs(settings: Settings) -> list[CandidateSpec]:
    """One assistant and one subject candidate per configured model, same prompt, tools and effort, so the models
    (not the policies) are what differ in a bake-off. The first model also gets a rubric-loop variant so the L1 loop
    is exercised without multiplying the bake-off grid."""
    a_models = settings.models_for("assistant")
    s_models = settings.models_for("subject")
    grader = settings.model_for("grader")
    llm: list[CandidateSpec] = [
        CandidateSpec(id=f"asst-{_slug(m)}-v1", kind="assistant", label=f"Evidence-first coach ({m})", version="1.0",
                      model=m, prompt_version="assistant_v1", runtime="deepagents",
                      policy={"rubric_loop": False, "effort": "low"},
                      description=f"{m} with the evidence-first prompt at low effort; same prompt, tools and budget as every other model candidate.")
        for m in a_models
    ]
    if a_models:
        first = a_models[0]
        llm.append(CandidateSpec(id=f"asst-{_slug(first)}-rubric-v1", kind="assistant",
                                 label=f"Evidence-first + rubric loop ({first})", version="1.0",
                                 model=first, prompt_version="assistant_v1", runtime="deepagents",
                                 policy={"rubric_loop": True, "rubric_max_iterations": 2, "effort": "medium"},
                                 description=f"{first} with a deepagents RubricMiddleware self-evaluation loop graded by {grader}; slower, used to measure what the rubric loop buys."))
    llm += [
        CandidateSpec(id=f"subj-{_slug(m)}-v1", kind="subject", label=f"Simulated subject ({m})", version="1.0",
                      model=m, prompt_version="subject_v1", runtime="deepagents", policy={"effort": "low"})
        for m in s_models
    ]
    return llm + [
        CandidateSpec(id="asst-mock-evidence-v1", kind="assistant", label="Baseline: evidence-first rules", version="1.0",
                      model=None, prompt_version="rules_v1", runtime="mock", policy={"style": "evidence_first"},
                      description="Deterministic baseline that only calls deception on record contradictions plus evasion."),
        CandidateSpec(id="asst-mock-aggressive-v1", kind="assistant", label="Baseline: aggressive rules", version="1.0",
                      model=None, prompt_version="rules_v1", runtime="mock", policy={"style": "aggressive"},
                      description="Deterministic baseline that treats uncertainty as evasion. Expected to fail the false-positive gate."),
        CandidateSpec(id="subj-mock-v1", kind="subject", label="Baseline: scripted subject", version="1.0",
                      model=None, prompt_version="script_v1", runtime="mock"),
    ]


class CandidateRegistry:
    def __init__(self, settings: Settings | None = None, specs: list[CandidateSpec] | None = None) -> None:
        self.settings = settings or get_settings()
        self.specs: dict[str, CandidateSpec] = {s.id: s for s in (specs or default_specs(self.settings))}
        self._assistants: dict[str, AssistantRuntime] = {}
        self._subjects: dict[str, SubjectRuntime] = {}
        self._models: dict[str, object] = {}
        self._gateway_cache: tuple[float, set[str] | None] | None = None

    @property
    def provider(self) -> str:
        return self.settings.resolved_provider

    @property
    def live(self) -> bool:
        return self.provider != "mock"

    def effective_runtime(self, spec: CandidateSpec) -> str:
        if spec.runtime == "deepagents" and not self.live:
            return "mock (fallback: no model credentials configured)"
        return spec.runtime

    def gateway_models(self) -> set[str] | None:
        """Model ids the OpenAI-compatible gateway serves right now (None when unknown). Cached for 30 s."""
        if self.provider != "openai_compatible":
            return None
        now = time.monotonic()
        if self._gateway_cache and now - self._gateway_cache[0] < 30:
            return self._gateway_cache[1]
        try:
            r = httpx.get(f"{self.settings.gateway_base_url.rstrip('/')}/models",
                          headers={"Authorization": f"Bearer {self.settings.gateway_api_key}"}, timeout=3)
            r.raise_for_status()
            ids: set[str] | None = {m["id"] for m in r.json().get("data", [])}
        except Exception:  # unreachable gateway or a gateway without /models: availability is simply unknown
            ids = None
        self._gateway_cache = (now, ids)
        return ids

    def unavailable_reason(self, spec: CandidateSpec) -> str | None:
        """Why a model-backed candidate cannot run right now: a missing vendor key, or a gateway model not pulled yet."""
        if spec.runtime != "deepagents" or not self.live:
            return None
        if self.provider == "cloud":
            return self.settings.missing_credential(spec.model)
        models = self.gateway_models()
        if models is None or spec.model in models or f"{spec.model}:latest" in models:  # Ollama lists untagged models as :latest
            return None
        return f"model '{spec.model}' is not served by the gateway yet (for Ollama: ollama pull {spec.model})"

    def available(self, spec: CandidateSpec) -> bool | None:
        """False when the candidate's model cannot be called; None when unknowable (gateway without /models)."""
        if spec.runtime != "deepagents" or not self.live:
            return True
        if self.provider != "cloud" and self.gateway_models() is None:
            return None
        return self.unavailable_reason(spec) is None

    def first_available(self, kind: str) -> str | None:
        specs = [s for s in self.specs.values() if s.kind == kind]
        return next((s.id for s in specs if self.available(s) is not False), specs[0].id if specs else None)

    def list(self, kind: str | None = None) -> list[dict]:
        return [
            {**s.model_dump(), "effective_runtime": self.effective_runtime(s), "available": self.available(s),
             "unavailable_reason": self.unavailable_reason(s), "vendor": vendor_for(s.model) if self.provider == "cloud" else None}
            for s in self.specs.values()
            if kind is None or s.kind == kind
        ]

    def spec(self, cid: str) -> CandidateSpec:
        if cid not in self.specs:
            raise KeyError(f"unknown candidate {cid}")
        return self.specs[cid]

    def _model(self, model_id: str, effort: str):
        from app.agents.llm import build_chat_model

        key = f"{model_id}|{effort}"
        if key not in self._models:
            self._models[key] = build_chat_model(model_id, effort=effort, settings=self.settings)
        return self._models[key]

    def assistant(self, cid: str) -> AssistantRuntime:
        if cid not in self._assistants:
            spec = self.spec(cid)
            if spec.kind != "assistant":
                raise ValueError(f"{cid} is not an assistant candidate")
            if spec.runtime == "deepagents" and self.live:
                from app.agents.llm import DeepAgentAssistant

                grader = self._model(self.settings.model_for("grader"), "low") if spec.policy.get("rubric_loop") else None
                self._assistants[cid] = DeepAgentAssistant(spec, self._model(spec.model, spec.policy.get("effort", "medium")), grader)
            else:
                fallback = spec if spec.runtime == "mock" else spec.model_copy(update={"policy": {"style": "evidence_first"}})
                self._assistants[cid] = MockAssistant(fallback)
        return self._assistants[cid]

    def subject(self, cid: str) -> SubjectRuntime:
        if cid not in self._subjects:
            spec = self.spec(cid)
            if spec.kind != "subject":
                raise ValueError(f"{cid} is not a subject candidate")
            if spec.runtime == "deepagents" and self.live:
                from app.agents.llm import DeepAgentSubject

                self._subjects[cid] = DeepAgentSubject(spec, self._model(spec.model, spec.policy.get("effort", "low")))
            else:
                self._subjects[cid] = MockSubject(spec)
        return self._subjects[cid]
