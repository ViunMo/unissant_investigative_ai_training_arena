"""L0 loop: parse-validate-retry around any model call that must return typed JSON."""
from __future__ import annotations

import json
import re
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ValidationLoopError(RuntimeError):
    pass


def extract_json_object(text: str) -> dict:
    """Tolerant extraction: strips code fences and takes the outermost {...} block."""
    if not text:
        raise ValueError("empty model output")
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(cleaned[start : end + 1])


def validated_call(
    invoke: Callable[[str | None], str],
    model_cls: type[T],
    max_retries: int = 2,
) -> tuple[T, int]:
    """Call `invoke(correction)` until the output validates as `model_cls`.

    `invoke` receives None on the first attempt and a correction message afterwards.
    Returns the parsed model and the number of retries used.
    """
    correction: str | None = None
    last_error = ""
    for attempt in range(max_retries + 1):
        raw = invoke(correction)
        try:
            return model_cls.model_validate(extract_json_object(raw)), attempt
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            correction = (
                "Your previous reply was not valid JSON for the required schema. "
                f"Error: {last_error[:400]}. Reply again with ONLY a JSON object matching the schema."
            )
    raise ValidationLoopError(f"model output failed validation after {max_retries} retries: {last_error}")
