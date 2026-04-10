from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .harness import load_harness_payload
from .harness_runtime import resolve_turn_schedule
from .loader import load_prompt, project_snapshot
from .models import AdmissionResult, HarnessContract
from .session_spec import build_session_spec

DISPATCH_TEMPLATE_VERSION = "v1"


def build_dispatch_template(
    *,
    session_spec: dict[str, Any],
    prompt: str,
    project_root: Path,
    shared_brief: str,
) -> dict[str, Any]:
    schedule = resolve_turn_schedule(session_spec)
    turns = [
        {
            "turn_index": turn.turn_index,
            "stage": turn.stage,
            "round_index": turn.round_index,
            "skill_slug": turn.skill_slug,
            "skill_name": turn.skill_name,
            "message": "",
            "judgment": "",
            "evidence": [],
            "tradeoff": "",
            "objection": "",
            "needs_verification": [],
            "confidence": "",
        }
        for turn in schedule
    ]
    return {
        "template_version": DISPATCH_TEMPLATE_VERSION,
        "prompt": prompt,
        "project_root": str(project_root),
        "shared_brief": shared_brief,
        "session_spec": session_spec,
        "turns": turns,
        "synthesis": {
            "title": "",
            "summary": "",
            "decision": "",
            "key_decisions": [],
            "strongest_objections": [],
            "next_steps": [],
            "open_questions": [],
            "skill_notes": [],
        },
    }


def load_dispatch_template_inputs(
    *,
    source_ref: Path | None,
    repo_root: Path,
    project_root: Path,
    prompt_arg: str | None,
    brief_arg: str | None,
    contract: HarnessContract | None = None,
    admission: AdmissionResult | None = None,
) -> tuple[dict[str, Any], str, Path, str]:
    if source_ref is None:
        if contract is None:
            raise ValueError("contract is required when source_ref is omitted")
        session_spec = build_session_spec(harness=contract, admission=admission)
        resolved_project_root = project_root
        prompt = load_prompt(repo_root, prompt_arg, brief_arg)
        shared_brief = project_snapshot(resolved_project_root)
        return session_spec, prompt, resolved_project_root, shared_brief

    payload = json.loads(source_ref.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Dispatch template source must be a JSON object")

    if _looks_like_session_spec(payload):
        session_spec = payload
        prompt = load_prompt(repo_root, prompt_arg, brief_arg) if (prompt_arg or brief_arg) else ""
        resolved_project_root = project_root
        shared_brief = project_snapshot(resolved_project_root) if prompt else ""
        return session_spec, prompt, resolved_project_root, shared_brief

    if "session_spec" in payload and isinstance(payload["session_spec"], dict):
        task_payload = payload.get("task", {})
        if not isinstance(task_payload, dict):
            task_payload = {}
        return (
            payload["session_spec"],
            str(task_payload.get("prompt", "")).strip(),
            Path(str(task_payload.get("project_root", project_root)).strip() or project_root),
            str(task_payload.get("shared_brief", "")).strip(),
        )

    if _looks_like_run_trace(payload):
        harness_payload = payload.get("harness")
        if not isinstance(harness_payload, dict):
            raise ValueError("Run trace source must include harness")
        task_payload = payload.get("task", {})
        if not isinstance(task_payload, dict):
            task_payload = {}
        loaded_contract, loaded_admission = load_harness_payload(source_ref)
        session_spec = build_session_spec(harness=loaded_contract, admission=loaded_admission)
        return (
            session_spec,
            str(task_payload.get("prompt", "")).strip(),
            Path(str(task_payload.get("project_root", project_root)).strip() or project_root),
            str(task_payload.get("shared_brief", "")).strip(),
        )

    loaded_contract, loaded_admission = load_harness_payload(source_ref)
    session_spec = build_session_spec(harness=loaded_contract, admission=loaded_admission)
    prompt = load_prompt(repo_root, prompt_arg, brief_arg) if (prompt_arg or brief_arg) else ""
    resolved_project_root = project_root
    shared_brief = project_snapshot(resolved_project_root) if prompt else ""
    return session_spec, prompt, resolved_project_root, shared_brief


def _looks_like_session_spec(payload: dict[str, Any]) -> bool:
    return "version" in payload and "participants" in payload and "stages" in payload


def _looks_like_run_trace(payload: dict[str, Any]) -> bool:
    return "task" in payload and "harness" in payload and "turns" in payload
