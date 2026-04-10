from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .errors import (
    IngestPayloadInvalidError,
    ScheduleTurnCountMismatchError,
    ScheduleTurnOrderMismatchError,
    SlotInvalidConfidenceError,
    SlotMissingRequiredError,
    SynthesisPayloadInvalidError,
)
from .failures import FailureEvent, create_failure_event, write_failure_events
from .harness import load_harness_payload, parse_admission_result, resolve_contract_path
from .harness_contract import REDUCTION_SLOTS
from .harness_runtime import (
    DispatchedTurn,
    normalize_dispatch_payload,
    resolve_turn_schedule,
    to_turn_records,
)
from .loader import parse_frontmatter
from .models import (
    AdmissionResult,
    HarnessContract,
    HarnessSkillContract,
    RunTrace,
    SkillInstance,
    SkillSpec,
    TaskEnvelope,
)
from .runtime import normalize_synthesis_payload
from .session_spec import build_session_spec
from .traces import write_trace_artifacts

ALLOWED_CONFIDENCE_LEVELS = ("high", "medium", "low")
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
SECTION_PRIORITY_ORDER = {
    "payload": 10,
    "prompt": 20,
    "session_spec": 30,
    "turns": 40,
    "synthesis": 50,
    "admission": 60,
    "ingest": 70,
}


@dataclass(frozen=True)
class DispatchPayloadValidationIssue:
    level: str
    code: str
    message: str
    source_stage: str
    turn_index: int | None = None
    field_path: str | None = None
    expected: Any | None = None
    actual: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "source_stage": self.source_stage,
        }
        if self.turn_index is not None:
            payload["turn_index"] = self.turn_index
        if self.field_path is not None:
            payload["field_path"] = self.field_path
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.actual is not None:
            payload["actual"] = self.actual
        return payload


@dataclass(frozen=True)
class DispatchPayloadRepairHint:
    code: str
    target: str
    action: str
    suggested_fix: str
    expected: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "target": self.target,
            "action": self.action,
            "suggested_fix": self.suggested_fix,
        }
        if self.expected is not None:
            payload["expected"] = self.expected
        return payload


@dataclass(frozen=True)
class DispatchPayloadValidationReport:
    status: str
    issues: tuple[DispatchPayloadValidationIssue, ...]
    repair_hints: tuple[DispatchPayloadRepairHint, ...]
    checked_skills: tuple[str, ...]
    selected_skill_slugs: tuple[str, ...]
    turn_count: int
    source_ref: str

    def to_dict(self) -> dict[str, Any]:
        issues_by_turn = _group_issues_by_turn(self.issues)
        issues_by_section = _group_issues_by_section(self.issues)
        return {
            "status": self.status,
            "issues": [item.to_dict() for item in self.issues],
            "issues_by_turn": issues_by_turn,
            "issues_by_section": issues_by_section,
            "recommended_repair_order": _build_recommended_repair_order(self.issues, self.repair_hints),
            "repair_hints": [item.to_dict() for item in self.repair_hints],
            "expected_contract": _expected_dispatch_contract(),
            "checked_skills": list(self.checked_skills),
            "selected_skill_slugs": list(self.selected_skill_slugs),
            "turn_count": self.turn_count,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True)
class PreparedIngestTrace:
    trace: RunTrace
    pending_failures: tuple[dict[str, Any], ...]
    model: str | None
    base_url: str | None


