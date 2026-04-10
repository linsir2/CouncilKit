from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..admission import prepare_session
from ..harness_contract import build_harness_contract
from ..loader import load_prompt, load_skill_specs
from ..models import AdmissionResult, HarnessContract, SkillInstance
from ..modes import DEFAULT_MODE_SPEC


@dataclass(frozen=True)
class SelectedRuntimeContext:
    prompt: str
    admission: AdmissionResult
    skill_instances: tuple[SkillInstance, ...]
    contract: HarnessContract


def select_runtime_context(
    *,
    repo_root: Path,
    prompt_arg: str | None,
    brief_arg: str | None,
    skill_root: Path,
    selected_skills: list[str] | None,
) -> SelectedRuntimeContext:
    prompt = load_prompt(repo_root, prompt_arg, brief_arg)
    skill_specs = load_skill_specs(repo_root, skill_root, selected_skills)
    admission = prepare_session(
        skill_specs=skill_specs,
        prompt=prompt,
        explicit_skill_selection=selected_skills is not None,
    )
    selected_slugs = set(admission.selected_skills)
    selected_specs = [spec for spec in skill_specs if spec.slug in selected_slugs]
    skill_instances = tuple(
        SkillInstance(spec=spec, instance_id=f"{spec.slug}-instance")
        for spec in selected_specs
    )
    contract = build_harness_contract(
        mode=DEFAULT_MODE_SPEC.name,
        mode_spec=DEFAULT_MODE_SPEC,
        skill_instances=skill_instances,
        admission=admission,
    )
    return SelectedRuntimeContext(
        prompt=prompt,
        admission=admission,
        skill_instances=skill_instances,
        contract=contract,
    )
