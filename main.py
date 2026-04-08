from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from dotenv import load_dotenv
from openai import OpenAI


@dataclass(frozen=True)
class AgentPack:
    name: str
    slug: str
    mission: str
    role: str
    non_goals: list[str]
    philosophy: list[str]
    forbidden: list[str]
    style: str
    push_for: list[str]
    push_against: list[str]
    anchors: list[str]
    cases: list[str]
    controversies: list[str]


@dataclass(frozen=True)
class Turn:
    stage: str
    round_index: int
    agent: str
    message: str


STAGES = ("alignment", "proposal", "challenge", "consensus")
STAGE_ROUNDS = {
    "alignment": 3,
    "proposal": 3,
    "challenge": 3,
}
DEFAULT_PROMPT_FILE = Path("examples/prompts/ai-support-backend.md")
DEFAULT_PACK_ROOT = Path("examples/packs")


class LLMClient:
    def __init__(self, api_key: str, model: str, base_url: str | None) -> None:
        self.model = model
        self.base_url = base_url
        self.client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=90)

    @classmethod
    def from_env(cls, repo_root: Path) -> "LLMClient":
        load_dotenv(repo_root / ".env")

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required.")

        model = os.environ.get("OPENAI_MODEL", "").strip() or "qwen-plus"
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
        return cls(api_key=api_key, model=model, base_url=base_url)

    def complete_json(self, *, role: str, stage: str, prompt: str, context: str) -> dict[str, Any]:
        if stage == "consensus":
            schema_hint = (
                '{"title":"short title","summary":"one short paragraph",'
                '"architecture":"one short paragraph","mvp_scope":"one short paragraph"}'
            )
        else:
            schema_hint = '{"message":"one short paragraph"}'

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are {role} in a three-agent technical debate.\n"
                        "Be concrete, minimal, and product-oriented.\n"
                        "Do not write long essays.\n"
                        f"Return JSON only with shape: {schema_hint}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"User request:\n{prompt}\n\nDebate context:\n{context}",
                },
            ],
            temperature=0.4,
        )
        raw = completion.choices[0].message.content or ""
        return extract_json_object(raw)


def extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(f"Model did not return JSON: {raw[:200]}")
    return json.loads(text[start : end + 1])


def load_prompt(repo_root: Path, prompt: str | None) -> str:
    if prompt:
        return prompt.strip()
    return (repo_root / DEFAULT_PROMPT_FILE).read_text(encoding="utf-8").strip()


def load_agent_packs(repo_root: Path, pack_root: Path = DEFAULT_PACK_ROOT) -> list[AgentPack]:
    root = repo_root / pack_root
    packs: list[AgentPack] = []

    for pack_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        aggregated_path = pack_dir / "agent.json"
        if not aggregated_path.exists():
            raise FileNotFoundError(
                f"Missing required aggregated pack file: {aggregated_path}. "
                "This runtime only supports agent.json packs."
            )

        raw = json.loads(aggregated_path.read_text(encoding="utf-8"))
        validate_agent_json(raw, aggregated_path)
        packs.append(
            AgentPack(
                name=raw["meta"]["name"],
                slug=raw["meta"]["id"],
                mission=raw["identity"]["mission"],
                role=raw["constitution"]["role"],
                non_goals=list(raw["identity"]["non_goals"]),
                philosophy=list(raw["constitution"]["principles"]),
                forbidden=list(raw["constitution"]["forbidden"]),
                style=str(raw["debate_guide"]["speak_like"]),
                push_for=list(raw["debate_guide"]["push_for"]),
                push_against=list(raw["debate_guide"]["push_against"]),
                anchors=[str(item["claim"]) for item in raw["team_judgment"]["anchors"]],
                cases=[str(item["claim"]) for item in raw["team_judgment"]["cases"]],
                controversies=[str(item["question"]) for item in raw["team_judgment"]["controversies"]],
            )
        )

    return packs


