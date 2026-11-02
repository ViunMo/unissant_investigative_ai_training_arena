"""Candidate registry: versioned combinations of model, prompt, tool configuration and policy."""
from __future__ import annotations

from app.agents.mock import MockAssistant, MockSubject
from app.agents.runtime import AssistantRuntime, SubjectRuntime
from app.config import Settings, get_settings
from app.schemas import CandidateSpec


def default_specs(settings: Settings) -> list[CandidateSpec]:
    live = settings.resolved_provider != "mock"
    a_model = settings.model_for("assistant") or settings.assistant_model
    s_model = settings.model_for("subject") or settings.subject_model
    fast_model = settings.model_for("assistant") or "claude-sonnet-5-5"
    return [
        CandidateSpec(id="asst-evidence-v1", kind="assistant", label=f"Evidence-first + rubric loop ({a_model})", version="1.0",
                      model=a_model, prompt_version="assistant_v1", runtime="deepagents",
                      policy={"rubric_loop": True, "rubric_max_iterations": 2, "effort": "medium"},
                      description=f"{a_model} with the evidence-first prompt and a deepagents RubricMiddleware self-evaluation loop."),
        CandidateSpec(id="asst-fast-v1", kind="assistant", label=f"Fast coach, no rubric loop ({fast_model})", version="1.0",
                      model=fast_model, prompt_version="assistant_v1", runtime="deepagents",
                      policy={"rubric_loop": False, "effort": "low"},
                      description=f"{fast_model} at low reasoning effort, tuned for the 3-second coaching target."),
        CandidateSpec(id="asst-mock-evidence-v1", kind="assistant", label="Baseline: evidence-first rules", version="1.0",
                      model=None, prompt_version="rules_v1", runtime="mock", policy={"style": "evidence_first"},
                      description="Deterministic baseline that only calls deception on record contradictions plus evasion."),
        CandidateSpec(id="asst-mock-aggressive-v1", kind="assistant", label="Baseline: aggressive rules", version="1.0",
                      model=None, prompt_version="rules_v1", runtime="mock", policy={"style": "aggressive"},
                      description="Deterministic baseline that treats uncertainty as evasion. Expected to fail the false-positive gate."),
        CandidateSpec(id="subj-llm-v1", kind="subject", label=f"Simulated subject ({s_model})", version="1.0",
                      model=s_model, prompt_version="subject_v1", runtime="deepagents", policy={"effort": "low"}),
        CandidateSpec(id="subj-llm-medium-v1", kind="subject", label=f"Simulated subject, medium effort ({s_model})", version="1.0",
                      model=s_model, prompt_version="subject_v1", runtime="deepagents", policy={"effort": "medium"}),
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

    def list(self, kind: str | None = None) -> list[dict]:
        return [
            {**s.model_dump(), "effective_runtime": self.effective_runtime(s)}
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
