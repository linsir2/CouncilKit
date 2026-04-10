from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .harness_contract import REDUCTION_SLOTS, SOURCE_OF_TRUTH
from .models import AdmissionCandidate, AdmissionResult, HarnessContract, HarnessSkillContract, RejectedSkill


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


def load_harness_payload(contract_ref: Path) -> tuple[HarnessContract, AdmissionResult | None]:
    candidate = contract_ref / "run.json" if contract_ref.is_dir() else contract_ref
    if not candidate.exists():
        raise FileNotFoundError(f"Harness contract file not found: {candidate}")

    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Harness contract payload must be a JSON object")

    if _looks_like_harness_contract(payload):
        harness_payload = payload
        admission_payload = None
    else:
        harness_payload = payload.get("harness")
        admission_payload = payload.get("admission")
        if not isinstance(harness_payload, dict):
            raise ValueError("Payload does not contain a valid harness contract section")

    harness = parse_harness_contract(harness_payload)
    admission = parse_admission_result(admission_payload) if isinstance(admission_payload, dict) else None
    return harness, admission


def resolve_contract_path(
    raw_path: str,
    *,
    repo_root: Path | None = None,
    contract_ref: Path | None = None,
    prefer_reference: bool = False,
) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate

    if contract_ref is not None:
        reference_root = contract_ref if contract_ref.is_dir() else contract_ref.parent
    else:
        reference_root = None

    search_roots: list[Path] = []
    if prefer_reference and reference_root is not None:
        search_roots.append(reference_root)
    if repo_root is not None:
        search_roots.append(repo_root)
    if not prefer_reference and reference_root is not None:
        search_roots.append(reference_root)

    resolved_candidates = [root / candidate for root in search_roots]
    for resolved in resolved_candidates:
        if resolved.exists():
            return resolved.resolve()
    if resolved_candidates:
        return resolved_candidates[0]
    return candidate


def parse_harness_contract(payload: dict[str, object]) -> HarnessContract:
    rounds_payload = payload.get("rounds_per_stage", {})
    if not isinstance(rounds_payload, dict):
        rounds_payload = {}

    skills = tuple(
        HarnessSkillContract(
            slug=str(item.get("slug", "")).strip(),
            name=str(item.get("name", "")).strip(),
            skill_file=str(item.get("skill_file", "")).strip(),
            skill_mtime=float(item["skill_mtime"]) if item.get("skill_mtime") is not None else None,
            prompt_sha256=str(item.get("prompt_sha256", "")).strip(),
        )
        for item in payload.get("skills", [])
        if isinstance(item, dict)
    )
    return HarnessContract(
        version=str(payload.get("version", "")).strip(),
        source_of_truth=str(payload.get("source_of_truth", "")).strip(),
        prompt_contract=str(payload.get("prompt_contract", "")).strip(),
        reduction_slots=tuple(str(item).strip() for item in payload.get("reduction_slots", []) if str(item).strip()),
        mode=str(payload.get("mode", "")).strip(),
        stage_order=tuple(str(item).strip() for item in payload.get("stage_order", []) if str(item).strip()),
        rounds_per_stage={
            str(key).strip(): int(value)
            for key, value in rounds_payload.items()
            if str(key).strip()
        },
        selected_skill_slugs=tuple(
            str(item).strip() for item in payload.get("selected_skill_slugs", []) if str(item).strip()
        ),
        loaded_skill_slugs=tuple(
            str(item).strip() for item in payload.get("loaded_skill_slugs", []) if str(item).strip()
        ),
        skills=skills,
        admission_status=str(payload.get("admission_status", "")).strip(),
    )


def parse_admission_result(payload: dict[str, object]) -> AdmissionResult:
    candidates = tuple(
        AdmissionCandidate(
            slug=str(item.get("slug", "")).strip(),
            name=str(item.get("name", "")).strip(),
            score=int(item.get("score", 0)),
            matched_terms=tuple(
                str(term).strip() for term in item.get("matched_terms", []) if str(term).strip()
            ),
        )
        for item in payload.get("candidate_skills", [])
        if isinstance(item, dict)
    )
    rejected = tuple(
        RejectedSkill(
            slug=str(item.get("slug", "")).strip(),
            reason=str(item.get("reason", "")).strip(),
        )
        for item in payload.get("rejected_skills", [])
        if isinstance(item, dict)
    )
    selected = tuple(str(item).strip() for item in payload.get("selected_skills", []) if str(item).strip())
    warnings = tuple(str(item).strip() for item in payload.get("warnings", []) if str(item).strip())
    return AdmissionResult(
        status=str(payload.get("status", "")).strip(),
        reason=str(payload.get("reason", "")).strip(),
        candidate_skills=candidates,
        selected_skills=selected,
        rejected_skills=rejected,
        warnings=warnings,
    )


def validate_harness_contract(
    harness: HarnessContract,
    *,
    strict_hash: bool = True,
    repo_root: Path | None = None,
    contract_ref: Path | None = None,
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

        skill_path = resolve_contract_path(
            skill.skill_file,
            repo_root=repo_root,
            contract_ref=contract_ref,
            prefer_reference=True,
        )
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


def _looks_like_harness_contract(payload: dict[str, object]) -> bool:
    return "version" in payload and "source_of_truth" in payload and "skills" in payload
