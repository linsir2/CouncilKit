from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..errors import (
    IngestPayloadInvalidError,
    ScheduleTurnCountMismatchError,
    ScheduleTurnOrderMismatchError,
    SlotInvalidConfidenceError,
    SlotMissingRequiredError,
    SynthesisPayloadInvalidError,
)
from ..harness_contract import REDUCTION_SLOTS
from ..validation import ALLOWED_CONFIDENCE_LEVELS, SYNTHESIS_REQUIRED_KEYS
from .map import prepare_ingest_trace
from .models import DispatchPayloadRepairHint, DispatchPayloadValidationIssue, DispatchPayloadValidationReport
from .parse import best_effort_session_spec, payload_session_spec, read_ingest_payload, selected_skill_slugs_from_payload, turn_payload_at

SECTION_PRIORITY_ORDER = {
    "payload": 10,
    "prompt": 20,
    "session_spec": 30,
    "turns": 40,
    "synthesis": 50,
    "admission": 60,
    "ingest": 70,
}


def validate_session_run_payload(
    *,
    payload_ref: Path,
    repo_root: Path,
    strict_hash: bool = True,
) -> DispatchPayloadValidationReport:
    payload: dict[str, Any] | None = None
    try:
        payload = read_ingest_payload(payload_ref)
        created_at = str(payload.get("created_at", "")).strip() or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        prepared = prepare_ingest_trace(
            payload=payload,
            payload_ref=payload_ref,
            repo_root=repo_root,
            strict_hash=strict_hash,
            created_at=created_at,
        )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ValueError,
        IngestPayloadInvalidError,
        ScheduleTurnCountMismatchError,
        ScheduleTurnOrderMismatchError,
        SlotMissingRequiredError,
        SlotInvalidConfidenceError,
        SynthesisPayloadInvalidError,
    ) as error:
        failure_code = _map_ingest_failure_code(error)
        return DispatchPayloadValidationReport(
            status="fail",
            issues=_build_validation_issues(
                level="error",
                code=failure_code,
                message=str(error),
                payload=payload,
                payload_ref=payload_ref,
            ),
            repair_hints=_build_repair_hints(
                code=failure_code,
                message=str(error),
                payload_ref=payload_ref,
            ),
            checked_skills=(),
            selected_skill_slugs=selected_skill_slugs_from_payload(payload_ref),
            turn_count=0,
            source_ref=str(payload_ref),
        )

    issues = tuple(
        issue
        for failure in prepared.pending_failures
        for issue in _build_validation_issues(
            level="warning",
            code=str(failure["failure_code"]),
            message=str(failure.get("notes", "")).strip() or str(failure["failure_code"]),
            payload=payload,
            payload_ref=payload_ref,
            source_stage=str(failure["source_stage"]),
        )
    )
    status = "pass_with_warning" if issues else "pass"
    return DispatchPayloadValidationReport(
        status=status,
        issues=issues,
        repair_hints=tuple(
            hint
            for failure in prepared.pending_failures
            for hint in _build_repair_hints(
                code=str(failure["failure_code"]),
                message=str(failure.get("notes", "")).strip() or str(failure["failure_code"]),
                payload_ref=payload_ref,
            )
        ),
        checked_skills=tuple(skill.spec.slug for skill in prepared.trace.skills),
        selected_skill_slugs=prepared.trace.harness.selected_skill_slugs if prepared.trace.harness is not None else (),
        turn_count=len(prepared.trace.turns),
        source_ref=str(payload_ref),
    )


def _expected_dispatch_contract() -> dict[str, Any]:
    return {
        "top_level_requirements": [
            "prompt",
            "session_spec|session_spec_path|harness",
            "turns",
            "synthesis",
        ],
        "reduction_slots": list(REDUCTION_SLOTS),
        "allowed_confidence": list(ALLOWED_CONFIDENCE_LEVELS),
        "synthesis_keys": list(SYNTHESIS_REQUIRED_KEYS),
    }