def ingest_session_run(
    *,
    payload_ref: Path,
    repo_root: Path,
    output_root: Path,
    directory_name: str | None = None,
    strict_hash: bool = True,
) -> Path:
    fallback_dir_name = directory_name or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir_hint = output_root / fallback_dir_name
    try:
        payload = _read_ingest_payload(payload_ref)
        created_at = str(payload.get("created_at", "")).strip() or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        final_dir_name = directory_name or str(payload.get("directory_name", "")).strip() or created_at
        run_dir_hint = output_root / final_dir_name
        prepared = _prepare_ingest_trace(
            payload=payload,
            payload_ref=payload_ref,
            repo_root=repo_root,
            strict_hash=strict_hash,
            created_at=created_at,
        )
        run_dir = write_trace_artifacts(
            prepared.trace,
            output_root=output_root,
            directory_name=final_dir_name,
            model=prepared.model,
            base_url=prepared.base_url,
        )
        if prepared.pending_failures:
            run_ref = str(run_dir / "run.json")
            repro_ref = str(payload_ref)
            events: list[FailureEvent] = []
            for failure in prepared.pending_failures:
                events.append(
                    create_failure_event(
                        run_ref=run_ref,
                        source_stage=str(failure["source_stage"]),
                        failure_code=str(failure["failure_code"]),
                        repro_ref=repro_ref,
                        deterministic=bool(failure["deterministic"]),
                        skill_slugs=tuple(str(item) for item in failure.get("skill_slugs", ()) if str(item).strip()),
                        notes=str(failure.get("notes", "")).strip() or None,
                    )
                )
            write_failure_events(run_dir, tuple(events))
        return run_dir
    except IngestPayloadInvalidError as error:
        notes = str(error)
        _persist_ingest_failure_event(
            run_dir=run_dir_hint,
            payload_ref=payload_ref,
            failure_code="ingest_payload_invalid",
            notes=notes,
            skill_slugs=(),
        )
        raise
    except (ScheduleTurnCountMismatchError, ScheduleTurnOrderMismatchError, SlotMissingRequiredError, SlotInvalidConfidenceError, SynthesisPayloadInvalidError, IngestPayloadInvalidError) as error:
        selected_skill_slugs = _selected_skill_slugs_from_payload(payload_ref)
        failure_code = _map_ingest_failure_code(error)
        _persist_ingest_failure_event(
            run_dir=run_dir_hint,
            payload_ref=payload_ref,
            failure_code=failure_code,
            notes=str(error),
            skill_slugs=selected_skill_slugs,
        )
        raise
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as error:
        selected_skill_slugs = _selected_skill_slugs_from_payload(payload_ref)
        failure_code = _map_ingest_failure_code(error)
        _persist_ingest_failure_event(
            run_dir=run_dir_hint,
            payload_ref=payload_ref,
            failure_code=failure_code,
            notes=str(error),
            skill_slugs=selected_skill_slugs,
        )
        raise


def validate_session_run_payload(
    *,
    payload_ref: Path,
    repo_root: Path,
    strict_hash: bool = True,
) -> DispatchPayloadValidationReport:
    payload: dict[str, Any] | None = None
    try:
        payload = _read_ingest_payload(payload_ref)
        created_at = str(payload.get("created_at", "")).strip() or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        prepared = _prepare_ingest_trace(
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
            selected_skill_slugs=_selected_skill_slugs_from_payload(payload_ref),
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


def _read_ingest_payload(payload_ref: Path) -> dict[str, Any]:
    try:
        payload = json.loads(payload_ref.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise IngestPayloadInvalidError(f"Ingest payload file not found: {payload_ref}") from error
    except json.JSONDecodeError as error:
        raise IngestPayloadInvalidError(f"Ingest payload JSON is invalid: {error}") from error
    if not isinstance(payload, dict):
        raise IngestPayloadInvalidError("Ingest payload must be a JSON object")
    return payload


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
    session_spec = _best_effort_session_spec(payload_ref)
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
    if code == "schedule_turn_count_mismatch":
        expected: dict[str, Any] = {}
        schedule = _best_effort_schedule(session_spec)
        if schedule is not None:
            expected["turn_count"] = len(schedule)
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="turns",
                action="realign_turn_count",
                suggested_fix="Make the dispatched turns count match the canonical schedule exactly.",
                expected=expected or None,
            ),
        )
    if code == "schedule_turn_order_mismatch":
        expected = {}
        schedule = _best_effort_schedule(session_spec)
        if schedule is not None:
            expected["turn_schedule"] = schedule
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="turns[*].stage|round_index|skill_slug",
                action="realign_turn_order",
                suggested_fix="Reorder dispatched turns to match the canonical turn schedule from the session spec.",
                expected=expected or None,
            ),
        )
    if code == "synthesis_payload_invalid":
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="synthesis",
                action="fill_synthesis_contract",
                suggested_fix="Fill the synthesis object with the required keys and valid list/object shapes.",
                expected={
                    "required_keys": list(SYNTHESIS_REQUIRED_KEYS),
                    "strongest_objections_entry": {
                        "skill": "string",
                        "objection": "string",
                        "severity": "low|medium|high",
                    },
                    "skill_notes_entry": {
                        "skill": "string",
                        "note": "string",
                    },
                },
            ),
        )
    if code == "prompt_hash_mismatch":
        return (
            DispatchPayloadRepairHint(
                code=code,
                target="session_spec.participants[*].prompt_sha256",
                action="regenerate_session_artifacts",
                suggested_fix="Re-emit the session spec or dispatch template from the current skill files, or use --ignore-hash-mismatch intentionally.",
                expected={"source_of_truth": "SKILL.md"},
            ),
        )
    if code == "ingest_payload_invalid":
        return (_build_ingest_payload_invalid_hint(message, session_spec),)
    return ()


