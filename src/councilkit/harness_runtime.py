from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .errors import (
    IngestPayloadInvalidError,
    ScheduleTurnCountMismatchError,
    ScheduleTurnOrderMismatchError,
    SlotInvalidConfidenceError,
    SlotMissingRequiredError,
)
from .harness_contract import REDUCTION_SLOTS
from .models import SkillInstance, TurnRecord, TurnResult


@dataclass(frozen=True)
class ScheduledTurn:
    turn_index: int
    stage: str
    round_index: int
    skill_slug: str
    skill_name: str


@dataclass(frozen=True)
class DispatchedTurn:
    turn: ScheduledTurn
    message: str
    result: TurnResult


TurnDispatcher = Callable[[ScheduledTurn], dict[str, Any]]


def build_turn_schedule(session_spec: dict[str, Any]) -> tuple[ScheduledTurn, ...]:
    stages = _extract_stages(session_spec)
    participants = _extract_participants(session_spec)
    turns: list[ScheduledTurn] = []
    turn_index = 0
    for stage_name, rounds in stages:
        if rounds <= 0:
            continue
        for round_index in range(1, rounds + 1):
            ordered = participants[(round_index - 1) % len(participants) :] + participants[
                : (round_index - 1) % len(participants)
            ]
            for slug, name in ordered:
                turn_index += 1
                turns.append(
                    ScheduledTurn(
                        turn_index=turn_index,
                        stage=stage_name,
                        round_index=round_index,
                        skill_slug=slug,
                        skill_name=name,
                    )
                )
    return tuple(turns)


def resolve_turn_schedule(session_spec: dict[str, Any]) -> tuple[ScheduledTurn, ...]:
    schedule = build_turn_schedule(session_spec)
    payload = session_spec.get("turn_schedule")
    if payload is None:
        return schedule
    if not isinstance(payload, list):
        raise IngestPayloadInvalidError("session_spec.turn_schedule must be a list")
    if len(payload) != len(schedule):
        raise ScheduleTurnCountMismatchError(
            "session_spec.turn_schedule mismatch: "
            f"expected {len(schedule)} scheduled turns, got {len(payload)}"
        )

    for index, (raw_turn, expected) in enumerate(zip(payload, schedule, strict=False), start=1):
        if not isinstance(raw_turn, dict):
            raise IngestPayloadInvalidError(f"session_spec.turn_schedule[{index}] must be an object")
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
    return schedule


def dispatch_turns(
    schedule: tuple[ScheduledTurn, ...],
    dispatcher: TurnDispatcher,
) -> tuple[DispatchedTurn, ...]:
    turns: list[DispatchedTurn] = []
    for scheduled in schedule:
        payload = dispatcher(scheduled)
        if not isinstance(payload, dict):
            raise ValueError("Dispatcher must return a dict payload per turn")
        message, result = normalize_dispatch_payload(payload)
        turns.append(DispatchedTurn(turn=scheduled, message=message, result=result))
    return tuple(turns)


def normalize_dispatch_payload(payload: dict[str, Any]) -> tuple[str, TurnResult]:
    missing = [slot for slot in REDUCTION_SLOTS if slot not in payload]
    if missing:
        raise SlotMissingRequiredError(f"Dispatcher payload missing reduction slots: {', '.join(missing)}")

    message = str(payload.get("message", "")).strip() or str(payload["judgment"]).strip()
    judgment = str(payload["judgment"]).strip()
    tradeoff = str(payload["tradeoff"]).strip()
    objection = str(payload["objection"]).strip()
    confidence = str(payload["confidence"]).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        raise SlotInvalidConfidenceError("Dispatcher payload confidence must be high, medium, or low")

    evidence = _normalize_string_list(payload["evidence"], key="evidence", allow_empty=False)
    needs_verification = _normalize_string_list(
        payload["needs_verification"],
        key="needs_verification",
        allow_empty=True,
    )
    return message, TurnResult(
        judgment=judgment,
        evidence=evidence,
        tradeoff=tradeoff,
        objection=objection,
        needs_verification=needs_verification,
        confidence=confidence,
    )


def to_turn_records(
    turns: tuple[DispatchedTurn, ...],
    *,
    skill_instances: tuple[SkillInstance, ...],
) -> tuple[TurnRecord, ...]:
    instances = {item.spec.slug: item for item in skill_instances}
    records: list[TurnRecord] = []
    for item in turns:
        instance = instances.get(item.turn.skill_slug)
        if instance is None:
            raise ValueError(f"No skill instance found for slug: {item.turn.skill_slug}")
        records.append(
            TurnRecord(
                stage=item.turn.stage,
                round_index=item.turn.round_index,
                skill_instance_id=instance.instance_id,
                skill_name=instance.spec.name,
                message=item.message,
                result=item.result,
            )
        )
    return tuple(records)


def render_transcript(prompt: str, turns: tuple[DispatchedTurn, ...]) -> str:
    lines = ["# Harness Runtime Transcript", "", f"Brief: {prompt}", ""]
    if not turns:
        lines.extend(["No turns dispatched.", ""])
        return "\n".join(lines)

    stages = []
    for item in turns:
        if item.turn.stage not in stages:
            stages.append(item.turn.stage)

    for stage in stages:
        stage_turns = [item for item in turns if item.turn.stage == stage]
        lines.extend([f"## {stage}", ""])
        max_round = max(item.turn.round_index for item in stage_turns)
        for round_index in range(1, max_round + 1):
            lines.extend([f"### round {round_index}", ""])
            for item in stage_turns:
                if item.turn.round_index != round_index:
                    continue
                lines.append(f"### {item.turn.skill_name}")
                lines.append(item.message)
                lines.append("")
                lines.append(f"- judgment: {item.result.judgment}")
                lines.append(f"- evidence: {'; '.join(item.result.evidence) if item.result.evidence else 'none'}")
                lines.append(f"- tradeoff: {item.result.tradeoff}")
                lines.append(f"- objection: {item.result.objection or 'none'}")
                lines.append(
                    "- needs_verification: "
                    + ("; ".join(item.result.needs_verification) if item.result.needs_verification else "none")
                )
                lines.append(f"- confidence: {item.result.confidence}")
                lines.append("")
    return "\n".join(lines)


def _extract_stages(session_spec: dict[str, Any]) -> list[tuple[str, int]]:
    payload = session_spec.get("stages")
    if not isinstance(payload, list) or not payload:
        raise ValueError("session_spec.stages must be a non-empty list")

    stages: list[tuple[str, int]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("session_spec.stages entries must be objects")
        stage = str(item.get("stage", "")).strip()
        rounds = int(item.get("rounds", 0))
        if not stage:
            raise ValueError("session_spec.stages entries require stage")
        if rounds < 0:
            raise ValueError("session_spec.stages rounds must be >= 0")
        stages.append((stage, rounds))
    return stages


def _extract_participants(session_spec: dict[str, Any]) -> list[tuple[str, str]]:
    payload = session_spec.get("participants")
    if not isinstance(payload, list) or not payload:
        raise ValueError("session_spec.participants must be a non-empty list")
    participants: list[tuple[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("session_spec.participants entries must be objects")
        slug = str(item.get("slug", "")).strip()
        name = str(item.get("name", "")).strip() or slug
        if not slug:
            raise ValueError("session_spec.participants entries require slug")
        participants.append((slug, name))
    return participants


def _normalize_string_list(payload: Any, *, key: str, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(payload, list):
        raise ValueError(f"{key} must be a list")
    items = tuple(str(item).strip() for item in payload if str(item).strip())
    if not items and not allow_empty:
        raise ValueError(f"{key} must be a non-empty list")
    return items