def _group_issues_by_turn(issues: tuple[DispatchPayloadValidationIssue, ...]) -> list[dict[str, Any]]:
    groups: dict[int, list[DispatchPayloadValidationIssue]] = {}
    for issue in issues:
        if issue.turn_index is None:
            continue
        groups.setdefault(issue.turn_index, []).append(issue)
    return [
        {
            "turn_index": turn_index,
            "blocking": _group_is_blocking(group),
            "blocking_issue_count": _count_blocking(group),
            "non_blocking_issue_count": _count_non_blocking(group),
            "priority_rank": _turn_group_priority(turn_index, group),
            "issue_count": len(group),
            "codes": sorted({item.code for item in group}),
            "issues": [item.to_dict() for item in group],
        }
        for turn_index, group in sorted(groups.items(), key=lambda item: _turn_group_priority(item[0], item[1]))
    ]


def _group_issues_by_section(issues: tuple[DispatchPayloadValidationIssue, ...]) -> list[dict[str, Any]]:
    groups: dict[str, list[DispatchPayloadValidationIssue]] = {}
    for issue in issues:
        section = _issue_section(issue)
        groups.setdefault(section, []).append(issue)
    return [
        {
            "section": section,
            "blocking": _group_is_blocking(group),
            "blocking_issue_count": _count_blocking(group),
            "non_blocking_issue_count": _count_non_blocking(group),
            "priority_rank": _section_group_priority(section, group),
            "issue_count": len(group),
            "codes": sorted({item.code for item in group}),
            "issues": [item.to_dict() for item in group],
        }
        for section, group in sorted(groups.items(), key=lambda item: _section_group_priority(item[0], item[1]))
    ]


def _issue_section(issue: DispatchPayloadValidationIssue) -> str:
    field_path = issue.field_path or ""
    if field_path.startswith("turns["):
        return "turns"
    if field_path.startswith("synthesis"):
        return "synthesis"
    if field_path.startswith("session_spec") or field_path.startswith("harness"):
        return "session_spec"
    if field_path.startswith("prompt"):
        return "prompt"
    if field_path.startswith("payload"):
        return "payload"
    if "session_spec" in field_path or "harness" in field_path:
        return "session_spec"
    return issue.source_stage


def _build_recommended_repair_order(
    issues: tuple[DispatchPayloadValidationIssue, ...],
    repair_hints: tuple[DispatchPayloadRepairHint, ...],
) -> list[dict[str, Any]]:
    hint_by_code: dict[str, DispatchPayloadRepairHint] = {}
    for hint in repair_hints:
        hint_by_code.setdefault(hint.code, hint)

    turn_groups: dict[int, list[tuple[int, DispatchPayloadValidationIssue]]] = {}
    section_groups: dict[str, list[tuple[int, DispatchPayloadValidationIssue]]] = {}
    for index, issue in enumerate(issues):
        if issue.turn_index is not None:
            turn_groups.setdefault(issue.turn_index, []).append((index, issue))
        else:
            section = _issue_section(issue)
            section_groups.setdefault(section, []).append((index, issue))

    queue: list[dict[str, Any]] = []
    for turn_index, group in sorted(turn_groups.items(), key=lambda item: _turn_group_priority(item[0], [pair[1] for pair in item[1]])):
        grouped_issues = [pair[1] for pair in group]
        primary = _primary_issue(grouped_issues)
        hint = hint_by_code.get(primary.code)
        queue.append(
            {
                "scope_type": "turn",
                "scope_id": turn_index,
                "blocking": _group_is_blocking(grouped_issues),
                "priority_rank": _turn_group_priority(turn_index, grouped_issues),
                "issue_count": len(grouped_issues),
                "codes": sorted({item.code for item in grouped_issues}),
                "issue_indexes": [pair[0] for pair in group],
                "primary_code": primary.code,
                "primary_field_path": primary.field_path,
                "primary_action": hint.action if hint is not None else None,
                "suggested_fix": hint.suggested_fix if hint is not None else None,
            }
        )

    for section, group in sorted(section_groups.items(), key=lambda item: _section_group_priority(item[0], [pair[1] for pair in item[1]])):
        grouped_issues = [pair[1] for pair in group]
        primary = _primary_issue(grouped_issues)
        hint = hint_by_code.get(primary.code)
        queue.append(
            {
                "scope_type": "section",
                "scope_id": section,
                "blocking": _group_is_blocking(grouped_issues),
                "priority_rank": _section_group_priority(section, grouped_issues),
                "issue_count": len(grouped_issues),
                "codes": sorted({item.code for item in grouped_issues}),
                "issue_indexes": [pair[0] for pair in group],
                "primary_code": primary.code,
                "primary_field_path": primary.field_path,
                "primary_action": hint.action if hint is not None else None,
                "suggested_fix": hint.suggested_fix if hint is not None else None,
            }
        )

    ordered = sorted(queue, key=lambda item: (item["priority_rank"], item["scope_type"], str(item["scope_id"])))
    for position, item in enumerate(ordered, start=1):
        item["position"] = position
    return ordered


