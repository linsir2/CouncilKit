from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

FAILURE_TAXONOMY_VERSION = "v1"
FAILURE_EVENT_FILE = "failure-events.jsonl"
REDISTILL_TICKET_VERSION = "v1"
CONTRACT_VERSION = "harness.v1"
DEFAULT_WINDOW_DAYS = 7
DEFAULT_DAILY_CAP = 3

VALID_STAGES = {"admission", "schedule", "dispatch", "synthesis", "ingest"}
VALID_LAYERS = {"runtime", "harness", "redistill"}
VALID_OWNERS = {"runtime", "harness", "redistill"}
VALID_ACTIONS = {"runtime_fix", "harness_fix", "redistill_request", "manual_triage"}
VALID_SEVERITIES = {"low", "medium", "high"}

FAILURE_CODE_POLICY: dict[str, dict[str, str]] = {
    "admission_needs_clarification": {
        "layer": "redistill",
        "owner": "redistill",
        "action": "redistill_request",
        "severity": "medium",
    },
    "admission_out_of_scope": {
        "layer": "harness",
        "owner": "harness",
        "action": "harness_fix",
        "severity": "medium",
    },
    "schedule_turn_count_mismatch": {
        "layer": "harness",
        "owner": "harness",
        "action": "harness_fix",
        "severity": "high",
    },
    "schedule_turn_order_mismatch": {
        "layer": "harness",
        "owner": "harness",
        "action": "harness_fix",
        "severity": "high",
    },
    "slot_missing_required": {
        "layer": "runtime",
        "owner": "runtime",
        "action": "runtime_fix",
        "severity": "high",
    },
    "slot_invalid_confidence": {
        "layer": "runtime",
        "owner": "runtime",
        "action": "runtime_fix",
        "severity": "medium",
    },
    "prompt_hash_mismatch": {
        "layer": "redistill",
        "owner": "redistill",
        "action": "redistill_request",
        "severity": "medium",
    },
    "synthesis_payload_invalid": {
        "layer": "runtime",
        "owner": "runtime",
        "action": "runtime_fix",
        "severity": "high",
    },
    "ingest_payload_invalid": {
        "layer": "harness",
        "owner": "harness",
        "action": "harness_fix",
        "severity": "high",
    },
}

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class FailureEvent:
    taxonomy_version: str
    event_id: str
    observed_at: str
    run_ref: str
    source_stage: str
    failure_code: str
    layer: str
    deterministic: bool
    repro_ref: str
    owner: str
    action: str
    severity: str
    contract_version: str = CONTRACT_VERSION
    skill_slugs: tuple[str, ...] = ()
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "taxonomy_version": self.taxonomy_version,
            "event_id": self.event_id,
            "observed_at": self.observed_at,
            "run_ref": self.run_ref,
            "source_stage": self.source_stage,
            "failure_code": self.failure_code,
            "layer": self.layer,
            "deterministic": self.deterministic,
            "repro_ref": self.repro_ref,
            "skill_slugs": list(self.skill_slugs),
            "owner": self.owner,
            "action": self.action,
            "severity": self.severity,
            "contract_version": self.contract_version,
        }
        if self.notes:
            payload["notes"] = self.notes
        return payload


@dataclass(frozen=True)
class FailurePolicy:
    window_days: int = DEFAULT_WINDOW_DAYS
    min_frequency: int = 2
    min_severity: str = "medium"
    daily_cap: int = DEFAULT_DAILY_CAP


