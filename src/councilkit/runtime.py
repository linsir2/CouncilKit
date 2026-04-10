from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from .admission import RUNNABLE_STATUSES, prepare_session
from .constants import DEFAULT_MODE, RAW_TRACE_ROOT
from .errors import SynthesisPayloadInvalidError, TurnConfidenceInvalidError, TurnPayloadValidationError, TurnSlotMissingError
from .failures import FailureEvent, create_failure_event, write_failure_events
from .harness_contract import build_harness_contract
from .llm import LLMClient
from .loader import load_prompt, load_skill_specs, project_snapshot
from .models import (
    AdmissionResult,
    RunTrace,
    SkillInstance,
    SynthesisResult,
    TaskEnvelope,
    TurnRecord,
    TurnResult,
)
from .modes import DEFAULT_MODE_SPEC
from .modes.review import build_context_frame, build_synthesis_context, render_context_frame
from .traces import write_trace_artifacts
from .validation import (
    normalize_runtime_turn_payload as _normalize_runtime_turn_payload,
    normalize_synthesis_payload as _normalize_synthesis_payload,
)


def normalize_turn_payload(payload: dict[str, Any]) -> tuple[str, TurnResult]:
    return _normalize_runtime_turn_payload(payload)


def normalize_synthesis_payload(payload: dict[str, Any]) -> SynthesisResult:
    return _normalize_synthesis_payload(payload)


def emit_turn(turn: TurnRecord, *, stage_rounds: int, stream: TextIO | None) -> None:
    out = stream if stream is not None else None
    target = out or __import__("sys").stdout
    target.write(
        f"\n## {turn.stage} (round {turn.round_index}/{stage_rounds})"
        f"\n\n### {turn.skill_name}\n{turn.message}\n"
        f"- judgment: {turn.result.judgment}\n"
        f"- evidence: {'; '.join(turn.result.evidence) if turn.result.evidence else 'none'}\n"
        f"- tradeoff: {turn.result.tradeoff}\n"
        f"- objection: {turn.result.objection or 'none'}\n"
        f"- needs_verification: {'; '.join(turn.result.needs_verification) if turn.result.needs_verification else 'none'}\n"
        f"- confidence: {turn.result.confidence}\n"
    )
    target.flush()


def emit_synthesis(synthesis: SynthesisResult, stream: TextIO | None) -> None:
    out = stream if stream is not None else None
    target = out or __import__("sys").stdout
    target.write(
        "\n## synthesis"
        "\n\n### Coordinator\n"
        f"{synthesis.summary}\n"
        f"- decision: {synthesis.decision}\n"
    )
    target.flush()


def _build_blocked_synthesis(admission: AdmissionResult) -> SynthesisResult:
    severity = "high" if admission.status == "out_of_scope" else "medium"
    if admission.status == "out_of_scope":
        decision = "Reduce selected skills to at most 4 and rerun the session."
        next_steps = (
            "Trim the selected skill set.",
            "Rerun with 3 skills by default, or 4 with warning.",
        )
    else:
        decision = "Clarify session scope or provide explicit skill selection before rerunning."
        next_steps = (
            "Clarify the brief with a narrower decision question.",
            "Provide explicit --skills when the local universe is broad.",
        )

    return SynthesisResult(
        title="Session blocked by admission gate",
        summary=admission.reason,
        decision=decision,
        key_decisions=(
            f"Admission status: {admission.status}",
            "No discussion turns were executed for this run.",
        ),
        strongest_objections=(
            {
                "skill": "Admission Gate",
                "objection": admission.reason,
                "severity": severity,
            },
        ),
        next_steps=next_steps,
        open_questions=(
            "Is the skill set too broad for this session goal?",
            "Does the brief need a narrower decision target?",
        ),
        skill_notes=(
            {
                "skill": "Admission Gate",
                "note": "Admission provenance is recorded in run.json for replay and routing diagnostics.",
            },
        ),
    )


def _build_runtime_failure_synthesis(*, failure_code: str, reason: str) -> SynthesisResult:
    return SynthesisResult(
        title="Session halted by runtime payload gate",
        summary=reason,
        decision="Fix runtime payload contract violations and rerun the session.",
        key_decisions=(
            f"Runtime failure code: {failure_code}",
            "Turn-level replay was preserved up to the failure point.",
        ),
        strongest_objections=(
            {
                "skill": "Runtime Contract",
                "objection": reason,
                "severity": "high",
            },
        ),
        next_steps=(
            "Inspect failure-events.jsonl and the last successful turn in run.json.",
            "Adjust skill prompt/response contract to satisfy six-slot constraints.",
        ),
        open_questions=(
            "Is the payload failure deterministic for this prompt and skill set?",
        ),
        skill_notes=(
            {
                "skill": "Runtime Contract",
                "note": "This run stopped intentionally to avoid propagating malformed payloads.",
            },
        ),
    )


