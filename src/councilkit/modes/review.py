from __future__ import annotations

from dataclasses import dataclass

from ..models import ContextFrame, SkillInstance, TurnRecord


@dataclass(frozen=True)
class ModeSpec:
    name: str
    stages: tuple[str, ...]
    rounds_per_stage: dict[str, int]


DEFAULT_MODE_SPEC = ModeSpec(
    name="review",
    stages=("survey", "review", "synthesis"),
    rounds_per_stage={"survey": 1, "review": 1},
)


def build_context_frame(
    *,
    skill: SkillInstance,
    stage: str,
    round_index: int,
    total_rounds: int,
    project_context: str,
    prompt: str,
    turns: list[TurnRecord],
) -> ContextFrame:
    prior_turns = [turn for turn in turns if turn.stage != "synthesis"]
    prior_lines = tuple(
        f"{turn.skill_name} [{turn.stage}/round-{turn.round_index}] "
        f"judgment={turn.result.judgment} tradeoff={turn.result.tradeoff} "
        f"objection={turn.result.objection or 'none'} confidence={turn.result.confidence}"
        for turn in prior_turns[-12:]
    )

    if stage == "survey":
        stage_ask = "State your boundary, first judgment, strongest evidence path, and key tradeoff."
    else:
        stage_ask = "Sharpen your strongest objection, update tradeoffs, and say what still needs verification."

    skill_brief = "\n".join(
        [
            f"Skill: {skill.spec.name}",
            f"Slug: {skill.spec.slug}",
            f"Description: {skill.spec.description or 'n/a'}",
            f"Tagline: {skill.spec.tagline or 'n/a'}",
            "",
            f"Round: {round_index}/{total_rounds}",
            f"Stage ask: {stage_ask}",
            "",
            "Skill text:",
            skill.spec.skill_markdown,
            "",
            "Original brief:",
            prompt,
        ]
    )
    return ContextFrame(
        stage=stage,
        round_index=round_index,
        total_rounds=total_rounds,
        shared_brief=project_context,
        skill_brief=skill_brief,
        prior_turns=prior_lines,
    )


def render_context_frame(frame: ContextFrame) -> str:
    prior = "\n".join(frame.prior_turns) if frame.prior_turns else "- none yet"
    return "\n".join(
        [
            "Project snapshot:",
            frame.shared_brief,
            "",
            frame.skill_brief,
            "",
            "Prior turns:",
            prior,
        ]
    )


def build_synthesis_context(prompt: str, skills: list[SkillInstance], turns: list[TurnRecord], project_context: str) -> str:
    skill_lines = [f"- {skill.spec.name}: {skill.spec.description or skill.spec.tagline or 'no description'}" for skill in skills]
    turn_lines = []
    for turn in turns:
        turn_lines.append(f"- {turn.skill_name} [{turn.stage}/round-{turn.round_index}]")
        turn_lines.append(f"  judgment: {turn.result.judgment}")
        turn_lines.append(f"  evidence: {'; '.join(turn.result.evidence) if turn.result.evidence else 'none'}")
        turn_lines.append(f"  tradeoff: {turn.result.tradeoff}")
        turn_lines.append(f"  objection: {turn.result.objection or 'none'}")
        turn_lines.append(
            f"  needs_verification: {'; '.join(turn.result.needs_verification) if turn.result.needs_verification else 'none'}"
        )
        turn_lines.append(f"  confidence: {turn.result.confidence}")

    return "\n".join(
        [
            "Project snapshot:",
            project_context,
            "",
            "User brief:",
            prompt,
            "",
            "Loaded skills:",
            *skill_lines,
            "",
            "Turn transcript:",
            *turn_lines,
            "",
            "Return a concise synthesis memo that preserves disagreement and tradeoffs.",
        ]
    )
