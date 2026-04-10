from __future__ import annotations

from hashlib import sha256

from .models import AdmissionResult, HarnessContract, HarnessSkillContract, SkillInstance
from .modes import ModeSpec

CONTRACT_VERSION = "v1"
SOURCE_OF_TRUTH = "SKILL.md"
PROMPT_CONTRACT = "SKILL.md acts as prompt, persona, and reasoning contract."
REDUCTION_SLOTS = (
    "judgment",
    "evidence",
    "tradeoff",
    "objection",
    "needs_verification",
    "confidence",
)


def build_harness_contract(
    *,
    mode: str,
    mode_spec: ModeSpec,
    skill_instances: tuple[SkillInstance, ...],
    admission: AdmissionResult,
) -> HarnessContract:
    skill_contracts = tuple(
        HarnessSkillContract(
            slug=skill.spec.slug,
            name=skill.spec.name,
            skill_file=str(skill.spec.skill_file),
            skill_mtime=skill.spec.skill_mtime,
            prompt_sha256=sha256(skill.spec.skill_markdown.encode("utf-8")).hexdigest(),
        )
        for skill in skill_instances
    )
    loaded_slugs = tuple(skill.spec.slug for skill in skill_instances)
    return HarnessContract(
        version=CONTRACT_VERSION,
        source_of_truth=SOURCE_OF_TRUTH,
        prompt_contract=PROMPT_CONTRACT,
        reduction_slots=REDUCTION_SLOTS,
        mode=mode,
        stage_order=mode_spec.stages,
        rounds_per_stage=dict(mode_spec.rounds_per_stage),
        selected_skill_slugs=admission.selected_skills,
        loaded_skill_slugs=loaded_slugs,
        skills=skill_contracts,
        admission_status=admission.status,
    )
