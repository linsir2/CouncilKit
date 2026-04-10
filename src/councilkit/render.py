from __future__ import annotations

from .models import RunTrace, SynthesisResult, TurnRecord


def render_transcript(prompt: str, turns: list[TurnRecord], synthesis: SynthesisResult, stages: tuple[str, ...]) -> str:
    lines = ["# Skill Runtime Transcript", "", f"Brief: {prompt}", ""]
    for stage in stages[:-1]:
        lines.append(f"## {stage}")
        lines.append("")
        stage_turns = [turn for turn in turns if turn.stage == stage]
        max_round = max((turn.round_index for turn in stage_turns), default=0)
        for round_index in range(1, max_round + 1):
            lines.append(f"### round {round_index}")
            lines.append("")
            for turn in stage_turns:
                if turn.round_index != round_index:
                    continue
                lines.append(f"### {turn.skill_name}")
                lines.append(turn.message)
                lines.append("")
                lines.append(f"- judgment: {turn.result.judgment}")
                lines.append(f"- evidence: {'; '.join(turn.result.evidence) if turn.result.evidence else 'none'}")
                lines.append(f"- tradeoff: {turn.result.tradeoff}")
                lines.append(f"- objection: {turn.result.objection or 'none'}")
                lines.append(
                    f"- needs_verification: {'; '.join(turn.result.needs_verification) if turn.result.needs_verification else 'none'}"
                )
                lines.append(f"- confidence: {turn.result.confidence}")
                lines.append("")
    lines.append("## synthesis")
    lines.append("")
    lines.append("### Coordinator")
    lines.append(synthesis.summary)
    lines.append("")
    lines.append(f"- decision: {synthesis.decision}")
    lines.append("")
    return "\n".join(lines)


def render_result(prompt: str, synthesis: SynthesisResult) -> str:
    lines = [
        f"# {synthesis.title}",
        "",
        f"Brief: {prompt}",
        "",
        "## Summary",
        synthesis.summary,
        "",
        "## Decision",
        synthesis.decision,
        "",
        "## Key Decisions",
    ]
    for item in synthesis.key_decisions:
        lines.append(f"- {item}")

    lines.extend(["", "## Strongest Objections"])
    for item in synthesis.strongest_objections:
        lines.append(f"- {item['skill']} ({item['severity']}): {item['objection']}")

    lines.extend(["", "## Next Steps"])
    for item in synthesis.next_steps:
        lines.append(f"- {item}")

    lines.extend(["", "## Open Questions"])
    for item in synthesis.open_questions:
        lines.append(f"- {item}")

    lines.extend(["", "## Skill Notes"])
    for item in synthesis.skill_notes:
        lines.append(f"- {item['skill']}: {item['note']}")

    lines.append("")
    return "\n".join(lines)


