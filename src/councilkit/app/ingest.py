from __future__ import annotations

from pathlib import Path

from ..harness_ingest import ingest_session_run, validate_session_run_payload


def ingest_dispatch_run(
    *,
    repo_root: Path,
    payload_ref: Path,
    output_root: Path,
    directory_name: str | None,
    strict_hash: bool,
) -> Path:
    return ingest_session_run(
        payload_ref=payload_ref,
        repo_root=repo_root,
        output_root=output_root,
        directory_name=directory_name,
        strict_hash=strict_hash,
    )


def validate_dispatch_run(
    *,
    repo_root: Path,
    payload_ref: Path,
    strict_hash: bool,
):
    return validate_session_run_payload(
        payload_ref=payload_ref,
        repo_root=repo_root,
        strict_hash=strict_hash,
    )
