from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillSpec:
    slug: str
    name: str
    description: str
    tagline: str
    skill_markdown: str
    skill_dir: Path
    skill_file: Path
    skill_mtime: float | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "tagline": self.tagline,
            "path": str(self.skill_dir),
            "skill_file": str(self.skill_file),
            "skill_mtime": self.skill_mtime if self.skill_mtime is not None else self.skill_file.stat().st_mtime,
        }


@dataclass(frozen=True)
class SkillInstance:
    spec: SkillSpec
    instance_id: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            **self.spec.snapshot(),
        }


@dataclass(frozen=True)
class TaskEnvelope:
    prompt: str
    mode: str
    project_root: Path
    shared_brief: str
    tool_grants: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "mode": self.mode,
            "project_root": str(self.project_root),
            "shared_brief": self.shared_brief,
            "tool_grants": list(self.tool_grants),
        }


@dataclass(frozen=True)
class AdmissionCandidate:
    slug: str
    name: str
    score: int
    matched_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class RejectedSkill:
    slug: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "slug": self.slug,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AdmissionResult:
    status: str
    reason: str
    candidate_skills: tuple[AdmissionCandidate, ...]
    selected_skills: tuple[str, ...]
    rejected_skills: tuple[RejectedSkill, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "candidate_skills": [item.to_dict() for item in self.candidate_skills],
            "selected_skills": list(self.selected_skills),
            "rejected_skills": [item.to_dict() for item in self.rejected_skills],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class HarnessSkillContract:
    slug: str
    name: str
    skill_file: str
    skill_mtime: float | None
    prompt_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "skill_file": self.skill_file,
            "skill_mtime": self.skill_mtime,
            "prompt_sha256": self.prompt_sha256,
        }


@dataclass(frozen=True)
class HarnessContract:
    version: str
    source_of_truth: str
    prompt_contract: str
    reduction_slots: tuple[str, ...]
    mode: str
    stage_order: tuple[str, ...]
    rounds_per_stage: dict[str, int]
    selected_skill_slugs: tuple[str, ...]
    loaded_skill_slugs: tuple[str, ...]
    skills: tuple[HarnessSkillContract, ...]
    admission_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_of_truth": self.source_of_truth,
            "prompt_contract": self.prompt_contract,
            "reduction_slots": list(self.reduction_slots),
            "mode": self.mode,
            "stage_order": list(self.stage_order),
            "rounds_per_stage": dict(self.rounds_per_stage),
            "selected_skill_slugs": list(self.selected_skill_slugs),
            "loaded_skill_slugs": list(self.loaded_skill_slugs),
            "skills": [skill.to_dict() for skill in self.skills],
            "admission_status": self.admission_status,
        }


@dataclass(frozen=True)
class ContextFrame:
    stage: str
    round_index: int
    total_rounds: int
    shared_brief: str
    skill_brief: str
    prior_turns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "round_index": self.round_index,
            "total_rounds": self.total_rounds,
            "shared_brief": self.shared_brief,
            "skill_brief": self.skill_brief,
            "prior_turns": list(self.prior_turns),
        }


@dataclass(frozen=True)
class PatchProposal:
    target: str
    change: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "target": self.target,
            "change": self.change,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TurnResult:
    judgment: str
    evidence: tuple[str, ...]
    tradeoff: str
    objection: str
    needs_verification: tuple[str, ...]
    confidence: str
    patch_proposals: tuple[PatchProposal, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "judgment": self.judgment,
            "evidence": list(self.evidence),
            "tradeoff": self.tradeoff,
            "objection": self.objection,
            "needs_verification": list(self.needs_verification),
            "confidence": self.confidence,
            "patch_proposals": [proposal.to_dict() for proposal in self.patch_proposals],
        }


@dataclass(frozen=True)
class TurnRecord:
    stage: str
    round_index: int
    skill_instance_id: str
    skill_name: str
    message: str
    result: TurnResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "round_index": self.round_index,
            "skill_instance_id": self.skill_instance_id,
            "skill_name": self.skill_name,
            "message": self.message,
            "result": self.result.to_dict(),
        }


@dataclass(frozen=True)
class SynthesisResult:
    title: str
    summary: str
    decision: str
    key_decisions: tuple[str, ...]
    strongest_objections: tuple[dict[str, str], ...]
    next_steps: tuple[str, ...]
    open_questions: tuple[str, ...]
    skill_notes: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "decision": self.decision,
            "key_decisions": list(self.key_decisions),
            "strongest_objections": [dict(item) for item in self.strongest_objections],
            "next_steps": list(self.next_steps),
            "open_questions": list(self.open_questions),
            "skill_notes": [dict(item) for item in self.skill_notes],
        }


@dataclass(frozen=True)
class RunTrace:
    task: TaskEnvelope
    skills: tuple[SkillInstance, ...]
    turns: tuple[TurnRecord, ...]
    synthesis: SynthesisResult
    created_at: str
    admission: AdmissionResult | None = None
    harness: HarnessContract | None = None
    source_kind: str = "raw"

    def to_dict(self, *, model: str | None, base_url: str | None) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "created_at": self.created_at,
            "task": self.task.to_dict(),
            "skills": [skill.snapshot() for skill in self.skills],
            "admission": self.admission.to_dict() if self.admission is not None else None,
            "harness": self.harness.to_dict() if self.harness is not None else None,
            "turn_count": len(self.turns) + 1,
            "turns": [turn.to_dict() for turn in self.turns],
            "synthesis": self.synthesis.to_dict(),
            "model": model,
            "base_url": base_url,
        }
