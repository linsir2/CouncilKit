from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import IngestPayloadInvalidError
from ..harness import load_harness_payload
from ..session_spec import build_session_spec


def read_ingest_payload(payload_ref: Path) -> dict[str, Any]:
    try:
        payload = json.loads(payload_ref.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise IngestPayloadInvalidError(f"Ingest payload file not found: {payload_ref}") from error
    except json.JSONDecodeError as error:
        raise IngestPayloadInvalidError(f"Ingest payload JSON is invalid: {error}") from error
    if not isinstance(payload, dict):
        raise IngestPayloadInvalidError("Ingest payload must be a JSON object")
    return payload


def best_effort_session_spec(payload_ref: Path) -> dict[str, Any] | None:
    try:
        payload = read_ingest_payload(payload_ref)
    except IngestPayloadInvalidError:
        return None
    return payload_session_spec(payload, payload_ref)


def payload_session_spec(payload: dict[str, Any] | None, payload_ref: Path) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    try:
        return load_session_spec(payload, payload_ref=payload_ref)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, IngestPayloadInvalidError):
        return None


def selected_skill_slugs_from_payload(payload_ref: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(payload_ref.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    session_spec = payload.get("session_spec")
    if isinstance(session_spec, dict):
        selected = tuple(
            str(item).strip()
            for item in session_spec.get("selected_skill_slugs", [])
            if str(item).strip()
        )
        if selected:
            return selected
        participants = tuple(
            str(item.get("slug", "")).strip()
            for item in session_spec.get("participants", [])
            if isinstance(item, dict) and str(item.get("slug", "")).strip()
        )
        if participants:
            return participants

    admission = payload.get("admission")
    if isinstance(admission, dict):
        selected = tuple(
            str(item).strip()
            for item in admission.get("selected_skills", [])
            if str(item).strip()
        )
        if selected:
            return selected

    harness = payload.get("harness")
    if isinstance(harness, dict):
        selected = tuple(
            str(item).strip()
            for item in harness.get("selected_skill_slugs", [])
            if str(item).strip()
        )
        if selected:
            return selected
    return ()


def extract_turn_payloads(payload: dict[str, Any]) -> object:
    turns = payload.get("turns")
    if not isinstance(turns, list):
        return turns
    flattened: list[dict[str, Any]] = []
    for item in turns:
        if not isinstance(item, dict):
            flattened.append(item)
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            flattened.append(item)
            continue
        flattened.append(
            {
                "stage": item.get("stage"),
                "round_index": item.get("round_index"),
                "skill_slug": item.get("skill_slug", ""),
                "message": item.get("message", ""),
                "judgment": result.get("judgment"),
                "evidence": result.get("evidence"),
                "tradeoff": result.get("tradeoff"),
                "objection": result.get("objection"),
                "needs_verification": result.get("needs_verification"),
                "confidence": result.get("confidence"),
            }
        )
    return flattened


def load_session_spec(payload: dict[str, object], *, payload_ref: Path) -> dict[str, Any]:
    session_spec = payload.get("session_spec")
    if isinstance(session_spec, dict):
        return session_spec

    harness_payload = payload.get("harness")
    if isinstance(harness_payload, dict):
        contract, admission = load_harness_payload(payload_ref)
        return build_session_spec(harness=contract, admission=admission)

    session_spec_path = str(payload.get("session_spec_path", "")).strip()
    if not session_spec_path:
        raise ValueError("Ingest payload requires session_spec or session_spec_path")
    path = Path(session_spec_path)
    if not path.is_absolute():
        path = payload_ref.parent / path
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("session_spec_path must point to a JSON object")
    return loaded


def turn_payload_at(payload: dict[str, Any] | None, turn_index: int) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    turns = payload.get("turns")
    if not isinstance(turns, list):
        return None
    zero_index = turn_index - 1
    if zero_index < 0 or zero_index >= len(turns):
        return None
    item = turns[zero_index]
    return item if isinstance(item, dict) else None
