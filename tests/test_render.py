import unittest
from pathlib import Path

from src.councilkit.models import (
    AdmissionCandidate,
    AdmissionResult,
    HarnessContract,
    HarnessSkillContract,
    RejectedSkill,
    RunTrace,
    SkillInstance,
    SkillSpec,
    SynthesisResult,
    TaskEnvelope,
    TurnRecord,
    TurnResult,
)
from src.councilkit.render import render_debate


def _skill_instance(
    *,
    slug: str = "fastapi",
    name: str = "FastAPI",
    description: str = "Typed API boundary owner.",
    tagline: str = "Type the contract first.",
) -> SkillInstance:
    skill_dir = Path("/demo/skills") / slug
    return SkillInstance(
        spec=SkillSpec(
            slug=slug,
            name=name,
            description=description,
            tagline=tagline,
            skill_markdown="",
            skill_dir=skill_dir,
            skill_file=skill_dir / "SKILL.md",
            skill_mtime=123.0,
        ),
        instance_id=f"{slug}-instance",
    )


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        prompt="Review the private skill debate surface.",
        mode="review",
        project_root=Path("/demo/project"),
        shared_brief="Project root: /demo/project",
    )


def _synthesis(title: str = "Debate synthesis") -> SynthesisResult:
    return SynthesisResult(
        title=title,
        summary="The projection should keep conflict and handoff visible.",
        decision="Ship the debate projection as a derived artifact.",
        key_decisions=("Keep run.json unchanged.",),
        strongest_objections=(
            {
                "skill": "FastAPI",
                "objection": "Do not leak transport internals into the artifact.",
                "severity": "medium",
            },
        ),
        next_steps=("Write debate.md beside transcript.md.",),
        open_questions=("How much turn text should the hero artifact show?",),
        skill_notes=(
            {
                "skill": "FastAPI",
                "note": "Keep projections readable and typed.",
            },
        ),
    )


class RenderDebateTests(unittest.TestCase):
    def test_render_debate_includes_provenance_admission_and_handoff(self) -> None:
        fastapi = _skill_instance()
        trace = RunTrace(
            task=_task(),
            skills=(fastapi,),
            turns=(
                TurnRecord(
                    stage="survey",
                    round_index=1,
                    skill_instance_id=fastapi.instance_id,
                    skill_name=fastapi.spec.name,
                    message="FastAPI wants a narrow, typed boundary.",
                    result=TurnResult(
                        judgment="Keep the runtime contract explicit.",
                        evidence=("Pydantic contracts are inspectable.",),
                        tradeoff="Strict typing slows ad hoc iteration.",
                        objection="Do not let projections become a second semantic layer.",
                        needs_verification=("Confirm the artifact stays projection-only.",),
                        confidence="high",
                    ),
                ),
            ),
            synthesis=_synthesis(),
            created_at="20260410T120000Z",
            admission=AdmissionResult(
                status="accept_with_warning",
                reason="Session is runnable, but selected skill count is above the default (3).",
                candidate_skills=(
                    AdmissionCandidate(
                        slug="fastapi",
                        name="FastAPI",
                        score=3,
                        matched_terms=("fastapi", "contract"),
                    ),
                ),
                selected_skills=("fastapi",),
                rejected_skills=(
                    RejectedSkill(
                        slug="langgraph",
                        reason="Not selected in this run (default cap 3).",
                    ),
                ),
                warnings=("Broader skill sets reduce focus.",),
            ),
            harness=HarnessContract(
                version="v1",
                source_of_truth="SKILL.md",
                prompt_contract="SKILL.md acts as prompt, persona, and reasoning contract.",
                reduction_slots=("judgment", "evidence", "tradeoff", "objection", "needs_verification", "confidence"),
                mode="review",
                stage_order=("survey", "review", "synthesis"),
                rounds_per_stage={"survey": 1, "review": 1},
                selected_skill_slugs=("fastapi",),
                loaded_skill_slugs=("fastapi",),
                skills=(
                    HarnessSkillContract(
                        slug="fastapi",
                        name="FastAPI",
                        skill_file=str(fastapi.spec.skill_file),
                        skill_mtime=123.0,
                        prompt_sha256="demo-hash",
                    ),
                ),
                admission_status="accept_with_warning",
            ),
        )

        rendered = render_debate(trace)

        self.assertIn("## Participants & Provenance", rendered)
        self.assertIn("matched_terms: fastapi, contract", rendered)
        self.assertIn("warnings: Broader skill sets reduce focus.", rendered)
        self.assertIn("langgraph: Not selected in this run (default cap 3).", rendered)
        self.assertIn("## Debate Map", rendered)
        self.assertIn("handoff_path:", rendered)
        self.assertIn("selected_skill_slugs: fastapi", rendered)

    def test_render_debate_handles_missing_optional_fields_and_blocked_runs(self) -> None:
        trace = RunTrace(
            task=_task(),
            skills=(
                _skill_instance(
                    slug="ghost",
                    name="Ghost Skill",
                    description="",
                    tagline="",
                ),
            ),
            turns=(),
            synthesis=_synthesis(title="Blocked synthesis"),
            created_at="20260410T120500Z",
            admission=AdmissionResult(
                status="needs_clarification",
                reason="Clarify the brief before rerunning.",
                candidate_skills=(),
                selected_skills=(),
                warnings=("No selected skills for this session.",),
            ),
            harness=None,
        )

        rendered = render_debate(trace)

        self.assertIn("- boundary: n/a", rendered)
        self.assertIn("- prompt_sha256: n/a", rendered)
        self.assertIn("No debate turns recorded.", rendered)
        self.assertIn("No harness metadata captured.", rendered)
        self.assertIn("warnings: No selected skills for this session.", rendered)


if __name__ == "__main__":
    unittest.main()
