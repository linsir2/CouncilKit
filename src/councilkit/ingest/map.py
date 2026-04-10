from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..errors import (
    IngestPayloadInvalidError,
    ScheduleTurnCountMismatchError,
    ScheduleTurnOrderMismatchError,
    SlotInvalidConfidenceError,
    SlotMissingRequiredError,
)
from ..harness import parse_admission_result, resolve_contract_path
from ..harness_contract import REDUCTION_SLOTS
from ..harness_runtime import DispatchedTurn, normalize_dispatch_payload, resolve_turn_schedule, to_turn_records
from ..loader import parse_frontmatter
from ..models import (
    AdmissionResult,
    HarnessContract,
    HarnessSkillContract,
    RunTrace,
    SkillInstance,
    SkillSpec,
    TaskEnvelope,
)
from ..validation import normalize_synthesis_payload, validate_turn_sequence_item
from .models import PreparedIngestTrace
from .parse import extract_turn_payloads, load_session_spec


def prepare_ingest_trace(
    *,
    payload: dict[str, Any],
    payload_ref: Path,
    repo_root: Path,
    strict_hash: bool,
    created_at: str,
) -> PreparedIngestTrace:
    try:
        session_spec = load_session_spec(payload, payload_ref=payload_ref)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as error:
        raise IngestPayloadInvalidError(str(error)) from error

    synthesis_payload = payload.get("synthesis")
    schedule = resolve_turn_schedule(session_spec)
    skill_instances, pending_failures = load_skill_instances_from_session_spec(
        session_spec,
        strict_hash=strict_hash,
        repo_root=repo_root,
        payload_ref=payload_ref,
    )
    dispatched_turns = load_dispatched_turns(extract_turn_payloads(payload), schedule=schedule)
    turn_records = to_turn_records(dispatched_turns, skill_instances=skill_instances)

    if not isinstance(synthesis_payload, dict):
        raise IngestPayloadInvalidError("Ingest payload requires synthesis object")
    synthesis = normalize_synthesis_payload(synthesis_payload)

    admission = load_admission(payload, session_spec)
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
    harness = build_harness_contract_from_session_spec(
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


def load_skill_instances_from_session_spec(
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
        spec, hash_mismatch = build_skill_spec_from_participant(
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


def build_skill_spec_from_participant(
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


def load_dispatched_turns(
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
        validate_turn_sequence_item(raw_turn, expected, index=index)
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


def load_admission(payload: dict[str, Any], session_spec: dict[str, Any]) -> AdmissionResult:
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


def build_harness_contract_from_session_spec(
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
