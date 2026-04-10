from __future__ import annotations

from pathlib import Path
from typing import Any

from ..failures import (
    FailurePolicy,
    propose_redistill_tickets,
    read_failure_events,
    read_redistill_tickets,
    summarize_failure_events,
    write_redistill_tickets,
)


def summarize_failures_payload(
    *,
    failure_root: Path,
    window_days: int,
) -> dict[str, Any]:
    events = read_failure_events(failure_root, window_days=window_days)
    return {
        "window_days": window_days,
        "failure_root": str(failure_root),
        "summary": summarize_failure_events(events),
    }


def propose_redistill_payload(
    *,
    failure_root: Path,
    window_days: int,
    daily_cap: int,
    ticket_root: Path,
    dry_run: bool,
) -> dict[str, Any]:
    events = read_failure_events(failure_root, window_days=window_days)
    summary = summarize_failure_events(events)
    policy = FailurePolicy(window_days=window_days, daily_cap=daily_cap)
    existing_tickets = read_redistill_tickets(ticket_root)
    tickets = propose_redistill_tickets(
        events,
        policy=policy,
        existing_tickets=existing_tickets,
    )
    ticket_path = None
    if not dry_run:
        ticket_path = write_redistill_tickets(ticket_root, tickets)
    return {
        "window_days": window_days,
        "daily_cap": daily_cap,
        "existing_ticket_count": len(existing_tickets),
        "remaining_cap": max(daily_cap - len(existing_tickets), 0),
        "event_count": len(events),
        "ticket_count": len(tickets),
        "ticket_path": str(ticket_path) if ticket_path is not None else None,
        "tickets": tickets,
        "summary": summary,
    }
