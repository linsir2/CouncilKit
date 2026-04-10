from __future__ import annotations

import json
import re
from pathlib import Path

from .harness import parse_harness_contract
from .models import (
    AdmissionCandidate,
    AdmissionResult,
    PatchProposal,
    RejectedSkill,
    RunTrace,
    SkillInstance,
    SkillSpec,
    SynthesisResult,
    TaskEnvelope,
    TurnRecord,
    TurnResult,
)
from .modes import DEFAULT_MODE_SPEC
from .render import render_debate, render_result, render_transcript


def resolve_trace_file(trace_ref: Path) -> Path:
    candidate = trace_ref / "run.json" if trace_ref.is_dir() else trace_ref
    if not candidate.exists():
        raise FileNotFoundError(f"Trace file not found: {candidate}")
    return candidate


def trace_dir_name(trace_ref: Path) -> str:
    candidate = resolve_trace_file(trace_ref)
    if candidate.name == "run.json":
        return candidate.parent.name
    return candidate.stem


def load_trace(trace_ref: Path) -> tuple[RunTrace, str | None, str | None]:
    payload = json.loads(resolve_trace_file(trace_ref).read_text(encoding="utf-8"))
    skills = tuple(_load_skill_instance(item) for item in payload.get("skills", []))
    turns = tuple(_load_turn_record(item) for item in payload.get("turns", []))
    admission_payload = payload.get("admission")
    harness_payload = payload.get("harness")
    trace = RunTrace(
        task=_load_task_envelope(payload["task"]),
        skills=skills,
        turns=turns,
        synthesis=_load_synthesis_result(payload["synthesis"]),
        created_at=str(payload["created_at"]).strip(),
        admission=_load_admission_result(admission_payload) if isinstance(admission_payload, dict) else None,
        harness=parse_harness_contract(harness_payload) if isinstance(harness_payload, dict) else None,
        source_kind=str(payload.get("source_kind", "raw")).strip() or "raw",
    )
    return trace, payload.get("model"), payload.get("base_url")


