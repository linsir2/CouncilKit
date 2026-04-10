from __future__ import annotations

from typing import Any

from ..errors import (
    SlotInvalidConfidenceError,
    SlotMissingRequiredError,
    TurnConfidenceInvalidError,
    TurnSlotMissingError,
)
from ..harness_contract import REDUCTION_SLOTS
from ..models import TurnResult

ALLOWED_CONFIDENCE_LEVELS = ("high", "medium", "low")


def normalize_runtime_turn_payload(payload: dict[str, Any]) -> tuple[str, TurnResult]:
    required_strings = ("message", "judgment", "tradeoff", "objection")
    normalized: dict[str, Any] = {}
    for key in required_strings:
        if key not in payload:
            raise TurnSlotMissingError(f"Skill payload missing key: {key}")
        normalized[key] = str(payload[key]).strip()

    try:
        evidence = tuple(_normalize_string_list(payload.get("evidence"), key="evidence", allow_empty=False))
        needs_verification = tuple(
            _normalize_string_list(payload.get("needs_verification"), key="needs_verification", allow_empty=True)
        )
    except ValueError as error:
        raise TurnSlotMissingError(str(error)) from error

    confidence = _normalize_confidence(
        payload.get("confidence", ""),
        error_cls=TurnConfidenceInvalidError,
        message="Skill payload confidence must be high, medium, or low",
    )
    return normalized["message"], TurnResult(
        judgment=normalized["judgment"],
        evidence=evidence,
        tradeoff=normalized["tradeoff"],
        objection=normalized["objection"],
        needs_verification=needs_verification,
        confidence=confidence,
    )


def normalize_dispatch_turn_payload(payload: dict[str, Any]) -> tuple[str, TurnResult]:
    missing = [slot for slot in REDUCTION_SLOTS if slot not in payload]
    if missing:
        raise SlotMissingRequiredError(f"Dispatcher payload missing reduction slots: {', '.join(missing)}")

    message = str(payload.get("message", "")).strip() or str(payload["judgment"]).strip()
    judgment = str(payload["judgment"]).strip()
    tradeoff = str(payload["tradeoff"]).strip()
    objection = str(payload["objection"]).strip()
    confidence = _normalize_confidence(
        payload["confidence"],
        error_cls=SlotInvalidConfidenceError,
        message="Dispatcher payload confidence must be high, medium, or low",
    )

    evidence = tuple(_normalize_string_list(payload["evidence"], key="evidence", allow_empty=False))
    needs_verification = tuple(
        _normalize_string_list(payload["needs_verification"], key="needs_verification", allow_empty=True)
    )
    return message, TurnResult(
        judgment=judgment,
        evidence=evidence,
        tradeoff=tradeoff,
        objection=objection,
        needs_verification=needs_verification,
        confidence=confidence,
    )


def _normalize_confidence(raw_value: Any, *, error_cls: type[ValueError], message: str) -> str:
    confidence = str(raw_value).strip().lower()
    if confidence not in ALLOWED_CONFIDENCE_LEVELS:
        raise error_cls(message)
    return confidence


def _normalize_string_list(payload: Any, *, key: str, allow_empty: bool) -> tuple[str, ...]:
    if payload is None and allow_empty:
        return ()
    if not isinstance(payload, list):
        raise ValueError(f"{key} must be a list")
    items = tuple(str(item).strip() for item in payload if str(item).strip())
    if not items and not allow_empty:
        raise ValueError(f"{key} must be a non-empty list")
    return items
