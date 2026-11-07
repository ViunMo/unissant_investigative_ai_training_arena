"""Draft case briefs from a plain-language description with a hosted model.

A use-case provider describes an incident in a paragraph; the model returns a matched truthful and deceptive
pair in the case-brief format, which the trainer reviews, edits and imports. Nothing enters the engine without
the import step, so a weak draft costs nothing but a model call."""
from __future__ import annotations

import json
from typing import Callable

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.validation_loop import validated_call
from app.scenarios.authoring import CaseBrief, DraftedCases, check_scenario, compile_brief

SYSTEM = """You write training cases for an investigative-interview simulator. Each case is a "case brief" that a
simulated subject (an LLM playing a person under interview) and an AI coach run from. All people, companies and
records must be fictional; never use the real names of people from the description, invent plausible substitutes.

Return ONLY a JSON object: {"cases": [<brief>, ...]} with one brief per requested role. Matched variants share the
same title, family_id, objective, context, known_timeline, initial_question, initial_documents and topic names, and
differ in role, the subject's known facts, answers, evidence contents and canonical facts. Demeanour must be
independent of role: give the truthful and the deceptive subject different communication styles, and do not make
the deceptive one nervous or the truthful one polished by default.

Brief schema (JSON):
{
  "title": str, "role": "truthful"|"deceptive", "family_id": "fam_<slug>", "case_id": "case_<slug>_t|_d",
  "split": "hidden", "difficulty": "low"|"medium"|"high",
  "objective": str (what the investigator must determine), "context": str (2-4 sentences),
  "known_timeline": [str, ...] (3-5 dated entries), "initial_question": str,
  "max_turns": 12,
  "initial_documents": [{"title": str, "content": str}] (1 record the investigator starts with),
  "subject": {"name": str, "position": str, "communication_style": str, "known_facts": [str, ...] (3-5),
              "may_disclose": [str], "must_not_disclose": [str] (deceptive only: phrases never to say),
              "uncertainty_notes": [str]},
  "topics": [ (5-6 lines of questioning)
    {"topic": "snake_case", "question": str (neutral, specific), "truthful_answer": str (1-2 sentences in character),
     "deceptive_answer": str|null (deceptive role, on sensitive topics only), "tactic": "omission"|"deflection"|"minimisation"|"contradiction",
     "uncertain": bool (truthful subject genuinely does not recall)}
  ],
  "evidence_release": [ (2 records) {"title": str, "content": str, "release_after_turn": 2|4,
     "contradicts": [str] (deceptive only: short lowercase phrases from the deceptive answers this record disproves)}],
  "violation": str|null (deceptive only), "canonical_facts": [str, ...] (3), "material_contradictions": [str],
  "resolution_criteria": str
}
In the deceptive variant at least three topics must carry a deceptive_answer, and at least one evidence record must
contradict one of them. In the truthful variant leave deceptive_answer null everywhere and violation null."""


def _prompt(description: str, roles: list[str]) -> str:
    return (f"Requested variants: {', '.join(roles)}.\n\nIncident description from the use-case provider:\n\n{description.strip()}\n\n"
            "Reply with ONLY the JSON object.")


def draft_cases(description: str, roles: list[str], model: BaseChatModel | Callable[[str], str]) -> dict:
    """Return {'yaml': <editable brief text>, 'cases': [...], 'warnings': [...], 'retries': n}."""
    roles = [r for r in roles if r in ("truthful", "deceptive")] or ["truthful", "deceptive"]
    messages = [SystemMessage(content=SYSTEM), HumanMessage(content=_prompt(description, roles))]

    def invoke(correction: str | None) -> str:
        msgs = messages + ([HumanMessage(content=correction)] if correction else [])
        if callable(model) and not isinstance(model, BaseChatModel):
            return model(msgs[-1].content)
        out = model.invoke(msgs)
        content = out.content
        if isinstance(content, list):  # Anthropic/Gemini content blocks
            content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        return content

    drafted, retries = validated_call(invoke, DraftedCases, max_retries=2)
    warnings = []
    for brief in drafted.cases:
        for w in check_scenario(compile_brief(brief)):
            warnings.append(f"{brief.case_id or brief.title} ({brief.role.value}): {w}")
    cases = [json.loads(b.model_dump_json(exclude_none=True)) for b in drafted.cases]
    text = yaml.safe_dump({"cases": cases}, sort_keys=False, allow_unicode=True, width=110)
    return {"yaml": text, "cases": cases, "warnings": warnings, "retries": retries}


__all__ = ["draft_cases", "CaseBrief"]
