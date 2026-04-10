from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import RunTrace


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
        from .reporting import (
            _build_recommended_repair_order,
            _expected_dispatch_contract,
            _group_issues_by_section,
            _group_issues_by_turn,
        )

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