def create_failure_event(
    *,
    run_ref: str,
    source_stage: str,
    failure_code: str,
    repro_ref: str,
    deterministic: bool,
    skill_slugs: tuple[str, ...] = (),
    notes: str | None = None,
    layer: str | None = None,
    owner: str | None = None,
    action: str | None = None,
    severity: str | None = None,
    observed_at: str | None = None,
) -> FailureEvent:
    policy = FAILURE_CODE_POLICY.get(failure_code)
    if policy is None:
        raise ValueError(f"Unsupported failure_code: {failure_code}")
    event = FailureEvent(
        taxonomy_version=FAILURE_TAXONOMY_VERSION,
        event_id=str(uuid4()),
        observed_at=observed_at or datetime.now(UTC).isoformat(),
        run_ref=run_ref,
        source_stage=source_stage,
        failure_code=failure_code,
        layer=layer or policy["layer"],
        deterministic=deterministic,
        repro_ref=repro_ref,
        skill_slugs=tuple(slug for slug in skill_slugs if slug),
        owner=owner or policy["owner"],
        action=action or policy["action"],
        severity=severity or policy["severity"],
        contract_version=CONTRACT_VERSION,
        notes=notes.strip() if notes else None,
    )
    validate_failure_event(event)
    return event


def validate_failure_event(event: FailureEvent) -> None:
    if event.taxonomy_version != FAILURE_TAXONOMY_VERSION:
        raise ValueError(f"Unsupported taxonomy_version: {event.taxonomy_version}")
    if not event.event_id:
        raise ValueError("event_id is required")
    if not event.run_ref:
        raise ValueError("run_ref is required")
    if event.source_stage not in VALID_STAGES:
        raise ValueError(f"Invalid source_stage: {event.source_stage}")
    if event.failure_code not in FAILURE_CODE_POLICY:
        raise ValueError(f"Unsupported failure_code: {event.failure_code}")
    if event.layer not in VALID_LAYERS:
        raise ValueError(f"Invalid layer: {event.layer}")
    if event.owner not in VALID_OWNERS:
        raise ValueError(f"Invalid owner: {event.owner}")
    if event.action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action: {event.action}")
    if event.severity not in VALID_SEVERITIES:
        raise ValueError(f"Invalid severity: {event.severity}")
    if not event.repro_ref:
        raise ValueError("repro_ref is required")
    _parse_iso(event.observed_at)


def write_failure_events(run_dir: Path, events: tuple[FailureEvent, ...]) -> Path | None:
    if not events:
        return None
    file_path = run_dir / FAILURE_EVENT_FILE
    with file_path.open("w", encoding="utf-8") as handle:
        for event in events:
            validate_failure_event(event)
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False))
            handle.write("\n")
    return file_path


def read_failure_events(raw_root: Path, *, window_days: int = DEFAULT_WINDOW_DAYS) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    lower_bound = now - timedelta(days=window_days)
    events: list[dict[str, Any]] = []
    if not raw_root.exists():
        return events

    for run_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        file_path = run_dir / FAILURE_EVENT_FILE
        if not file_path.exists():
            continue
        for raw_line in file_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            observed = _parse_iso(str(payload.get("observed_at", "")))
            if observed < lower_bound:
                continue
            events.append(payload)
    return events


def summarize_failure_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_code: dict[str, int] = {}
    by_owner: dict[str, int] = {}
    by_skill: dict[str, int] = {}
    for event in events:
        code = str(event.get("failure_code", "")).strip() or "unknown"
        owner = str(event.get("owner", "")).strip() or "unknown"
        by_code[code] = by_code.get(code, 0) + 1
        by_owner[owner] = by_owner.get(owner, 0) + 1
        for skill in event.get("skill_slugs", []):
            skill_slug = str(skill).strip()
            if not skill_slug:
                continue
            by_skill[skill_slug] = by_skill.get(skill_slug, 0) + 1

    return {
        "taxonomy_version": FAILURE_TAXONOMY_VERSION,
        "event_count": len(events),
        "by_code": _sorted_counts(by_code),
        "by_owner": _sorted_counts(by_owner),
        "by_skill": _sorted_counts(by_skill),
    }