def _group_is_blocking(issues: list[DispatchPayloadValidationIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def _count_blocking(issues: list[DispatchPayloadValidationIssue]) -> int:
    return sum(1 for issue in issues if issue.level == "error")


def _count_non_blocking(issues: list[DispatchPayloadValidationIssue]) -> int:
    return sum(1 for issue in issues if issue.level != "error")


def _turn_group_priority(turn_index: int, issues: list[DispatchPayloadValidationIssue]) -> int:
    return (0 if _group_is_blocking(issues) else 1000) + turn_index


def _section_group_priority(section: str, issues: list[DispatchPayloadValidationIssue]) -> int:
    base = SECTION_PRIORITY_ORDER.get(section, 900)
    return (0 if _group_is_blocking(issues) else 1000) + base


def _primary_issue(issues: list[DispatchPayloadValidationIssue]) -> DispatchPayloadValidationIssue:
    return sorted(
        issues,
        key=lambda issue: (
            0 if issue.level == "error" else 1,
            0 if issue.field_path else 1,
            issue.code,
        ),
    )[0]


def _build_repair_hints(
    *,
    code: str,
    message: str,
    payload_ref: Path,
) -> tuple[DispatchPayloadRepairHint, ...]:
    session_spec = best_effort_session_spec(payload_ref)
    if code == "slot_missing_required":
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="turns[*]",
                action="fill_reduction_slots",
                suggested_fix="Populate every turn with all six reduction slots before ingest.",
                expected={
                    "required_slots": list(REDUCTION_SLOTS),
                    "message": "optional",
                },
            ),
        )
    if code == "slot_invalid_confidence":
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="turns[*].confidence",
                action="normalize_confidence",
                suggested_fix="Normalize every confidence value to one of the allowed literals.",
                expected={"allowed_values": list(ALLOWED_CONFIDENCE_LEVELS)},
            ),
        )
    if code in {"schedule_turn_count_mismatch", "schedule_turn_order_mismatch"}:
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="session_spec.turn_schedule|turns[*]",
                action="realign_turn_sequence",
                suggested_fix="Regenerate turns from the canonical session_spec turn schedule and keep the same order.",
                expected={
                    "turn_schedule": _best_effort_schedule(session_spec),
                },
            ),
        )
    if code == "synthesis_payload_invalid":
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="synthesis",
                action="fill_synthesis_contract",
                suggested_fix="Populate every required synthesis key with a valid value before ingest.",
                expected={
                    "required_keys": list(SYNTHESIS_REQUIRED_KEYS),
                },
            ),
        )
    if code == "prompt_hash_mismatch":
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="session_spec.participants[*].prompt_sha256",
                action="regenerate_session_artifacts",
                suggested_fix="Regenerate the session artifacts from the current skill files or rerun with non-strict hash mode.",
            ),
        )
    return (_build_ingest_payload_invalid_hint(code=code, message=message),)


