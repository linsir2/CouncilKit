from __future__ import annotations

from pathlib import Path
from typing import Any

from ..dispatch_template import build_dispatch_template, load_dispatch_template_inputs
from ..harness import load_harness_payload, validate_harness_contract
from ..session_spec import build_session_spec
from .selection import select_runtime_context


def emit_harness_contract_payload(
    *,
    repo_root: Path,
    prompt_arg: str | None,
    brief_arg: str | None,
    skill_root: Path,
    selected_skills: list[str] | None,
) -> dict[str, Any]:
    selected = select_runtime_context(
        repo_root=repo_root,
        prompt_arg=prompt_arg,
        brief_arg=brief_arg,
        skill_root=skill_root,
        selected_skills=selected_skills,
    )
    return {
        "harness": selected.contract.to_dict(),
        "admission": selected.admission.to_dict(),
    }


def verify_harness_contract_payload(
    *,
    repo_root: Path,
    contract_ref: Path,
    strict_hash: bool,
):
    harness, _ = load_harness_payload(contract_ref)
    return validate_harness_contract(
        harness,
        strict_hash=strict_hash,
        repo_root=repo_root,
        contract_ref=contract_ref,
    )


def emit_session_spec_payload(
    *,
    repo_root: Path,
    source_ref: Path | None,
    prompt_arg: str | None,
    brief_arg: str | None,
    skill_root: Path,
    selected_skills: list[str] | None,
) -> dict[str, Any]:
    if source_ref is not None:
        contract, admission = load_harness_payload(source_ref)
    else:
        selected = select_runtime_context(
            repo_root=repo_root,
            prompt_arg=prompt_arg,
            brief_arg=brief_arg,
            skill_root=skill_root,
            selected_skills=selected_skills,
        )
        contract, admission = selected.contract, selected.admission
    return build_session_spec(harness=contract, admission=admission)


def emit_dispatch_template_payload(
    *,
    repo_root: Path,
    source_ref: Path | None,
    project_root: Path,
    prompt_arg: str | None,
    brief_arg: str | None,
    skill_root: Path,
    selected_skills: list[str] | None,
) -> dict[str, Any]:
    selected = None
    if source_ref is None:
        selected = select_runtime_context(
            repo_root=repo_root,
            prompt_arg=prompt_arg,
            brief_arg=brief_arg,
            skill_root=skill_root,
            selected_skills=selected_skills,
        )

    session_spec, prompt, template_project_root, shared_brief = load_dispatch_template_inputs(
        source_ref=source_ref,
        repo_root=repo_root,
        project_root=project_root,
        prompt_arg=prompt_arg,
        brief_arg=brief_arg,
        contract=selected.contract if selected is not None else None,
        admission=selected.admission if selected is not None else None,
    )
    return build_dispatch_template(
        session_spec=session_spec,
        prompt=prompt,
        project_root=template_project_root,
        shared_brief=shared_brief,
    )
