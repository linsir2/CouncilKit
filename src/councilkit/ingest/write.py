from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ..errors import (
    IngestPayloadInvalidError,
    ScheduleTurnCountMismatchError,
    ScheduleTurnOrderMismatchError,
    SlotInvalidConfidenceError,
    SlotMissingRequiredError,
    SynthesisPayloadInvalidError,
)
from ..failures import FailureEvent, create_failure_event, write_failure_events
from ..traces import write_trace_artifacts
from .map import prepare_ingest_trace
from .parse import read_ingest_payload, selected_skill_slugs_from_payload
from .reporting import _map_ingest_failure_code


def ingest_session_run(
    *,
    payload_ref: Path,
    repo_root: Path,
    output_root: Path,
    directory_name: str | None = None,
    strict_hash: bool = True,
) -> Path:
    fallback_dir_name = directory_name or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir_hint = output_root / fallback_dir_name
    try:
        payload = read_ingest_payload(payload_ref)
        created_at = str(payload.get("created_at", "")).strip() or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        final_dir_name = directory_name or str(payload.get("directory_name", "")).strip() or created_at
        run_dir_hint = output_root / final_dir_name
        prepared = prepare_ingest_trace(
            payload=payload,
            payload_ref=payload_ref,
            repo_root=repo_root,
            strict_hash=strict_hash,
            created_at=created_at,
        )
        run_dir = write_trace_artifacts(
            prepared.trace,
            output_root=output_root,
            directory_name=final_dir_name,
            model=prepared.model,
            base_url=prepared.base_url,
        )
        if prepared.pending_failures:
            run_ref = str(run_dir / "run.json")
            repro_ref = str(payload_ref)
            events: list[FailureEvent] = []
            for failure in prepared.pending_failures:
                events.append(
                    create_failure_event(
                        run_ref=run_ref,
                        source_stage=str(failure["source_stage"]),
                        failure_code=str(failure["failure_code"]),
                        repro_ref=repro_ref,
                        deterministic=bool(failure["deterministic"]),
                        skill_slugs=tuple(str(item) for item in failure.get("skill_slugs", ()) if str(item).strip()),
                        notes=str(failure.get("notes", "")).strip() or None,
                    )
                )
            write_failure_events(run_dir, tuple(events))
        return run_dir
    except IngestPayloadInvalidError as error:
        _persist_ingest_failure_event(
            run_dir=run_dir_hint,
            payload_ref=payload_ref,
            failure_code="ingest_payload_invalid",
            notes=str(error),
            skill_slugs=(),
        )
        raise
    except (
        ScheduleTurnCountMismatchError,
        ScheduleTurnOrderMismatchError,
        SlotMissingRequiredError,
        SlotInvalidConfidenceError,
        SynthesisPayloadInvalidError,
        IngestPayloadInvalidError,
    ) as error:
        _persist_ingest_failure_event(
            run_dir=run_dir_hint,
            payload_ref=payload_ref,
            failure_code=_map_ingest_failure_code(error),
            notes=str(error),
            skill_slugs=selected_skill_slugs_from_payload(payload_ref),
        )
        raise
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as error:
        _persist_ingest_failure_event(
            run_dir=run_dir_hint,
            payload_ref=payload_ref,
            failure_code=_map_ingest_failure_code(error),
            notes=str(error),
            skill_slugs=selected_skill_slugs_from_payload(payload_ref),
        )
        raise


def _persist_ingest_failure_event(
    *,
    run_dir: Path,
    payload_ref: Path,
    failure_code: str,
    notes: str,
    skill_slugs: tuple[str, ...],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    event = create_failure_event(
        run_ref=str(run_dir / "run.json"),
        source_stage="ingest",
        failure_code=failure_code,
        repro_ref=str(payload_ref),
        deterministic=True,
        skill_slugs=skill_slugs,
        notes=notes,
    )
    write_failure_events(run_dir, (event,))