def _build_ingest_payload_invalid_hint(
    *,
    code: str,
    message: str,
) -> DispatchPayloadRepairHint:
    if code == "ingest_payload_invalid":
        return DispatchPayloadRepairHint(
            code=code,
            target="payload",
            action="repair_payload_shape",
            suggested_fix=message,
            expected={"required_keys": ["prompt", "turns", "synthesis"]},
        )
    if code == "skill_file_not_found":
        return DispatchPayloadRepairHint(
            code=code,
            target="session_spec.participants[*].skill_file",
            action="repair_skill_file_path",
            suggested_fix=message,
        )
    if code == "prompt_hash_mismatch":
        return DispatchPayloadRepairHint(
            code=code,
            target="session_spec.participants[*].prompt_sha256",
            action="regenerate_session_artifacts",
            suggested_fix=message,
        )
    if code == "missing_session_spec":
        return DispatchPayloadRepairHint(
            code=code,
            target="session_spec|session_spec_path|harness",
            action="add_session_contract",
            suggested_fix=message,
            expected={"required_keys": ["session_spec|session_spec_path|harness"]},
        )
    if code == "invalid_synthesis_contract":
        return DispatchPayloadRepairHint(
            code=code,
            target="synthesis",
            action="repair_synthesis_contract",
            suggested_fix=message,
            expected={"required_keys": list(SYNTHESIS_REQUIRED_KEYS)},
        )
    return DispatchPayloadRepairHint(
        code=code,
        target="payload",
        action="inspect_payload",
        suggested_fix=message,
    )


def _build_validation_issues(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    payload_ref: Path,
    source_stage: str | None = None,
) -> tuple[DispatchPayloadValidationIssue, ...]:
    if code == "slot_missing_required":
        return _build_slot_missing_issues(level=level, message=message, payload=payload)
    if code == "slot_invalid_confidence":
        return (_build_confidence_issue(level=level, message=message, payload=payload),)
    if code == "schedule_turn_count_mismatch":
        return (_build_turn_count_issue(level=level, message=message, payload=payload, payload_ref=payload_ref),)
    if code == "schedule_turn_order_mismatch":
        return (_build_turn_order_issue(level=level, message=message, payload=payload, payload_ref=payload_ref),)
    if code == "synthesis_payload_invalid":
        return (_build_synthesis_issue(level=level, message=message, payload=payload),)
    if code == "prompt_hash_mismatch":
        return (_build_prompt_hash_issue(level=level, message=message, payload=payload, payload_ref=payload_ref),)
    return (_build_ingest_issue(level=level, code=code, message=message, payload=payload, payload_ref=payload_ref, source_stage=source_stage),)


def _build_slot_missing_issues(
    *,
    level: str,
    message: str,
    payload: dict[str, Any] | None,
) -> tuple[DispatchPayloadValidationIssue, ...]:
    turn_match = None
    import re

    turn_match = re.search(r"turns\[(\d+)\] missing reduction slots: (.+)$", message)
    if not turn_match:
        return (
            DispatchPayloadValidationIssue(
                level=level,
                code="slot_missing_required",
                message=message,
                source_stage="turns",
                field_path="turns",
                expected={"required_slots": list(REDUCTION_SLOTS)},
            ),
        )
    turn_index = int(turn_match.group(1))
    missing_slots = [part.strip() for part in turn_match.group(2).split(",") if part.strip()]
    issues: list[DispatchPayloadValidationIssue] = []
    for slot in missing_slots:
        issues.append(
            DispatchPayloadValidationIssue(
                level=level,
                code="slot_missing_required",
                message=f"turns[{turn_index}] missing required slot '{slot}'",
                source_stage="turns",
                turn_index=turn_index,
                field_path=f"turns[{turn_index - 1}].{slot}",
                expected=_expected_turn_field(slot),
                actual=None,
            )
        )
    return tuple(issues)


def _build_confidence_issue(
    *,
    level: str,
    message: str,
    payload: dict[str, Any] | None,
) -> DispatchPayloadValidationIssue:
    import re

    match = re.search(r"turns\[(\d+)\]\.confidence must be high, medium, or low \(got (.+)\)$", message)
    if not match:
        return DispatchPayloadValidationIssue(
            level=level,
            code="slot_invalid_confidence",
            message=message,
            source_stage="turns",
            field_path="turns[*].confidence",
            expected=list(ALLOWED_CONFIDENCE_LEVELS),
        )
    turn_index = int(match.group(1))
    actual = match.group(2)
    turn_payload = turn_payload_at(payload, turn_index)
    actual_value = actual if actual != "<empty>" else (turn_payload.get("confidence") if isinstance(turn_payload, dict) else "")
    return DispatchPayloadValidationIssue(
        level=level,
        code="slot_invalid_confidence",
        message=f"turns[{turn_index}] has invalid confidence '{actual}'.",
        source_stage="turns",
        turn_index=turn_index,
        field_path=f"turns[{turn_index - 1}].confidence",
        expected=list(ALLOWED_CONFIDENCE_LEVELS),
        actual=actual_value,
    )


