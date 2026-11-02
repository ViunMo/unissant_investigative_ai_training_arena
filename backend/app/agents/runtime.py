"""Runtime protocols implemented by both the deepagents runtimes and the deterministic mocks."""
from __future__ import annotations

from typing import Protocol

from app.agents.context import AssistantContext, SubjectContext
from app.schemas import CandidateSpec, Coaching, FinalFinding, SubjectReply


class AssistantRuntime(Protocol):
    spec: CandidateSpec

    def coach(self, ctx: AssistantContext) -> Coaching: ...

    def final_finding(self, ctx: AssistantContext) -> FinalFinding: ...


class SubjectRuntime(Protocol):
    spec: CandidateSpec

    def answer(self, ctx: SubjectContext) -> SubjectReply: ...
