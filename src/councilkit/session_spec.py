from __future__ import annotations

from typing import Any

from .harness_runtime import build_turn_schedule
from .models import AdmissionResult, HarnessContract

SESSION_SPEC_VERSION = "v1"


def build_session_spec(
    *,
    harness: HarnessContract,
    admission: AdmissionResult | None = None,
) -> dict[str, Any]:
    stages = [
        {
            "stage": stage,
            "rounds": int(harness.rounds_per_stage.get(stage, 0)),
        }
        for stage in harness.stage_order
    ]
    participants = [
        {
            "slug": skill.slug,
            "name": skill.name,
            "skill_file": skill.skill_file,
            "prompt_sha256": skill.prompt_sha256,
        }
        for skill in harness.skills
    ]

    admission_status = admission.status if admission is not None else harness.admission_status
    admission_warnings = list(admission.warnings) if admission is not None else []
    turn_schedule = [
        {
            "turn_index": turn.turn_index,
            "stage": turn.stage,
            "round_index": turn.round_index,
            "skill_slug": turn.skill_slug,
            "skill_name": turn.skill_name,
        }
        for turn in build_turn_schedule(
            {
                "stages": stages,
                "participants": participants,
            }
        )
    ]

    return {
        "version": SESSION_SPEC_VERSION,
        "mode": harness.mode,
        "source_of_truth": harness.source_of_truth,
        "prompt_contract": harness.prompt_contract,
        "reduction_slots": list(harness.reduction_slots),
        "stages": stages,
        "participants": participants,
        "selected_skill_slugs": list(harness.selected_skill_slugs),
        "loaded_skill_slugs": list(harness.loaded_skill_slugs),
        "turn_schedule": turn_schedule,
        "admission": {
            "status": admission_status,
            "warnings": admission_warnings,
        },
    }
