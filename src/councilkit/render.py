from __future__ import annotations

from .models import SynthesisResult, TurnRecord


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
