import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.councilkit.harness_runtime import (
    build_turn_schedule,
    dispatch_turns,
    render_transcript,
    to_turn_records,
)
from src.councilkit.models import SkillInstance, SkillSpec


def _make_session_spec() -> dict[str, object]:
    return {
        "stages": [
            {"stage": "survey", "rounds": 1},
            {"stage": "review", "rounds": 2},
            {"stage": "synthesis", "rounds": 0},
        ],
        "participants": [
            {"slug": "fastapi", "name": "FastAPI"},
            {"slug": "do-things-that-dont-scale", "name": "Do Things That Don't Scale"},
        ],
    }


class HarnessRuntimeTests(unittest.TestCase):
    def test_build_turn_schedule_rotates_participants_by_round(self) -> None:
        schedule = build_turn_schedule(_make_session_spec())
        self.assertEqual(len(schedule), 6)
        self.assertEqual(
            [(item.stage, item.round_index, item.skill_slug) for item in schedule],
            [
                ("survey", 1, "fastapi"),
                ("survey", 1, "do-things-that-dont-scale"),
                ("review", 1, "fastapi"),
                ("review", 1, "do-things-that-dont-scale"),
                ("review", 2, "do-things-that-dont-scale"),
                ("review", 2, "fastapi"),
            ],
        )

    def test_dispatch_to_turn_records_and_transcript_adapter(self) -> None:
        schedule = build_turn_schedule(_make_session_spec())

        def dispatcher(turn):
            return {
                "message": f"{turn.skill_name} on {turn.stage}.",
                "judgment": f"{turn.skill_name} judgment.",
                "evidence": [f"{turn.skill_name} evidence"],
                "tradeoff": f"{turn.skill_name} tradeoff.",
                "objection": f"{turn.skill_name} objection.",
                "needs_verification": [f"{turn.skill_name} verify"],
                "confidence": "high",
            }

        dispatched = dispatch_turns(schedule, dispatcher)
        transcript = render_transcript("Review API contracts.", dispatched)
        self.assertIn("# Harness Runtime Transcript", transcript)
        self.assertIn("## survey", transcript)
        self.assertIn("## review", transcript)
        self.assertIn("- confidence: high", transcript)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fastapi_file = root / "fastapi.md"
            dtnds_file = root / "dtnds.md"
            fastapi_file.write_text("fastapi", encoding="utf-8")
            dtnds_file.write_text("dtnds", encoding="utf-8")

            instances = (
                SkillInstance(
                    spec=SkillSpec(
                        slug="fastapi",
                        name="FastAPI",
                        description="",
                        tagline="",
                        skill_markdown="fastapi",
                        skill_dir=root,
                        skill_file=fastapi_file,
                        skill_mtime=None,
                    ),
                    instance_id="fastapi-instance",
                ),
                SkillInstance(
                    spec=SkillSpec(
                        slug="do-things-that-dont-scale",
                        name="Do Things That Don't Scale",
                        description="",
                        tagline="",
                        skill_markdown="dtnds",
                        skill_dir=root,
                        skill_file=dtnds_file,
                        skill_mtime=None,
                    ),
                    instance_id="dtnds-instance",
                ),
            )
            records = to_turn_records(dispatched, skill_instances=instances)
            self.assertEqual(len(records), 6)
            self.assertEqual(records[0].skill_instance_id, "fastapi-instance")
            self.assertEqual(records[-1].skill_instance_id, "fastapi-instance")

    def test_dispatch_turns_rejects_missing_reduction_slot(self) -> None:
        schedule = build_turn_schedule(
            {
                "stages": [{"stage": "survey", "rounds": 1}],
                "participants": [{"slug": "fastapi", "name": "FastAPI"}],
            }
        )

        def bad_dispatcher(_turn):
            return {
                "judgment": "x",
                "evidence": ["x"],
                "tradeoff": "x",
                "objection": "x",
                "confidence": "high",
            }

        with self.assertRaises(ValueError):
            dispatch_turns(schedule, bad_dispatcher)


if __name__ == "__main__":
    unittest.main()