def render_debate(trace: RunTrace) -> str:
    lines = [
        "# CouncilKit Debate Projection",
        "",
        "## Brief",
        trace.task.prompt,
        "",
        "## Trace Context",
        f"- source_kind: {trace.source_kind}",
        f"- mode: {trace.task.mode}",
        f"- created_at: {trace.created_at}",
        f"- project_root: {trace.task.project_root}",
        "",
        "## Participants & Provenance",
        "",
    ]

    candidate_map = {
        item.slug: item
        for item in (trace.admission.candidate_skills if trace.admission is not None else ())
    }
    harness_skill_map = {
        item.slug: item
        for item in (trace.harness.skills if trace.harness is not None else ())
    }

    if not trace.skills:
        lines.extend(["No runtime participants were loaded.", ""])
    else:
        for skill in trace.skills:
            candidate = candidate_map.get(skill.spec.slug)
            harness_skill = harness_skill_map.get(skill.spec.slug)
            lines.append(f"### {skill.spec.name}")
            lines.append(f"- slug: {skill.spec.slug}")
            lines.append(f"- boundary: {_single_line(skill.spec.tagline or skill.spec.description or 'n/a')}")
            lines.append(f"- skill_file: {skill.spec.skill_file}")
            lines.append(f"- prompt_sha256: {harness_skill.prompt_sha256 if harness_skill is not None else 'n/a'}")
            lines.append(
                "- matched_terms: "
                + (_format_joined(candidate.matched_terms) if candidate is not None else "none")
            )
            lines.append("")

    lines.extend(["## Admission Rationale", ""])
    if trace.admission is None:
        lines.extend(["No admission metadata captured.", ""])
    else:
        lines.append(f"- status: {trace.admission.status}")
        lines.append(f"- reason: {_single_line(trace.admission.reason)}")
        lines.append(f"- selected_skills: {_format_joined(trace.admission.selected_skills)}")
        lines.append(f"- warnings: {_format_joined(trace.admission.warnings)}")
        if trace.admission.rejected_skills:
            lines.append("- rejected_skills:")
            for item in trace.admission.rejected_skills:
                lines.append(f"  - {item.slug}: {_single_line(item.reason)}")
        else:
            lines.append("- rejected_skills: none")
        lines.append("")

    lines.extend(["## Debate Map", ""])
    if not trace.turns:
        lines.extend(["No debate turns recorded.", ""])
    else:
        for stage in _stage_order(trace):
            stage_turns = [turn for turn in trace.turns if turn.stage == stage]
            if not stage_turns:
                continue
            lines.extend([f"### {stage}", ""])
            for round_index in sorted({turn.round_index for turn in stage_turns}):
                lines.extend([f"#### round {round_index}", ""])
                for turn in stage_turns:
                    if turn.round_index != round_index:
                        continue
                    lines.append(f"##### {turn.skill_name}")
                    lines.append(f"- position: {_single_line(_first_sentence(turn.message))}")
                    lines.append(f"- judgment: {_single_line(turn.result.judgment)}")
                    lines.append(f"- objection: {_single_line(turn.result.objection or 'none')}")
                    lines.append(f"- tradeoff: {_single_line(turn.result.tradeoff)}")
                    lines.append(f"- confidence: {turn.result.confidence}")
                    lines.append(f"- evidence_path: {_format_joined(turn.result.evidence)}")
                    lines.append(f"- needs_verification: {_format_joined(turn.result.needs_verification)}")
                    lines.append("")

    lines.extend(
        [
            "## Synthesis Delta",
            "",
            "### Coordinator Summary",
            trace.synthesis.summary,
            "",
            "### Final Decision",
            trace.synthesis.decision,
            "",
            "### Kept In Synthesis",
        ]
    )
    for item in trace.synthesis.key_decisions:
        lines.append(f"- {item}")
    if not trace.synthesis.key_decisions:
        lines.append("- none")

    lines.extend(["", "### Strongest Objections Preserved"])
    for item in trace.synthesis.strongest_objections:
        lines.append(f"- {item['skill']} ({item['severity']}): {item['objection']}")
    if not trace.synthesis.strongest_objections:
        lines.append("- none")

    lines.extend(["", "### Next Steps"])
    for item in trace.synthesis.next_steps:
        lines.append(f"- {item}")
    if not trace.synthesis.next_steps:
        lines.append("- none")

    lines.extend(["", "### Still Unresolved"])
    for item in trace.synthesis.open_questions:
        lines.append(f"- {item}")
    if not trace.synthesis.open_questions:
        lines.append("- none")

    lines.extend(["", "### Skill Notes"])
    for item in trace.synthesis.skill_notes:
        lines.append(f"- {item['skill']}: {item['note']}")
    if not trace.synthesis.skill_notes:
        lines.append("- none")

    lines.extend(["", "## Harness Handoff", ""])
    if trace.harness is None:
        lines.extend(["No harness metadata captured.", ""])
    else:
        lines.append(f"- mode: {trace.harness.mode}")
        lines.append(f"- stage_order: {_format_joined(trace.harness.stage_order)}")
        lines.append(f"- reduction_slots: {_format_joined(trace.harness.reduction_slots)}")
        lines.append(f"- selected_skill_slugs: {_format_joined(trace.harness.selected_skill_slugs)}")
        lines.append(
            "- handoff_path: "
            "--emit-harness-contract -> --emit-session-spec -> "
            "--emit-dispatch-template -> --validate-dispatch-payload -> --ingest-session-run"
        )
        lines.append("")

    return "\n".join(lines)


def _format_joined(items: tuple[str, ...]) -> str:
    values = tuple(_single_line(item) for item in items if _single_line(item))
    return ", ".join(values) if values else "none"


def _single_line(value: str) -> str:
    return " ".join(part.strip() for part in str(value).splitlines() if part.strip()) or "n/a"


def _first_sentence(value: str) -> str:
    text = str(value).strip()
    if not text:
        return "n/a"
    compact = _single_line(text)
    for marker in (". ", "! ", "? ", "。", "！", "？"):
        if marker in compact:
            head, _, _ = compact.partition(marker)
            suffix = marker.strip() if marker.strip() in {".", "!", "?", "。", "！", "？"} else ""
            return f"{head}{suffix}".strip() or compact
    return compact


def _stage_order(trace: RunTrace) -> list[str]:
    stage_order = [stage for stage in (trace.harness.stage_order if trace.harness is not None else ()) if stage != "synthesis"]
    seen = set(stage_order)
    for turn in trace.turns:
        if turn.stage == "synthesis" or turn.stage in seen:
            continue
        seen.add(turn.stage)
        stage_order.append(turn.stage)
    return stage_order
