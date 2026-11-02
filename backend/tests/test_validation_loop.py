import pytest
from pydantic import BaseModel

from app.agents.validation_loop import ValidationLoopError, extract_json_object, validated_call


class Out(BaseModel):
    a: int


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json_object('Sure! ```json\n{"a": 1}\n``` done') == {"a": 1}


def test_validated_call_retries_with_correction():
    seen = []

    def invoke(correction):
        seen.append(correction)
        return "not json" if len(seen) == 1 else '{"a": 2}'

    out, retries = validated_call(invoke, Out)
    assert out.a == 2 and retries == 1
    assert seen[0] is None and "not valid JSON" in seen[1]


def test_validated_call_gives_up():
    with pytest.raises(ValidationLoopError):
        validated_call(lambda c: '{"a": "x"}', Out, max_retries=1)