def _build_ingest_payload_invalid_hint(
    message: str,
    session_spec: dict[str, Any] | None,
) -> DispatchPayloadRepairHint:
    lowered = message.lower()
    if "non-empty prompt" in lowered:
        return DispatchPayloadRepairHint(
            code="ingest_payload_invalid",
            target="prompt",
            action="fill_prompt",
            suggested_fix="Provide a non-empty prompt at the payload top level or under task.prompt.",
        )
    if "synthesis object" in lowered:
        return DispatchPayloadRepairHint(
            code="ingest_payload_invalid",
            target="synthesis",
            action="provide_synthesis_object",
            suggested_fix="Provide a synthesis object with the required synthesis keys.",
            expected={"required_keys": list(SYNTHESIS_REQUIRED_KEYS)},
        )
    if "turns as a list" in lowered:
        expected: dict[str, Any] = {"type": "array"}
        schedule = _best_effort_schedule(session_spec)
        if schedule is not None:
            expected["turn_count"] = len(schedule)
        return DispatchPayloadRepairHint(
            code="ingest_payload_invalid",
            target="turns",
            action="provide_turn_list",
            suggested_fix="Provide turns as an ordered array aligned to the canonical schedule.",
            expected=expected,
        )
    if "session_spec or session_spec_path" in lowered:
        return DispatchPayloadRepairHint(
            code="ingest_payload_invalid",
            target="session_spec|session_spec_path|harness",
            action="provide_session_contract",
            suggested_fix="Provide an embedded session_spec, a session_spec_path, or a CouncilKit run trace/harness payload.",
        )
    if "json is invalid" in lowered or "json object" in lowered or "file not found" in lowered:
        return DispatchPayloadRepairHint(
            code="ingest_payload_invalid",
            target="payload",
            action="fix_payload_source",
            suggested_fix="Provide a readable JSON object file before validating or ingesting.",
        )
    return DispatchPayloadRepairHint(
        code="ingest_payload_invalid",
        target="payload",
        action="repair_payload",
        suggested_fix="Repair the payload so it satisfies the expected top-level dispatch contract.",
        expected=_expected_dispatch_contract(),
    )


def _build_validation_issues(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    payload_ref: Path,
    source_stage: str = "ingest",
) -> tuple[DispatchPayloadValidationIssue, ...]:
    if code == "slot_missing_required":
        return _build_slot_missing_issues(level=level, code=code, message=message, payload=payload, source_stage=source_stage)
    if code == "slot_invalid_confidence":
        return (_build_confidence_issue(level=level, code=code, message=message, payload=payload, source_stage=source_stage),)
    if code == "schedule_turn_count_mismatch":
        return (_build_turn_count_issue(level=level, code=code, message=message, payload=payload, payload_ref=payload_ref, source_stage=source_stage),)
    if code == "schedule_turn_order_mismatch":
        return (_build_turn_order_issue(level=level, code=code, message=message, payload=payload, payload_ref=payload_ref, source_stage=source_stage),)
    if code == "synthesis_payload_invalid":
        return (_build_synthesis_issue(level=level, code=code, message=message, payload=payload, source_stage=source_stage),)
    if code == "prompt_hash_mismatch":
        return (_build_prompt_hash_issue(level=level, code=code, message=message, payload=payload, source_stage=source_stage),)
    if code == "ingest_payload_invalid":
        return (_build_ingest_issue(level=level, code=code, message=message, payload=payload, source_stage=source_stage),)
    return (
        DispatchPayloadValidationIssue(
            level=level,
            code=code,
            message=message,
            source_stage=source_stage,
        ),
    )