def write_trace_artifacts(
    trace: RunTrace,
    *,
    output_root: Path,
    directory_name: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> Path:
    run_dir = output_root / (directory_name or trace.created_at)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(trace.to_dict(model=model, base_url=base_url), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "transcript.md").write_text(
        render_transcript(trace.task.prompt, list(trace.turns), trace.synthesis, DEFAULT_MODE_SPEC.stages),
        encoding="utf-8",
    )
    (run_dir / "result.md").write_text(render_result(trace.task.prompt, trace.synthesis), encoding="utf-8")
    (run_dir / "debate.md").write_text(render_debate(trace), encoding="utf-8")
    return run_dir


def distill_trace(trace: RunTrace) -> RunTrace:
    return RunTrace(
        task=trace.task,
        skills=trace.skills,
        turns=tuple(_distill_turn(turn) for turn in trace.turns),
        synthesis=_distill_synthesis(trace.synthesis),
        created_at=trace.created_at,
        admission=trace.admission,
        harness=trace.harness,
        source_kind="distilled",
    )


def distill_trace_artifacts(trace_ref: Path, *, output_root: Path) -> Path:
    trace, model, base_url = load_trace(trace_ref)
    distilled = distill_trace(trace)
    return write_trace_artifacts(
        distilled,
        output_root=output_root,
        directory_name=trace_dir_name(trace_ref),
        model=model,
        base_url=base_url,
    )


def _load_task_envelope(payload: dict[str, object]) -> TaskEnvelope:
    return TaskEnvelope(
        prompt=str(payload["prompt"]).strip(),
        mode=str(payload["mode"]).strip(),
        project_root=Path(str(payload["project_root"]).strip()),
        shared_brief=str(payload.get("shared_brief", "")).strip(),
        tool_grants=tuple(str(item).strip() for item in payload.get("tool_grants", [])),
    )


def _load_skill_instance(payload: dict[str, object]) -> SkillInstance:
    spec = SkillSpec(
        slug=str(payload["slug"]).strip(),
        name=str(payload["name"]).strip(),
        description=str(payload.get("description", "")).strip(),
        tagline=str(payload.get("tagline", "")).strip(),
        skill_markdown="",
        skill_dir=Path(str(payload["path"]).strip()),
        skill_file=Path(str(payload["skill_file"]).strip()),
        skill_mtime=float(payload["skill_mtime"]) if payload.get("skill_mtime") is not None else None,
    )
    return SkillInstance(spec=spec, instance_id=str(payload["instance_id"]).strip())


def _load_patch_proposal(payload: dict[str, object]) -> PatchProposal:
    return PatchProposal(
        target=str(payload.get("target", "")).strip(),
        change=str(payload.get("change", "")).strip(),
        reason=str(payload.get("reason", "")).strip(),
    )


def _load_admission_result(payload: dict[str, object]) -> AdmissionResult:
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


def _load_turn_result(payload: dict[str, object]) -> TurnResult:
    patch_proposals = tuple(_load_patch_proposal(item) for item in payload.get("patch_proposals", []))
    return TurnResult(
        judgment=str(payload["judgment"]).strip(),
        evidence=tuple(str(item).strip() for item in payload.get("evidence", []) if str(item).strip()),
        tradeoff=str(payload["tradeoff"]).strip(),
        objection=str(payload["objection"]).strip(),
        needs_verification=tuple(
            str(item).strip() for item in payload.get("needs_verification", []) if str(item).strip()
        ),
        confidence=str(payload["confidence"]).strip(),
        patch_proposals=patch_proposals,
    )


def _load_turn_record(payload: dict[str, object]) -> TurnRecord:
    return TurnRecord(
        stage=str(payload["stage"]).strip(),
        round_index=int(payload["round_index"]),
        skill_instance_id=str(payload["skill_instance_id"]).strip(),
        skill_name=str(payload["skill_name"]).strip(),
        message=str(payload["message"]).strip(),
        result=_load_turn_result(payload["result"]),
    )


def _load_synthesis_result(payload: dict[str, object]) -> SynthesisResult:
    strongest_objections = tuple(
        {
            "skill": str(item.get("skill", "")).strip(),
            "objection": str(item.get("objection", "")).strip(),
            "severity": str(item.get("severity", "")).strip(),
        }
        for item in payload.get("strongest_objections", [])
    )
    skill_notes = tuple(
        {
            "skill": str(item.get("skill", "")).strip(),
            "note": str(item.get("note", "")).strip(),
        }
        for item in payload.get("skill_notes", [])
    )
    return SynthesisResult(
        title=str(payload["title"]).strip(),
        summary=str(payload["summary"]).strip(),
        decision=str(payload["decision"]).strip(),
        key_decisions=tuple(str(item).strip() for item in payload.get("key_decisions", []) if str(item).strip()),
        strongest_objections=strongest_objections,
        next_steps=tuple(str(item).strip() for item in payload.get("next_steps", []) if str(item).strip()),
        open_questions=tuple(str(item).strip() for item in payload.get("open_questions", []) if str(item).strip()),
        skill_notes=skill_notes,
    )


def _distill_turn(turn: TurnRecord) -> TurnRecord:
    patch_proposals = tuple(
        proposal
        for proposal in turn.result.patch_proposals
        if proposal.target.strip() and proposal.change.strip() and proposal.reason.strip()
    )[:2]
    return TurnRecord(
        stage=turn.stage,
        round_index=turn.round_index,
        skill_instance_id=turn.skill_instance_id,
        skill_name=turn.skill_name,
        message=_distill_text(turn.message, max_sentences=1),
        result=TurnResult(
            judgment=_distill_text(turn.result.judgment, max_sentences=2),
            evidence=_distill_list(turn.result.evidence, limit=2, max_sentences=1),
            tradeoff=_distill_text(turn.result.tradeoff, max_sentences=2),
            objection=_distill_text(turn.result.objection, max_sentences=1),
            needs_verification=_distill_list(turn.result.needs_verification, limit=1, max_sentences=1),
            confidence=turn.result.confidence,
            patch_proposals=patch_proposals,
        ),
    )


def _distill_synthesis(synthesis: SynthesisResult) -> SynthesisResult:
    strongest_objections = []
    seen_skills: set[str] = set()
    for item in sorted(
        synthesis.strongest_objections,
        key=lambda value: (_severity_rank(value.get("severity", "")), value.get("skill", "")),
        reverse=True,
    ):
        skill = item.get("skill", "").strip()
        if not skill or skill.casefold() in seen_skills:
            continue
        seen_skills.add(skill.casefold())
        strongest_objections.append(
            {
                "skill": skill,
                "objection": _distill_text(item.get("objection", ""), max_sentences=1),
                "severity": item.get("severity", "").strip().lower() or "medium",
            }
        )
        if len(strongest_objections) >= 3:
            break

    skill_notes = []
    seen_notes: set[str] = set()
    for item in synthesis.skill_notes:
        skill = item.get("skill", "").strip()
        note = _distill_text(item.get("note", ""), max_sentences=1)
        key = f"{skill.casefold()}::{note.casefold()}"
        if not skill or not note or key in seen_notes:
            continue
        seen_notes.add(key)
        skill_notes.append({"skill": skill, "note": note})

    return SynthesisResult(
        title=_distill_text(synthesis.title, max_sentences=1),
        summary=_distill_text(synthesis.summary, max_sentences=2),
        decision=_distill_text(synthesis.decision, max_sentences=1),
        key_decisions=_distill_list(synthesis.key_decisions, limit=3, max_sentences=1),
        strongest_objections=tuple(strongest_objections),
        next_steps=_distill_list(synthesis.next_steps, limit=3, max_sentences=1),
        open_questions=_distill_list(synthesis.open_questions, limit=2, max_sentences=1),
        skill_notes=tuple(skill_notes),
    )


def _distill_list(items: tuple[str, ...], *, limit: int, max_sentences: int) -> tuple[str, ...]:
    distilled: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = _distill_text(item, max_sentences=max_sentences)
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        distilled.append(value)
        if len(distilled) >= limit:
            break
    return tuple(distilled)


def _distill_text(value: str, *, max_sentences: int) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", cleaned) if part.strip()]
    if not parts or len(parts) <= max_sentences:
        return cleaned
    return " ".join(parts[:max_sentences]).strip()


def _severity_rank(value: str) -> int:
    if value == "high":
        return 3
    if value == "medium":
        return 2
    if value == "low":
        return 1
    return 0
