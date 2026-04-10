from __future__ import annotations

from pathlib import Path
from typing import Any

from ..redistill import build_redistill_work_items, execute_redistill_work_items, read_redistill_work_items, write_redistill_work_items
from ..failures import read_redistill_tickets


def emit_redistill_worklist_payload(
    *,
    repo_root: Path,
    ticket_root: Path,
    ticket_day: str | None,
    worklist_root: Path,
) -> dict[str, Any]:
    tickets = read_redistill_tickets(ticket_root, day=ticket_day)
    authoring_skill_file = repo_root / "authoring" / "project-incarnation" / "SKILL.md"
    work_items = build_redistill_work_items(
        tickets,
        repo_root=repo_root,
        authoring_skill_file=authoring_skill_file,
    )
    worklist_path = write_redistill_work_items(worklist_root, work_items)
    return {
        "ticket_root": str(ticket_root),
        "ticket_day": ticket_day or "today",
        "ticket_count": len(tickets),
        "worklist_root": str(worklist_root),
        "work_item_count": len(work_items),
        "worklist_path": str(worklist_path) if worklist_path is not None else None,
        "work_items": work_items,
    }


def execute_redistill_worklist_payload(
    *,
    worklist_root: Path,
    worklist_day: str | None,
    execution_root: Path,
    retry_failed: bool,
    dry_run: bool,
) -> dict[str, Any]:
    work_items = read_redistill_work_items(worklist_root, day=worklist_day)
    execution = execute_redistill_work_items(
        work_items,
        execution_root=execution_root,
        day=worklist_day,
        retry_failed=retry_failed,
        dry_run=dry_run,
    )
    return {
        "worklist_root": str(worklist_root),
        "worklist_day": worklist_day or "today",
        "execution_root": str(execution_root),
        **execution,
    }
