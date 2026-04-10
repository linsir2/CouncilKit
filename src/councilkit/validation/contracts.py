from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from ..harness_contract import REDUCTION_SLOTS, SOURCE_OF_TRUTH
from ..models import HarnessContract


@dataclass(frozen=True)
class ContractValidationIssue:
    level: str
    code: str
    message: str
    skill_slug: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
        }
        if self.skill_slug:
            payload["skill_slug"] = self.skill_slug
        return payload


@dataclass(frozen=True)
class ContractValidationReport:
    status: str
    issues: tuple[ContractValidationIssue, ...]
    checked_skills: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "issues": [item.to_dict() for item in self.issues],
            "checked_skills": list(self.checked_skills),
        }


def validate_harness_contract(
    harness: HarnessContract,
    *,
    strict_hash: bool,
    resolve_skill_path: Callable[[str], Path],
) -> ContractValidationReport:
    issues: list[ContractValidationIssue] = []

    def add_issue(level: str, code: str, message: str, skill_slug: str | None = None) -> None:
        issues.append(ContractValidationIssue(level=level, code=code, message=message, skill_slug=skill_slug))

    if harness.source_of_truth != SOURCE_OF_TRUTH:
        add_issue(
            "error",
            "invalid_source_of_truth",
            f"Expected source_of_truth='{SOURCE_OF_TRUTH}', got '{harness.source_of_truth}'.",
        )

    if tuple(harness.reduction_slots) != REDUCTION_SLOTS:
        add_issue(
            "error",
            "invalid_reduction_slots",
            "Reduction slots must match the v1 six-slot contract in canonical order.",
        )

    stage_set = set(harness.stage_order)
    if "synthesis" not in stage_set:
        add_issue("warning", "missing_synthesis_stage", "Stage order should include synthesis.")

    expected_round_keys = {stage for stage in harness.stage_order if stage != "synthesis"}
    round_keys = set(harness.rounds_per_stage.keys())
    if round_keys != expected_round_keys:
        add_issue(
            "warning",
            "rounds_per_stage_mismatch",
            "rounds_per_stage keys should match stage_order excluding synthesis.",
        )

    loaded_set = set(harness.loaded_skill_slugs)
    for slug in harness.selected_skill_slugs:
        if slug not in loaded_set:
            add_issue(
                "error",
                "selected_skill_not_loaded",
                "Selected skill is missing from loaded skill slugs.",
                skill_slug=slug,
            )

    skill_map = {skill.slug: skill for skill in harness.skills}
    for slug in harness.loaded_skill_slugs:
        if slug not in skill_map:
            add_issue(
                "error",
                "loaded_skill_missing_contract_entry",
                "Loaded skill slug has no matching harness skill entry.",
                skill_slug=slug,
            )

    for skill in harness.skills:
        if not skill.skill_file:
            add_issue("error", "missing_skill_file", "Skill entry has empty skill_file.", skill_slug=skill.slug)
            continue

        skill_path = resolve_skill_path(skill.skill_file)
        if not skill_path.exists():
            add_issue(
                "error",
                "skill_file_not_found",
                f"Skill file not found at '{skill.skill_file}'.",
                skill_slug=skill.slug,
            )
            continue

        content = skill_path.read_text(encoding="utf-8").strip()
        digest = sha256(content.encode("utf-8")).hexdigest()
        if digest != skill.prompt_sha256:
            add_issue(
                "error" if strict_hash else "warning",
                "prompt_hash_mismatch",
                "Current skill file content hash does not match prompt_sha256 in contract.",
                skill_slug=skill.slug,
            )

    has_error = any(item.level == "error" for item in issues)
    has_warning = any(item.level == "warning" for item in issues)
    if has_error:
        status = "fail"
    elif has_warning:
        status = "pass_with_warning"
    else:
        status = "pass"

    return ContractValidationReport(
        status=status,
        issues=tuple(issues),
        checked_skills=tuple(skill.slug for skill in harness.skills),
    )