def _best_effort_session_spec(payload_ref: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(payload_ref.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    session_spec = payload.get("session_spec")
    if isinstance(session_spec, dict):
        return session_spec
    harness = payload.get("harness")
    if isinstance(harness, dict):
        try:
            contract, admission = load_harness_payload(payload_ref)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return None
        return build_session_spec(harness=contract, admission=admission)
    return None


def _build_slot_missing_issues(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    source_stage: str,
) -> tuple[DispatchPayloadValidationIssue, ...]:
    match = re.search(r"turns\[(\d+)\] missing reduction slots: (.+)$", message)
    if not match:
        return (
            DispatchPayloadValidationIssue(
                level=level,
                code=code,
                message=message,
                source_stage=source_stage,
            ),
        )
    turn_index = int(match.group(1))
    missing_slots = [slot.strip() for slot in match.group(2).split(",") if slot.strip()]
    actual_turn = _turn_payload_at(payload, turn_index)
    issues: list[DispatchPayloadValidationIssue] = []
    for slot in missing_slots:
        issues.append(
            DispatchPayloadValidationIssue(
                level=level,
                code=code,
                message=message,
                source_stage=source_stage,
                turn_index=turn_index,
                field_path=f"turns[{turn_index - 1}].{slot}",
                expected=_expected_turn_field(slot),
                actual=None if actual_turn is None else actual_turn.get(slot),
            )
        )
    return tuple(issues)


def _build_confidence_issue(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    source_stage: str,
) -> DispatchPayloadValidationIssue:
    match = re.search(r"turns\[(\d+)\]\.confidence must be high, medium, or low \(got (.+)\)$", message)
    if not match:
        return DispatchPayloadValidationIssue(
            level=level,
            code=code,
            message=message,
            source_stage=source_stage,
            expected=list(ALLOWED_CONFIDENCE_LEVELS),
        )
    turn_index = int(match.group(1))
    actual_turn = _turn_payload_at(payload, turn_index)
    actual_confidence = None if actual_turn is None else actual_turn.get("confidence")
    return DispatchPayloadValidationIssue(
        level=level,
        code=code,
        message=message,
        source_stage=source_stage,
        turn_index=turn_index,
        field_path=f"turns[{turn_index - 1}].confidence",
        expected=list(ALLOWED_CONFIDENCE_LEVELS),
        actual=actual_confidence,
    )


def _build_turn_count_issue(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    payload_ref: Path,
    source_stage: str,
) -> DispatchPayloadValidationIssue:
    schedule = _best_effort_schedule(_payload_session_spec(payload, payload_ref))
    turns = _extract_turn_payloads(payload) if payload is not None else None
    actual_count = len(turns) if isinstance(turns, list) else None
    expected_count = len(schedule) if schedule is not None else None
    return DispatchPayloadValidationIssue(
        level=level,
        code=code,
        message=message,
        source_stage=source_stage,
        field_path="turns",
        expected={"count": expected_count} if expected_count is not None else None,
        actual={"count": actual_count} if actual_count is not None else None,
    )


def _build_turn_order_issue(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    payload_ref: Path,
    source_stage: str,
) -> DispatchPayloadValidationIssue:
    match = re.search(r"index (\d+): expected", message)
    turn_index = int(match.group(1)) if match else None
    schedule = _best_effort_schedule(_payload_session_spec(payload, payload_ref))
    expected = None
    actual = None
    field_path = None
    if turn_index is not None:
        field_path = f"turns[{turn_index - 1}]"
        if schedule is not None and 0 < turn_index <= len(schedule):
            expected = schedule[turn_index - 1]
        actual_turn = _turn_payload_at(payload, turn_index)
        if actual_turn is not None:
            actual = {
                "stage": actual_turn.get("stage"),
                "round_index": actual_turn.get("round_index"),
                "skill_slug": actual_turn.get("skill_slug"),
            }
    return DispatchPayloadValidationIssue(
        level=level,
        code=code,
        message=message,
        source_stage=source_stage,
        turn_index=turn_index,
        field_path=field_path,
        expected=expected,
        actual=actual,
    )


def _build_synthesis_issue(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    source_stage: str,
) -> DispatchPayloadValidationIssue:
    synthesis = payload.get("synthesis") if isinstance(payload, dict) and isinstance(payload.get("synthesis"), dict) else {}
    missing_key = re.search(r"Synthesis payload missing or empty key: ([a-z_]+)$", message)
    if missing_key:
        key = missing_key.group(1)
        return DispatchPayloadValidationIssue(
            level=level,
            code=code,
            message=message,
            source_stage=source_stage,
            field_path=f"synthesis.{key}",
            expected=_expected_synthesis_field(key),
            actual=synthesis.get(key),
        )
    for key in SYNTHESIS_REQUIRED_KEYS:
        if key in message:
            return DispatchPayloadValidationIssue(
                level=level,
                code=code,
                message=message,
                source_stage=source_stage,
                field_path=f"synthesis.{key}",
                expected=_expected_synthesis_field(key),
                actual=synthesis.get(key),
            )
    return DispatchPayloadValidationIssue(
        level=level,
        code=code,
        message=message,
        source_stage=source_stage,
        field_path="synthesis",
    )


def _build_prompt_hash_issue(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    source_stage: str,
) -> DispatchPayloadValidationIssue:
    participant_match = re.search(r"participant '([^']+)' prompt hash mismatch: expected ([a-f0-9]+), got ([a-f0-9]+)", message)
    field_path = "session_spec.participants[*].prompt_sha256"
    expected = None
    actual = None
    if participant_match:
        slug, expected_hash, actual_hash = participant_match.groups()
        expected = {"skill_slug": slug, "prompt_sha256": expected_hash}
        actual = {"skill_slug": slug, "prompt_sha256": actual_hash}
    return DispatchPayloadValidationIssue(
        level=level,
        code=code,
        message=message,
        source_stage=source_stage,
        field_path=field_path,
        expected=expected,
        actual=actual,
    )


def _build_ingest_issue(
    *,
    level: str,
    code: str,
    message: str,
    payload: dict[str, Any] | None,
    source_stage: str,
) -> DispatchPayloadValidationIssue:
    lowered = message.lower()
    field_path = "payload"
    expected: Any | None = None
    actual: Any | None = None
    if "non-empty prompt" in lowered:
        field_path = "prompt"
        expected = {"type": "non-empty string"}
        actual = None if payload is None else payload.get("prompt")
    elif "synthesis object" in lowered:
        field_path = "synthesis"
        expected = {"type": "object", "required_keys": list(SYNTHESIS_REQUIRED_KEYS)}
        actual = None if payload is None else type(payload.get("synthesis")).__name__
    elif "turns as a list" in lowered:
        field_path = "turns"
        expected = {"type": "array"}
        actual = None if payload is None else type(payload.get("turns")).__name__
    elif "session_spec or session_spec_path" in lowered:
        field_path = "session_spec|session_spec_path|harness"
        expected = {"one_of": ["session_spec", "session_spec_path", "harness"]}
    return DispatchPayloadValidationIssue(
        level=level,
        code=code,
        message=message,
        source_stage=source_stage,
        field_path=field_path,
        expected=expected,
        actual=actual,
    )


def _best_effort_schedule(session_spec: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if session_spec is None:
        return None
    try:
        schedule = resolve_turn_schedule(session_spec)
    except (ValueError, IngestPayloadInvalidError, ScheduleTurnCountMismatchError, ScheduleTurnOrderMismatchError):
        return None
    return [
        {
            "turn_index": turn.turn_index,
            "stage": turn.stage,
            "round_index": turn.round_index,
            "skill_slug": turn.skill_slug,
            "skill_name": turn.skill_name,
        }
        for turn in schedule
    ]


def _payload_session_spec(payload: dict[str, Any] | None, payload_ref: Path) -> dict[str, Any] | None:
    if payload is None:
        return _best_effort_session_spec(payload_ref)
    session_spec = payload.get("session_spec")
    if isinstance(session_spec, dict):
        return session_spec
    harness = payload.get("harness")
    if isinstance(harness, dict):
        try:
            contract, admission = load_harness_payload(payload_ref)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return None
        return build_session_spec(harness=contract, admission=admission)
    return _best_effort_session_spec(payload_ref)


def _turn_payload_at(payload: dict[str, Any] | None, turn_index: int) -> dict[str, Any] | None:
    if payload is None:
        return None
    turns = _extract_turn_payloads(payload)
    if not isinstance(turns, list) or turn_index < 1 or turn_index > len(turns):
        return None
    turn = turns[turn_index - 1]
    return turn if isinstance(turn, dict) else None


def _expected_turn_field(slot: str) -> dict[str, Any]:
    if slot in {"evidence", "needs_verification"}:
        return {"type": "array"}
    if slot == "confidence":
        return {"type": "string", "allowed_values": list(ALLOWED_CONFIDENCE_LEVELS)}
    return {"type": "string"}


def _expected_synthesis_field(key: str) -> dict[str, Any]:
    if key in {"key_decisions", "next_steps", "open_questions"}:
        return {"type": "array"}
    if key == "strongest_objections":
        return {
            "type": "array",
            "entry_shape": {
                "skill": "string",
                "objection": "string",
                "severity": "low|medium|high",
            },
        }
    if key == "skill_notes":
        return {
            "type": "array",
            "entry_shape": {
                "skill": "string",
                "note": "string",
            },
        }
    return {"type": "string", "non_empty": True}


def _prepare_ingest_trace(
    *,
    payload: dict[str, Any],
    payload_ref: Path,
    repo_root: Path,
    strict_hash: bool,
    created_at: str,
) -> PreparedIngestTrace:
    try:
        session_spec = _load_session_spec(payload, payload_ref=payload_ref)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as error:
        raise IngestPayloadInvalidError(str(error)) from error

    synthesis_payload = payload.get("synthesis")
    schedule = resolve_turn_schedule(session_spec)
    skill_instances, pending_failures = _load_skill_instances_from_session_spec(
        session_spec,
        strict_hash=strict_hash,
        repo_root=repo_root,
        payload_ref=payload_ref,
    )
    dispatched_turns = _load_dispatched_turns(_extract_turn_payloads(payload), schedule=schedule)
    turn_records = to_turn_records(dispatched_turns, skill_instances=skill_instances)

    if not isinstance(synthesis_payload, dict):
        raise IngestPayloadInvalidError("Ingest payload requires synthesis object")
    synthesis = normalize_synthesis_payload(synthesis_payload)

    admission = _load_admission(payload, session_spec)
    if admission.status == "needs_clarification":
        pending_failures.append(
            {
                "source_stage": "admission",
                "failure_code": "admission_needs_clarification",
                "deterministic": True,
                "skill_slugs": tuple(admission.selected_skills),
                "notes": admission.reason,
            }
        )
    elif admission.status == "out_of_scope":
        pending_failures.append(
            {
                "source_stage": "admission",
                "failure_code": "admission_out_of_scope",
                "deterministic": True,
                "skill_slugs": tuple(admission.selected_skills),
                "notes": admission.reason,
            }
        )
    harness = _build_harness_contract_from_session_spec(
        session_spec=session_spec,
        skill_instances=skill_instances,
        admission_status=admission.status,
    )

    task_payload = payload.get("task", {})
    if not isinstance(task_payload, dict):
        task_payload = {}

    prompt = str(payload.get("prompt", "")).strip() or str(task_payload.get("prompt", "")).strip()
    if not prompt:
        raise IngestPayloadInvalidError("Ingest payload requires non-empty prompt")
    mode = str(session_spec.get("mode", "")).strip() or str(task_payload.get("mode", "review")).strip() or "review"
    project_root_raw = str(payload.get("project_root", "")).strip() or str(task_payload.get("project_root", "")).strip()
    if not project_root_raw:
        project_root_raw = str(repo_root)
    project_root = resolve_contract_path(
        project_root_raw,
        repo_root=repo_root,
        contract_ref=payload_ref,
    )
    shared_brief = str(payload.get("shared_brief", "")).strip() or str(task_payload.get("shared_brief", "")).strip()
    if not shared_brief:
        shared_brief = "Imported external harness run."
    tool_grants_payload = payload.get("tool_grants")
    if not isinstance(tool_grants_payload, list):
        tool_grants_payload = task_payload.get("tool_grants", [])
    tool_grants = tuple(str(item).strip() for item in tool_grants_payload if str(item).strip())
    trace = RunTrace(
        task=TaskEnvelope(
            prompt=prompt,
            mode=mode,
            project_root=project_root.resolve() if project_root.exists() else project_root,
            shared_brief=shared_brief,
            tool_grants=tool_grants,
        ),
        skills=skill_instances,
        turns=turn_records,
        synthesis=synthesis,
        created_at=created_at,
        admission=admission,
        harness=harness,
        source_kind="raw",
    )
    model = str(payload.get("model", "")).strip() or None
    base_url = str(payload.get("base_url", "")).strip() or None
    return PreparedIngestTrace(
        trace=trace,
        pending_failures=tuple(pending_failures),
        model=model,
        base_url=base_url,
    )


def _selected_skill_slugs_from_payload(payload_ref: Path) -> tuple[str, ...]:
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


def _extract_turn_payloads(payload: dict[str, Any]) -> object:
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


def _load_session_spec(payload: dict[str, object], *, payload_ref: Path) -> dict[str, Any]:
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


def _load_skill_instances_from_session_spec(
    session_spec: dict[str, Any],
    *,
    strict_hash: bool,
    repo_root: Path,
    payload_ref: Path,
) -> tuple[tuple[SkillInstance, ...], list[dict[str, Any]]]:
    participants = session_spec.get("participants")
    if not isinstance(participants, list) or not participants:
        raise ValueError("session_spec.participants must be a non-empty list")

    participant_map: dict[str, dict[str, Any]] = {}
    for item in participants:
        if not isinstance(item, dict):
            raise ValueError("session_spec.participants entries must be objects")
        slug = str(item.get("slug", "")).strip()
        if not slug:
            raise ValueError("session_spec.participants entries require slug")
        participant_map[slug] = item

    loaded_slugs = session_spec.get("loaded_skill_slugs")
    if isinstance(loaded_slugs, list) and loaded_slugs:
        ordered_slugs = [str(item).strip() for item in loaded_slugs if str(item).strip()]
    else:
        ordered_slugs = [str(item.get("slug", "")).strip() for item in participants]

    instances: list[SkillInstance] = []
    pending_failures: list[dict[str, Any]] = []
    for slug in ordered_slugs:
        item = participant_map.get(slug)
        if item is None:
            raise ValueError(f"Participant slug not found in session_spec.participants: {slug}")
        spec, hash_mismatch = _build_skill_spec_from_participant(
            item,
            strict_hash=strict_hash,
            repo_root=repo_root,
            payload_ref=payload_ref,
        )
        if hash_mismatch:
            pending_failures.append(
                {
                    "source_stage": "ingest",
                    "failure_code": "prompt_hash_mismatch",
                    "deterministic": True,
                    "skill_slugs": (spec.slug,),
                    "notes": f"Hash mismatch accepted in non-strict mode for participant '{spec.slug}'.",
                }
            )
        instances.append(SkillInstance(spec=spec, instance_id=f"{spec.slug}-instance"))
    return tuple(instances), pending_failures


def _build_skill_spec_from_participant(
    participant: dict[str, Any],
    *,
    strict_hash: bool,
    repo_root: Path,
    payload_ref: Path,
) -> tuple[SkillSpec, bool]:
    slug = str(participant.get("slug", "")).strip()
    if not slug:
        raise ValueError("Participant entry requires slug")
    skill_file_raw = str(participant.get("skill_file", "")).strip()
    if not skill_file_raw:
        raise ValueError(f"Participant '{slug}' requires skill_file")

    skill_file = resolve_contract_path(
        skill_file_raw,
        repo_root=repo_root,
        contract_ref=payload_ref,
        prefer_reference=True,
    )
    if not skill_file.exists():
        raise FileNotFoundError(f"Skill file not found for participant '{slug}': {skill_file}")
    skill_markdown = skill_file.read_text(encoding="utf-8").strip()

    expected_hash = str(participant.get("prompt_sha256", "")).strip()
    hash_mismatch = False
    if expected_hash:
        current_hash = sha256(skill_markdown.encode("utf-8")).hexdigest()
        if current_hash != expected_hash and strict_hash:
            raise ValueError(
                f"Participant '{slug}' prompt hash mismatch: expected {expected_hash}, got {current_hash}"
            )
        if current_hash != expected_hash and not strict_hash:
            hash_mismatch = True

    frontmatter = parse_frontmatter(skill_markdown)
    title_match = re.search(r"^#\s+(.+)$", skill_markdown, flags=re.MULTILINE)
    tagline_match = re.search(r"^>\s+(.+)$", skill_markdown, flags=re.MULTILINE)
    name = str(participant.get("name", "")).strip() or (title_match.group(1).strip() if title_match else slug)
    return (
        SkillSpec(
            slug=slug,
            name=name,
            description=frontmatter.get("description", "").strip(),
            tagline=tagline_match.group(1).strip() if tagline_match else "",
            skill_markdown=skill_markdown,
            skill_dir=skill_file.parent,
            skill_file=skill_file,
            skill_mtime=skill_file.stat().st_mtime,
        ),
        hash_mismatch,
    )
def _load_dispatched_turns(
    payload: object,
    *,
    schedule: tuple,
) -> tuple[DispatchedTurn, ...]:
    if not isinstance(payload, list):
        raise IngestPayloadInvalidError("Ingest payload requires turns as a list")
    if len(payload) != len(schedule):
        raise ScheduleTurnCountMismatchError(
            f"Turn count mismatch: expected {len(schedule)} turns from session_spec, got {len(payload)}"
        )

    dispatched: list[DispatchedTurn] = []
    for index, (raw_turn, expected) in enumerate(zip(payload, schedule, strict=False), start=1):
        if not isinstance(raw_turn, dict):
            raise IngestPayloadInvalidError(f"turns[{index}] must be an object")

        stage = str(raw_turn.get("stage", expected.stage)).strip() or expected.stage
        round_index = int(raw_turn.get("round_index", expected.round_index))
        skill_slug = str(raw_turn.get("skill_slug", expected.skill_slug)).strip() or expected.skill_slug
        if stage != expected.stage or round_index != expected.round_index or skill_slug != expected.skill_slug:
            raise ScheduleTurnOrderMismatchError(
                "Turn sequence mismatch at index "
                f"{index}: expected ({expected.stage}, round {expected.round_index}, {expected.skill_slug})"
            )
        try:
            message, result = normalize_dispatch_payload(raw_turn)
        except SlotMissingRequiredError as error:
            missing = re.search(r"Dispatcher payload missing reduction slots: (.+)$", str(error))
            detail = missing.group(1) if missing else str(error)
            raise SlotMissingRequiredError(f"turns[{index}] missing reduction slots: {detail}") from error
        except SlotInvalidConfidenceError as error:
            actual = str(raw_turn.get("confidence", "")).strip() or "<empty>"
            raise SlotInvalidConfidenceError(
                f"turns[{index}].confidence must be high, medium, or low (got {actual})"
            ) from error
        except ValueError as error:
            raise IngestPayloadInvalidError(f"turns[{index}] invalid: {error}") from error
        dispatched.append(DispatchedTurn(turn=expected, message=message, result=result))
    return tuple(dispatched)


def _load_admission(payload: dict[str, Any], session_spec: dict[str, Any]) -> AdmissionResult:
    admission_payload = payload.get("admission")
    if isinstance(admission_payload, dict):
        return parse_admission_result(admission_payload)

    session_admission = session_spec.get("admission", {})
    if not isinstance(session_admission, dict):
        session_admission = {}
    selected = tuple(
        str(item).strip()
        for item in session_spec.get("selected_skill_slugs", [])
        if str(item).strip()
    )
    warnings = tuple(
        str(item).strip()
        for item in session_admission.get("warnings", [])
        if str(item).strip()
    )
    status = str(session_admission.get("status", "")).strip() or "accept"
    return AdmissionResult(
        status=status,
        reason=f"Imported from external harness session spec with status '{status}'.",
        candidate_skills=(),
        selected_skills=selected,
        warnings=warnings,
    )


def _build_harness_contract_from_session_spec(
    *,
    session_spec: dict[str, Any],
    skill_instances: tuple[SkillInstance, ...],
    admission_status: str,
) -> HarnessContract:
    stage_payload = session_spec.get("stages", [])
    if not isinstance(stage_payload, list):
        stage_payload = []
    stage_order = tuple(str(item.get("stage", "")).strip() for item in stage_payload if isinstance(item, dict))
    rounds_per_stage = {
        str(item.get("stage", "")).strip(): int(item.get("rounds", 0))
        for item in stage_payload
        if isinstance(item, dict) and str(item.get("stage", "")).strip()
    }

    participant_payload = session_spec.get("participants", [])
    participant_map = {
        str(item.get("slug", "")).strip(): item
        for item in participant_payload
        if isinstance(item, dict) and str(item.get("slug", "")).strip()
    }
    skills = []
    for instance in skill_instances:
        participant = participant_map.get(instance.spec.slug, {})
        if not isinstance(participant, dict):
            participant = {}
        skills.append(
            HarnessSkillContract(
                slug=instance.spec.slug,
                name=instance.spec.name,
                skill_file=str(instance.spec.skill_file),
                skill_mtime=instance.spec.skill_mtime,
                prompt_sha256=str(participant.get("prompt_sha256", "")).strip()
                or sha256(instance.spec.skill_markdown.encode("utf-8")).hexdigest(),
            )
        )

    return HarnessContract(
        version=str(session_spec.get("version", "")).strip() or "v1",
        source_of_truth=str(session_spec.get("source_of_truth", "")).strip() or "SKILL.md",
        prompt_contract=str(session_spec.get("prompt_contract", "")).strip()
        or "SKILL.md acts as prompt, persona, and reasoning contract.",
        reduction_slots=REDUCTION_SLOTS,
        mode=str(session_spec.get("mode", "")).strip() or "review",
        stage_order=stage_order,
        rounds_per_stage=rounds_per_stage,
        selected_skill_slugs=tuple(
            str(item).strip()
            for item in session_spec.get("selected_skill_slugs", [])
            if str(item).strip()
        ),
        loaded_skill_slugs=tuple(
            str(item).strip()
            for item in session_spec.get("loaded_skill_slugs", [])
            if str(item).strip()
        ),
        skills=tuple(skills),
        admission_status=admission_status,
    )


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
    if "prompt hash mismatch" in str(error).lower():
        return "prompt_hash_mismatch"
    return "ingest_payload_invalid"


def _persist_ingest_failure_event(
    *,
    run_dir: Path,
    payload_ref: Path,
    failure_code: str,
    notes: str,
    skill_slugs: tuple[str, ...],
) -> None:
    event = create_failure_event(
        run_ref=str(run_dir / "run.json"),
        source_stage="ingest",
        failure_code=failure_code,
        repro_ref=str(payload_ref),
        deterministic=True,
        skill_slugs=skill_slugs,
        notes=notes,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    write_failure_events(run_dir, (event,))