def run(
    *,
    prompt: str | None = None,
    brief: str | None = None,
    skill_root: Path | None = None,
    skills: list[str] | None = None,
    project_root: Path | None = None,
    output_root: Path | None = None,
    client: Any | None = None,
    repo_root: Path | None = None,
    echo: bool = False,
    stream: TextIO | None = None,
) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    resolved_project_root = project_root or root
    final_prompt = load_prompt(root, prompt, brief)
    skill_specs = load_skill_specs(root, skill_root or root / "skills", skills)
    admission = prepare_session(
        skill_specs=skill_specs,
        prompt=final_prompt,
        explicit_skill_selection=skills is not None,
    )
    selected_slugs = set(admission.selected_skills)
    selected_specs = [spec for spec in skill_specs if spec.slug in selected_slugs]
    skill_instances = tuple(
        SkillInstance(spec=spec, instance_id=f"{spec.slug}-instance")
        for spec in selected_specs
    )
    project_context = project_snapshot(resolved_project_root)
    task = TaskEnvelope(
        prompt=final_prompt,
        mode=DEFAULT_MODE,
        project_root=resolved_project_root,
        shared_brief=project_context,
    )
    turns: list[TurnRecord] = []
    pending_failures: list[dict[str, Any]] = []
    target_stream = stream or None
    runnable = admission.status in RUNNABLE_STATUSES and bool(skill_instances)
    runtime_failure: dict[str, Any] | None = None

    if runnable:
        llm = client or LLMClient.from_env(root)
        current_stage = "dispatch"
        current_skill_slug = ""
        current_round = 0
        for stage in DEFAULT_MODE_SPEC.stages[:-1]:
            stage_rounds = DEFAULT_MODE_SPEC.rounds_per_stage[stage]
            for round_index in range(1, stage_rounds + 1):
                ordered_skills = skill_instances[(round_index - 1) % len(skill_instances) :] + skill_instances[
                    : (round_index - 1) % len(skill_instances)
                ]
                for skill in ordered_skills:
                    current_stage = stage
                    current_round = round_index
                    current_skill_slug = skill.spec.slug
                    frame = build_context_frame(
                        skill=skill,
                        stage=stage,
                        round_index=round_index,
                        total_rounds=stage_rounds,
                        project_context=project_context,
                        prompt=final_prompt,
                        turns=turns,
                    )
                    raw_payload = llm.complete_json(
                        role=f"{skill.spec.name} / skill runtime participant",
                        stage=stage,
                        prompt=final_prompt,
                        context=render_context_frame(frame),
                    )
                    try:
                        message, result = normalize_turn_payload(raw_payload)
                    except TurnPayloadValidationError as error:
                        runtime_failure = {
                            "source_stage": "dispatch",
                            "failure_code": error.failure_code,
                            "deterministic": False,
                            "skill_slugs": tuple(admission.selected_skills),
                            "notes": (
                                f"{current_stage}/round-{current_round}/{current_skill_slug}: {error}"
                            ),
                        }
                        break
                    turn = TurnRecord(
                        stage=stage,
                        round_index=round_index,
                        skill_instance_id=skill.instance_id,
                        skill_name=skill.spec.name,
                        message=message,
                        result=result,
                    )
                    turns.append(turn)
                    if echo:
                        emit_turn(turn, stage_rounds=stage_rounds, stream=target_stream)
                if runtime_failure is not None:
                    break
            if runtime_failure is not None:
                break

        if runtime_failure is None:
            try:
                synthesis = normalize_synthesis_payload(
                    llm.complete_json(
                        role="Coordinator / synthesis",
                        stage="synthesis",
                        prompt=final_prompt,
                        context=build_synthesis_context(final_prompt, list(skill_instances), turns, project_context),
                    )
                )
            except SynthesisPayloadInvalidError as error:
                runtime_failure = {
                    "source_stage": "synthesis",
                    "failure_code": error.failure_code,
                    "deterministic": False,
                    "skill_slugs": tuple(admission.selected_skills),
                    "notes": str(error),
                }
                synthesis = _build_runtime_failure_synthesis(
                    failure_code=error.failure_code,
                    reason=str(error),
                )
        else:
            synthesis = _build_runtime_failure_synthesis(
                failure_code=str(runtime_failure["failure_code"]),
                reason=str(runtime_failure["notes"]),
            )
        if runtime_failure is not None:
            pending_failures.append(runtime_failure)
        if echo:
            emit_synthesis(synthesis, stream=target_stream)
        model = getattr(llm, "model", None)
        base_url = getattr(llm, "base_url", None)
    else:
        synthesis = _build_blocked_synthesis(admission)
        failure_code = ""
        if admission.status == "needs_clarification":
            failure_code = "admission_needs_clarification"
        elif admission.status == "out_of_scope":
            failure_code = "admission_out_of_scope"
        if failure_code:
            pending_failures.append(
                {
                    "source_stage": "admission",
                    "failure_code": failure_code,
                    "deterministic": True,
                    "skill_slugs": tuple(admission.selected_skills),
                    "notes": admission.reason,
                }
            )
        if echo:
            emit_synthesis(synthesis, stream=target_stream)
        model = None
        base_url = None

    created_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    trace = RunTrace(
        task=task,
        skills=skill_instances,
        turns=tuple(turns),
        synthesis=synthesis,
        created_at=created_at,
        admission=admission,
        harness=build_harness_contract(
            mode=DEFAULT_MODE,
            mode_spec=DEFAULT_MODE_SPEC,
            skill_instances=skill_instances,
            admission=admission,
        ),
    )

    trace_root = output_root or (root / RAW_TRACE_ROOT)
    run_dir = write_trace_artifacts(
        trace,
        output_root=trace_root,
        directory_name=created_at,
        model=model,
        base_url=base_url,
    )
    if pending_failures:
        run_ref = str(run_dir / "run.json")
        events: list[FailureEvent] = []
        for failure in pending_failures:
            events.append(
                create_failure_event(
                    run_ref=run_ref,
                    source_stage=str(failure["source_stage"]),
                    failure_code=str(failure["failure_code"]),
                    repro_ref=run_ref,
                    deterministic=bool(failure["deterministic"]),
                    skill_slugs=tuple(str(item) for item in failure.get("skill_slugs", ()) if str(item).strip()),
                    notes=str(failure.get("notes", "")).strip() or None,
                )
            )
        write_failure_events(run_dir, tuple(events))
    return run_dir