def validate_agent_json(payload: dict[str, Any], source_path: Path) -> None:
    required_sections = ("meta", "identity", "constitution", "team_judgment", "debate_guide")
    for section in required_sections:
        if section not in payload:
            raise ValueError(f"{source_path} missing required section: {section}")

    if payload["meta"].get("schema_version") != "1.0":
        raise ValueError(f"{source_path} schema_version must be '1.0'")

    required_meta_keys = ("id", "name")
    for key in required_meta_keys:
        if not payload["meta"].get(key):
            raise ValueError(f"{source_path} meta.{key} must be non-empty")

    if not payload["identity"].get("mission"):
        raise ValueError(f"{source_path} identity.mission must be non-empty")

    if not payload["constitution"].get("role"):
        raise ValueError(f"{source_path} constitution.role must be non-empty")

    judgment = payload["team_judgment"]
    for bucket in ("anchors", "cases", "controversies"):
        if not isinstance(judgment.get(bucket), list) or not judgment[bucket]:
            raise ValueError(f"{source_path} team_judgment.{bucket} must be a non-empty list")

    guide = payload["debate_guide"]
    for key in ("speak_like", "push_for", "push_against"):
        if key not in guide or not guide[key]:
            raise ValueError(f"{source_path} debate_guide.{key} must be non-empty")


def build_agent_context(
    agent: AgentPack,
    stage: str,
    round_index: int,
    total_rounds: int,
    prompt: str,
    turns: list[Turn],
) -> str:
    prior_turns = [turn for turn in turns if turn.stage != "consensus"]
    debate_so_far = "\n".join(
        f"- {turn.agent} [{turn.stage}/round-{turn.round_index}]: {turn.message}" for turn in prior_turns[-15:]
    )
    if not debate_so_far:
        debate_so_far = "- none yet"

    if stage == "alignment":
        ask = "State your boundary, your role, and what this MVP should not overbuild."
    elif stage == "proposal":
        ask = "Propose your minimal slice of the MVP."
    else:
        ask = "Challenge the current design and remove unnecessary complexity."

    return "\n".join(
        [
            f"Agent: {agent.name}",
            f"Mission: {agent.mission}",
            f"Primary role: {agent.role}",
            f"Non-goals: {', '.join(agent.non_goals)}",
            f"Design philosophy: {'; '.join(agent.philosophy)}",
            f"Forbidden moves: {'; '.join(agent.forbidden)}",
            f"Debate style: {agent.style}",
            f"Push for: {'; '.join(agent.push_for)}",
            f"Push against: {'; '.join(agent.push_against)}",
            f"Key anchors: {'; '.join(agent.anchors)}",
            f"Representative cases: {'; '.join(agent.cases)}",
            f"Known controversies: {'; '.join(agent.controversies)}",
            "",
            f"Round: {round_index}/{total_rounds}",
            f"Stage ask: {ask}",
            f"Target product request: {prompt}",
            "",
            "Debate so far:",
            debate_so_far,
        ]
    )


def build_consensus_context(prompt: str, packs: list[AgentPack], turns: list[Turn]) -> str:
    pack_lines = [f"- {pack.name}: {pack.role}" for pack in packs]
    turn_lines = [f"- {turn.agent} [{turn.stage}/round-{turn.round_index}]: {turn.message}" for turn in turns]
    return "\n".join(
        [
            f"User request: {prompt}",
            "",
            "Available agents:",
            *pack_lines,
            "",
            "Debate transcript:",
            *turn_lines,
            "",
            "Return a minimal MVP consensus only.",
        ]
    )


