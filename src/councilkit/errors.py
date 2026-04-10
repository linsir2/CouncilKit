from __future__ import annotations


class CouncilKitValidationError(ValueError):
    """Base class for structured validation errors in runtime and harness ingest."""


class TurnPayloadValidationError(CouncilKitValidationError):
    failure_code = "slot_missing_required"


class TurnSlotMissingError(TurnPayloadValidationError):
    failure_code = "slot_missing_required"


class TurnConfidenceInvalidError(TurnPayloadValidationError):
    failure_code = "slot_invalid_confidence"


class SynthesisPayloadInvalidError(CouncilKitValidationError):
    failure_code = "synthesis_payload_invalid"


class ScheduleTurnCountMismatchError(CouncilKitValidationError):
    failure_code = "schedule_turn_count_mismatch"


class ScheduleTurnOrderMismatchError(CouncilKitValidationError):
    failure_code = "schedule_turn_order_mismatch"


class SlotMissingRequiredError(CouncilKitValidationError):
    failure_code = "slot_missing_required"


class SlotInvalidConfidenceError(CouncilKitValidationError):
    failure_code = "slot_invalid_confidence"


class IngestPayloadInvalidError(CouncilKitValidationError):
    failure_code = "ingest_payload_invalid"

