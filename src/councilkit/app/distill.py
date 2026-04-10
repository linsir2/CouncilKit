from __future__ import annotations

from pathlib import Path

from ..constants import RAW_TRACE_ROOT
from ..traces import distill_trace_artifacts


def distill_traces(
    *,
    repo_root: Path,
    output_root: Path,
    distill_from: Path | None,
    distill_all: bool,
) -> list[Path]:
    if distill_all:
        raw_root = repo_root / RAW_TRACE_ROOT
        trace_refs = sorted(path for path in raw_root.iterdir() if path.is_dir())
    else:
        if distill_from is None:
            raise ValueError("distill_from is required when distill_all is false")
        trace_refs = [distill_from]
    return [distill_trace_artifacts(trace_ref, output_root=output_root) for trace_ref in trace_refs]