def _build_turn_count_issue(
    *,
    level: str,
    message: str,
    payload: dict[str, Any] | None,
    payload_ref: Path,
) -> DispatchPayloadValidationIssue:
    import re

    match = re.search(r"expected (\d+) turns from session_spec, got (\d+)", message)
    expected = None
    actual = None
    if match:
        expected = int(match.group(1))
        actual = int(match.group(2))
    session_spec = payload_session_spec(payload, payload_ref)
    return DispatchPayloadValidationIssue(
        level=level,
        code="schedule_turn_count_mismatch",
        message=message,
        source_stage="session_spec",
        field_path="turns",
        expected=expected if expected is not None else {"turn_schedule": _best_effort_schedule(session_spec)},
        actual=actual if actual is not None else (len(payload.get("turns", [])) if isinstance(payload, dict) and isinstance(payload.get("turns"), list) else None),
    )


def _build_turn_order_issue(
    *,
    level: str,
    message: str,
    payload: dict[str, Any] | None,
    payload_ref: Path,
) -> DispatchPayloadValidationIssue:
    import re

    match = re.search(
        r"Turn sequence mismatch at index (\d+): expected \(([^,]+), round (\d+), ([^)]+)\)",
        message,
    )
    turn_index = int(match.group(1)) if match else None
    expected_payload = None
    if match:
        expected_payload = {
            "stage": match.group(2),
            "round_index": int(match.group(3)),
            "skill_slug": match.group(4),
        }
    actual_payload = turn_payload_at(payload, turn_index) if turn_index is not None else None
    session_spec = payload_session_spec(payload, payload_ref)
    return DispatchPayloadValidationIssue(
        level=level,
        code="schedule_turn_order_mismatch",
        message=message,
        source_stage="turns",
        turn_index=turn_index,
        field_path=f"turns[{turn_index - 1}]" if turn_index is not None else "turns",
        expected=expected_payload if expected_payload is not None else {"turn_schedule": _best_effort_schedule(session_spec)},
        actual=actual_payload,
    )


def _build_synthesis_issue(
    *,
    level: str,
    message: str,
    payload: dict[str, Any] | None,
) -> DispatchPayloadValidationIssue:
    import re

    synthesis_payload = payload.get("synthesis") if isinstance(payload, dict) else None
    if not isinstance(synthesis_payload, dict):
        return DispatchPayloadValidationIssue(
            level=level,
            code="synthesis_payload_invalid",
            message=message,
            source_stage="synthesis",
            field_path="synthesis",
            expected={"type": "object", "required_keys": list(SYNTHESIS_REQUIRED_KEYS)},
            actual=synthesis_payload,
        )
    match = re.search(r"Synthesis payload missing or empty key: ([a-z_]+)", message)
    if match:
        key = match.group(1)
        return DispatchPayloadValidationIssue(
            level=level,
            code="synthesis_payload_invalid",
            message=f"synthesis.{key} is missing or empty",
            source_stage="synthesis",
            field_path=f"synthesis.{key}",
            expected=_expected_synthesis_field(key),
            actual=synthesis_payload.get(key),
        )
    return DispatchPayloadValidationIssue(
        level=level,
        code="synthesis_payload_invalid",
        message=message,
        source_stage="synthesis",
        field_path="synthesis",
        expected={"required_keys": list(SYNTHESIS_REQUIRED_KEYS)},
        actual=synthesis_payload,
    )