def run(
    *,
    prompt: str | None = None,
    output_root: Path | None = None,
    client: Any | None = None,
    repo_root: Path | None = None,
    echo: bool = False,
    stream: TextIO | None = None,
) -> Path:
    root = repo_root or Path(__file__).resolve().parent
    final_prompt = load_prompt(root, prompt)
    packs = load_agent_packs(root)
    llm = client or LLMClient.from_env(root)
    turns: list[Turn] = []
    target_stream = stream or None

    for stage in STAGES[:-1]:
        stage_rounds = STAGE_ROUNDS[stage]
        for round_index in range(1, stage_rounds + 1):
            ordered_packs = packs[(round_index - 1) % len(packs) :] + packs[: (round_index - 1) % len(packs)]
            for pack in ordered_packs:
                payload = llm.complete_json(
                    role=f"{pack.name} / {pack.role}",
                    stage=stage,
                    prompt=final_prompt,
                    context=build_agent_context(pack, stage, round_index, stage_rounds, final_prompt, turns),
                )
                turn = Turn(
                    stage=stage,
                    round_index=round_index,
                    agent=pack.name,
                    message=str(payload["message"]).strip(),
                )
                turns.append(turn)
                if echo:
                    emit_turn(turn, stage_rounds=stage_rounds, stream=target_stream)

    consensus = llm.complete_json(
        role="Coordinator / final synthesizer",
        stage="consensus",
        prompt=final_prompt,
        context=build_consensus_context(final_prompt, packs, turns),
    )
    if echo:
        emit_consensus(consensus, stream=target_stream)

    root_output = output_root or (root / "runs")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root_output / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "transcript.md").write_text(render_transcript(final_prompt, turns, consensus), encoding="utf-8")
    (run_dir / "result.md").write_text(render_result(final_prompt, consensus), encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "prompt": final_prompt,
                "agents": [pack.name for pack in packs],
                "stages": list(STAGES),
                "rounds_per_stage": STAGE_ROUNDS,
                "turn_count": len(turns) + 1,
                "model": getattr(llm, "model", None),
                "base_url": getattr(llm, "base_url", None),
                "consensus": consensus,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return run_dir


def render_transcript(prompt: str, turns: list[Turn], consensus: dict[str, Any]) -> str:
    lines = ["# Debate Transcript", "", f"Prompt: {prompt}", ""]
    for stage in STAGES[:-1]:
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
                lines.append(f"### {turn.agent}")
                lines.append(turn.message)
                lines.append("")
    lines.append("## consensus")
    lines.append("")
    lines.append("### Coordinator")
    lines.append(str(consensus["summary"]).strip())
    lines.append("")
    lines.append(str(consensus["architecture"]).strip())
    lines.append("")
    return "\n".join(lines)


def render_result(prompt: str, consensus: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {consensus['title']}",
            "",
            f"Prompt: {prompt}",
            "",
            "## Summary",
            str(consensus["summary"]).strip(),
            "",
            "## Architecture",
            str(consensus["architecture"]).strip(),
            "",
            "## MVP Scope",
            str(consensus["mvp_scope"]).strip(),
            "",
        ]
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Run the minimal debate MVP.")
    parser.add_argument("--prompt", help="Optional inline prompt. Defaults to examples/prompts/ai-support-backend.md")
    parser.add_argument(
        "--output-root",
        default=None,
        help="Directory where artifacts will be written. Defaults to <project-root>/runs.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable real-time terminal debate logs.",
    )
    args = parser.parse_args()

    output_root = None
    if args.output_root:
        candidate = Path(args.output_root)
        output_root = candidate if candidate.is_absolute() else repo_root / candidate

    run_dir = run(
        prompt=args.prompt,
        output_root=output_root,
        repo_root=repo_root,
        echo=not args.quiet,
    )
    print(run_dir)
    return 0


def emit_turn(turn: Turn, *, stage_rounds: int, stream: TextIO | None) -> None:
    out = stream if stream is not None else sys.stdout
    out.write(
        f"\n## {turn.stage} (round {turn.round_index}/{stage_rounds})\n"
        f"\n### {turn.agent}\n{turn.message}\n"
    )
    out.flush()


def emit_consensus(consensus: dict[str, Any], stream: TextIO | None) -> None:
    out = stream if stream is not None else sys.stdout
    out.write(
        "\n## consensus\n"
        "\n### Coordinator\n"
        f"{str(consensus.get('summary', '')).strip()}\n"
        f"{str(consensus.get('architecture', '')).strip()}\n"
    )
    out.flush()


if __name__ == "__main__":
    raise SystemExit(main())
