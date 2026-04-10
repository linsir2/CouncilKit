from __future__ import annotations

from typing import Any, Sequence

from ..errors import IngestPayloadInvalidError, ScheduleTurnCountMismatchError, ScheduleTurnOrderMismatchError


def validate_declared_turn_schedule(expected_schedule: Sequence[Any], payload: Any) -> None:
    if payload is None:
        return
    if not isinstance(payload, list):
        raise IngestPayloadInvalidError("session_spec.turn_schedule must be a list")
    if len(payload) != len(expected_schedule):
        raise ScheduleTurnCountMismatchError(
            "session_spec.turn_schedule mismatch: "
            f"expected {len(expected_schedule)} scheduled turns, got {len(payload)}"
        )

    for index, (raw_turn, expected) in enumerate(zip(payload, expected_schedule, strict=False), start=1):
        _validate_expected_turn_object(raw_turn, index=index, label="session_spec.turn_schedule")
        turn_index = int(raw_turn.get("turn_index", expected.turn_index))
        stage = str(raw_turn.get("stage", expected.stage)).strip()
        round_index = int(raw_turn.get("round_index", expected.round_index))
        skill_slug = str(raw_turn.get("skill_slug", expected.skill_slug)).strip()
        skill_name = str(raw_turn.get("skill_name", expected.skill_name)).strip()
        if (
            turn_index != expected.turn_index
            or stage != expected.stage
            or round_index != expected.round_index
            or skill_slug != expected.skill_slug
            or skill_name != expected.skill_name
        ):
            raise ScheduleTurnOrderMismatchError(
                "session_spec.turn_schedule mismatch at index "
                f"{index}: expected ({expected.turn_index}, {expected.stage}, "
                f"round {expected.round_index}, {expected.skill_slug}, {expected.skill_name})"
            )


def validate_turn_sequence_item(raw_turn: Any, expected: Any, *, index: int) -> None:
    _validate_expected_turn_object(raw_turn, index=index, label="turns")
    stage = str(raw_turn.get("stage", expected.stage)).strip() or expected.stage
    round_index = int(raw_turn.get("round_index", expected.round_index))
    skill_slug = str(raw_turn.get("skill_slug", expected.skill_slug)).strip() or expected.skill_slug
    if stage != expected.stage or round_index != expected.round_index or skill_slug != expected.skill_slug:
        raise ScheduleTurnOrderMismatchError(
            "Turn sequence mismatch at index "
            f"{index}: expected ({expected.stage}, round {expected.round_index}, {expected.skill_slug})"
        )


def _validate_expected_turn_object(raw_turn: Any, *, index: int, label: str) -> None:
    if not isinstance(raw_turn, dict):
        raise IngestPayloadInvalidError(f"{label}[{index}] must be an object")