def _build_prompt_hash_issue(
    *,
    level: str,
    message: str,
    payload: dict[str, Any] | None,
    payload_ref: Path,
) -> DispatchPayloadValidationIssue:
    session_spec = payload_session_spec(payload, payload_ref)
    participants = session_spec.get("participants", []) if isinstance(session_spec, dict) else []
    participant = participants[0] if isinstance(participants, list) and participants else None
    return DispatchPayloadValidationIssue(
        level=level,
        code="prompt_hash_mismatch",
        message=message,
        source_stage="session_spec",
        field_path="session_spec.participants[*].prompt_sha256",
        expected={"type": "sha256", "matches_current_skill_file": True},
        actual=participant.get("prompt_sha256") if isinstance(participant, dict) else None,
    )


def _build_ingest_issue(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    payload_ref: Path,
    source_stage: str | None = None,
) -> DispatchPayloadValidationIssue:
    stage = source_stage or "payload"
    field_path = "payload"
    expected: Any | None = None
    actual: Any | None = None
    if "session_spec or session_spec_path" in message:
        stage = "session_spec"
        field_path = "session_spec|session_spec_path|harness"
        expected = {"required_keys": ["session_spec|session_spec_path|harness"]}
    elif "non-empty prompt" in message:
        stage = "prompt"
        field_path = "prompt"
        expected = {"type": "string", "non_empty": True}
        actual = payload.get("prompt") if isinstance(payload, dict) else None
    elif "turns as a list" in message:
        stage = "turns"
        field_path = "turns"
        expected = {"type": "list"}
        actual = payload.get("turns") if isinstance(payload, dict) else None
    elif "synthesis object" in message:
        stage = "synthesis"
        field_path = "synthesis"
        expected = {"type": "object", "required_keys": list(SYNTHESIS_REQUIRED_KEYS)}
        actual = payload.get("synthesis") if isinstance(payload, dict) else None
    return DispatchPayloadValidationIssue(
        level=level,
        code=code,
        message=message,
        source_stage=stage,
        field_path=field_path,
        expected=expected,
        actual=actual,
    )


def _best_effort_schedule(session_spec: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not isinstance(session_spec, dict):
        return None
    payload = session_spec.get("turn_schedule")
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    return None


def _expected_turn_field(slot: str) -> dict[str, Any]:
    if slot in {"message", "judgment", "tradeoff", "objection"}:
        return {"type": "string", "non_empty": True}
    if slot in {"evidence", "needs_verification"}:
        return {"type": "list", "items": "string"}
    if slot == "confidence":
        return {"type": "string", "allowed_values": list(ALLOWED_CONFIDENCE_LEVELS)}
    return {"type": "string", "non_empty": True}


def _expected_synthesis_field(key: str) -> dict[str, Any]:
    if key in {"title", "summary", "decision"}:
        return {"type": "string", "non_empty": True}
    if key in {"key_decisions", "next_steps", "open_questions"}:
        return {"type": "list", "items": "string"}
    if key == "strongest_objections":
        return {
            "type": "list",
            "items": {
                "skill": "string",
                "objection": "string",
                "severity": ["low", "medium", "high"],
            },
        }
    if key == "skill_notes":
        return {
            "type": "list",
            "items": {
                "skill": "string",
                "note": "string",
            },
        }
    return {"type": "string", "non_empty": True}


def _map_ingest_failure_code(error: Exception) -> str:
    if isinstance(error, ScheduleTurnCountMismatchError):
        return "schedule_turn_count_mismatch"
    if isinstance(error, ScheduleTurnOrderMismatchError):
        return "schedule_turn_order_mismatch"
    if isinstance(error, SlotMissingRequiredError):
        return "slot_missing_required"
    if isinstance(error, SlotInvalidConfidenceError):
        return "slot_invalid_confidence"
    if isinstance(error, SynthesisPayloadInvalidError):
        return "synthesis_payload_invalid"
    if isinstance(error, IngestPayloadInvalidError):
        if "session_spec or session_spec_path" in str(error):
            return "missing_session_spec"
        if "synthesis object" in str(error):
            return "invalid_synthesis_contract"
        return "ingest_payload_invalid"
    if isinstance(error, FileNotFoundError):
        return "skill_file_not_found"
    if isinstance(error, json.JSONDecodeError):
        return "ingest_payload_invalid"
    if isinstance(error, ValueError) and "prompt hash mismatch" in str(error):
        return "prompt_hash_mismatch"
    return "ingest_payload_invalid"
