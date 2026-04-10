import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.councilkit.errors import (
    ScheduleTurnOrderMismatchError,
    SlotInvalidConfidenceError,
    SlotMissingRequiredError,
    SynthesisPayloadInvalidError,
    TurnSlotMissingError,
)
from src.councilkit.harness_runtime import build_turn_schedule
from src.councilkit.models import HarnessContract, HarnessSkillContract
from src.councilkit.validation import (
    normalize_dispatch_turn_payload,
    normalize_runtime_turn_payload,
    normalize_synthesis_payload,
    validate_declared_turn_schedule,
    validate_harness_contract,
    validate_turn_sequence_item,
)


class ValidationTests(unittest.TestCase):
    def test_runtime_turn_payload_requires_message_slot(self) -> None:
        with self.assertRaises(TurnSlotMissingError):
            normalize_runtime_turn_payload(
                {
                    "judgment": "x",
                    "evidence": ["x"],
                    "tradeoff": "x",
                    "objection": "x",
                    "needs_verification": [],
                    "confidence": "high",
                }
            )

    def test_dispatch_turn_payload_requires_all_reduction_slots(self) -> None:
        with self.assertRaises(SlotMissingRequiredError):
            normalize_dispatch_turn_payload(
                {
                    "judgment": "x",
                    "evidence": ["x"],
                    "tradeoff": "x",
                    "objection": "x",
                    "confidence": "high",
                }
            )

    def test_dispatch_turn_payload_rejects_invalid_confidence(self) -> None:
        with self.assertRaises(SlotInvalidConfidenceError):
            normalize_dispatch_turn_payload(
                {
                    "judgment": "x",
                    "evidence": ["x"],
                    "tradeoff": "x",
                    "objection": "x",
                    "needs_verification": [],
                    "confidence": "certain",
                }
            )

    def test_synthesis_payload_requires_title(self) -> None:
        with self.assertRaises(SynthesisPayloadInvalidError):
            normalize_synthesis_payload(
                {
                    "summary": "x",
                    "decision": "x",
                    "key_decisions": ["x"],
                    "strongest_objections": [{"skill": "FastAPI", "objection": "x", "severity": "medium"}],
                    "next_steps": ["x"],
                    "open_questions": [],
                    "skill_notes": [{"skill": "FastAPI", "note": "x"}],
                }
            )

    def test_contract_validation_rejects_selected_skill_missing_from_loaded(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_file = root / "fastapi.md"
            skill_file.write_text("fastapi", encoding="utf-8")
            contract = HarnessContract(
                version="v1",
                source_of_truth="SKILL.md",
                prompt_contract="SKILL.md acts as prompt, persona, and reasoning contract.",
                reduction_slots=("judgment", "evidence", "tradeoff", "objection", "needs_verification", "confidence"),
                mode="review",
                stage_order=("survey", "review", "synthesis"),
                rounds_per_stage={"survey": 1, "review": 1},
                selected_skill_slugs=("fastapi",),
                loaded_skill_slugs=(),
                skills=(
                    HarnessSkillContract(
                        slug="fastapi",
                        name="FastAPI",
                        skill_file=str(skill_file),
                        skill_mtime=None,
                        prompt_sha256="invalid",
                    ),
                ),
                admission_status="accept",
            )
            report = validate_harness_contract(
                contract,
                strict_hash=True,
                resolve_skill_path=lambda raw_path: Path(raw_path),
            )
            self.assertEqual(report.status, "fail")
            self.assertTrue(any(item.code == "selected_skill_not_loaded" for item in report.issues))

    def test_declared_schedule_rejects_drift(self) -> None:
        schedule = build_turn_schedule(
            {
                "stages": [
                    {"stage": "survey", "rounds": 1},
                    {"stage": "review", "rounds": 1},
                ],
                "participants": [
                    {"slug": "fastapi", "name": "FastAPI"},
                ],
            }
        )
        bad_payload = [
            {
                "turn_index": 1,
                "stage": "survey",
                "round_index": 1,
                "skill_slug": "fastapi",
                "skill_name": "FastAPI",
            },
            {
                "turn_index": 2,
                "stage": "survey",
                "round_index": 1,
                "skill_slug": "fastapi",
                "skill_name": "FastAPI",
            },
        ]
        with self.assertRaises(ScheduleTurnOrderMismatchError):
            validate_declared_turn_schedule(schedule, bad_payload)

    def test_turn_sequence_item_rejects_stage_drift(self) -> None:
        schedule = build_turn_schedule(
            {
                "stages": [{"stage": "survey", "rounds": 1}],
                "participants": [{"slug": "fastapi", "name": "FastAPI"}],
            }
        )
        with self.assertRaises(ScheduleTurnOrderMismatchError):
            validate_turn_sequence_item(
                {
                    "stage": "review",
                    "round_index": 1,
                    "skill_slug": "fastapi",
                },
                schedule[0],
                index=1,
            )


if __name__ == "__main__":
    unittest.main()
