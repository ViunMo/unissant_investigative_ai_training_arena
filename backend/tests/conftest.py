import pytest

from app.agents.candidates import CandidateRegistry
from app.config import Settings
from app.loops.interview_loop import InterviewLoop
from app.scenarios.engine import ScenarioEngine


@pytest.fixture
def settings() -> Settings:
    return Settings(provider="mock")


@pytest.fixture
def engine() -> ScenarioEngine:
    return ScenarioEngine()


@pytest.fixture
def registry(settings) -> CandidateRegistry:
    return CandidateRegistry(settings)


@pytest.fixture
def loop(engine, registry) -> InterviewLoop:
    return InterviewLoop(engine, registry)
