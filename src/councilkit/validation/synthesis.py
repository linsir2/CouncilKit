from __future__ import annotations

from typing import Any

from ..errors import SynthesisPayloadInvalidError
from ..models import SynthesisResult

SYNTHESIS_REQUIRED_KEYS = (
    "title",
    "summary",
    "decision",
    "key_decisions",
    "strongest_objections",
    "next_steps",
    "open_questions",
    "skill_notes",
)


def normalize_synthesis_payload(payload: dict[str, Any]) -> SynthesisResult:
    try:
        required_strings = ("title", "summary", "decision")
        normalized: dict[str, Any] = {}
        for key in required_strings:
            value = str(payload.get(key, "")).strip()
            if not value:
                raise ValueError(f"Synthesis payload missing or empty key: {key}")
            normalized[key] = value

        key_decisions = tuple(_normalize_string_list(payload.get("key_decisions"), key="key_decisions"))
        next_steps = tuple(_normalize_string_list(payload.get("next_steps"), key="next_steps"))
        open_questions = tuple(
            _normalize_string_list(payload.get("open_questions"), key="open_questions", allow_empty=True)
        )

        objections = payload.get("strongest_objections")
        if not isinstance(objections, list):
            raise ValueError("Synthesis payload strongest_objections must be a list")
        normalized_objections: list[dict[str, str]] = []
        for item in objections:
            if not isinstance(item, dict):
                raise ValueError("Synthesis payload strongest_objections entries must be objects")
            obj = {
                "skill": str(item.get("skill", "")).strip(),
                "objection": str(item.get("objection", "")).strip(),
                "severity": str(item.get("severity", "")).strip().lower(),
            }
            if not obj["skill"] or not obj["objection"] or obj["severity"] not in {"low", "medium", "high"}:
                raise ValueError("Synthesis payload strongest_objections entries are invalid")
            normalized_objections.append(obj)
        if not normalized_objections:
            raise ValueError("Synthesis payload strongest_objections must be non-empty")

        skill_notes = payload.get("skill_notes")
        if not isinstance(skill_notes, list) or not skill_notes:
            raise ValueError("Synthesis payload skill_notes must be a non-empty list")
        normalized_notes: list[dict[str, str]] = []
        for item in skill_notes:
            if not isinstance(item, dict):
                raise ValueError("Synthesis payload skill_notes entries must be objects")
            obj = {
                "skill": str(item.get("skill", "")).strip(),
                "note": str(item.get("note", "")).strip(),
            }
            if not obj["skill"] or not obj["note"]:
                raise ValueError("Synthesis payload skill_notes entries are invalid")
            normalized_notes.append(obj)

        return SynthesisResult(
            title=normalized["title"],
            summary=normalized["summary"],
            decision=normalized["decision"],
            key_decisions=key_decisions,
            strongest_objections=tuple(normalized_objections),
            next_steps=next_steps,
            open_questions=open_questions,
            skill_notes=tuple(normalized_notes),
        )
    except ValueError as error:
        raise SynthesisPayloadInvalidError(str(error)) from error


def _normalize_string_list(payload: Any, *, key: str, allow_empty: bool = False) -> tuple[str, ...]:
    if payload is None and allow_empty:
        return ()
    if not isinstance(payload, list):
        raise ValueError(f"{key} must be a list")
    items = tuple(str(item).strip() for item in payload if str(item).strip())
    if not items and not allow_empty:
        raise ValueError(f"{key} must be a non-empty string list")
    return items