def propose_redistill_tickets(
    events: list[dict[str, Any]],
    *,
    policy: FailurePolicy,
    existing_tickets: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    issued_today = existing_tickets or []
    existing_keys = {
        identity
        for identity in (_ticket_identity(item) for item in issued_today)
        if identity is not None
    }
    remaining_cap = max(policy.daily_cap - len(issued_today), 0)
    if remaining_cap <= 0:
        return []

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    min_rank = SEVERITY_RANK[policy.min_severity]

    for event in events:
        if str(event.get("owner", "")).strip() != "redistill":
            continue
        if str(event.get("action", "")).strip() != "redistill_request":
            continue
        code = str(event.get("failure_code", "")).strip()
        if not code:
            continue
        for skill in event.get("skill_slugs", []):
            skill_slug = str(skill).strip()
            if not skill_slug:
                continue
            groups.setdefault((skill_slug, code), []).append(event)

    candidates: list[dict[str, Any]] = []
    for (skill_slug, code), grouped in groups.items():
        ticket_identity = (skill_slug, code)
        if ticket_identity in existing_keys:
            continue
        frequency = len(grouped)
        max_severity = max(
            (str(item.get("severity", "low")).strip() for item in grouped),
            key=lambda value: SEVERITY_RANK.get(value, 0),
        )
        if frequency < policy.min_frequency:
            continue
        if SEVERITY_RANK.get(max_severity, 0) < min_rank:
            continue

        sample_refs = [
            {
                "event_id": str(item.get("event_id", "")).strip(),
                "run_ref": str(item.get("run_ref", "")).strip(),
            }
            for item in grouped[:3]
        ]
        candidates.append(
            {
                "ticket_version": REDISTILL_TICKET_VERSION,
                "ticket_id": str(uuid4()),
                "created_at": datetime.now(UTC).isoformat(),
                "skill_slug": skill_slug,
                "failure_code": code,
                "window_days": policy.window_days,
                "frequency": frequency,
                "max_severity": max_severity,
                "sample_event_refs": sample_refs,
                "reason": (
                    f"{skill_slug} hit {code} {frequency} times in {policy.window_days} days "
                    f"(max severity: {max_severity})."
                ),
            }
        )

    candidates.sort(
        key=lambda item: (
            -SEVERITY_RANK.get(str(item.get("max_severity", "low")), 0),
            -int(item.get("frequency", 0)),
            str(item.get("skill_slug", "")),
            str(item.get("failure_code", "")),
        )
    )
    return candidates[:remaining_cap]


def write_redistill_tickets(ticket_root: Path, tickets: list[dict[str, Any]]) -> Path | None:
    if not tickets:
        return None
    ticket_root.mkdir(parents=True, exist_ok=True)
    date_stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    filename = date_stamp + ".jsonl"
    file_path = ticket_root / filename
    existing_keys = {
        identity
        for identity in (_ticket_identity(item) for item in read_redistill_tickets(ticket_root, day=date_stamp))
        if identity is not None
    }
    deduped: list[dict[str, Any]] = []
    for ticket in tickets:
        identity = _ticket_identity(ticket)
        if identity is None or identity in existing_keys:
            continue
        existing_keys.add(identity)
        deduped.append(ticket)
    if not deduped:
        return None
    with file_path.open("a", encoding="utf-8") as handle:
        for ticket in deduped:
            handle.write(json.dumps(ticket, ensure_ascii=False))
            handle.write("\n")
    return file_path


def read_redistill_tickets(ticket_root: Path, *, day: str | None = None) -> list[dict[str, Any]]:
    date_stamp = day or datetime.now(UTC).strftime("%Y-%m-%d")
    file_path = ticket_root / f"{date_stamp}.jsonl"
    if not file_path.exists():
        return []
    tickets: list[dict[str, Any]] = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            tickets.append(payload)
    return tickets


def _sorted_counts(counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"key": key, "count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("observed_at is required")
    normalized = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _ticket_identity(ticket: dict[str, Any]) -> tuple[str, str] | None:
    skill_slug = str(ticket.get("skill_slug", "")).strip()
    failure_code = str(ticket.get("failure_code", "")).strip()
    if not skill_slug or not failure_code:
        return None
    return (skill_slug, failure_code)
