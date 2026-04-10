import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from src.councilkit.failures import (
    FailurePolicy,
    create_failure_event,
    propose_redistill_tickets,
    read_redistill_tickets,
    read_failure_events,
    summarize_failure_events,
    validate_failure_event,
    write_redistill_tickets,
)


class FailureEventTests(unittest.TestCase):
    def test_create_failure_event_uses_policy_defaults(self) -> None:
        event = create_failure_event(
            run_ref="traces/raw/demo/run.json",
            source_stage="admission",
            failure_code="admission_needs_clarification",
            repro_ref="traces/raw/demo/run.json",
            deterministic=True,
            skill_slugs=("fastapi",),
        )
        validate_failure_event(event)
        payload = event.to_dict()
        self.assertEqual(payload["owner"], "redistill")
        self.assertEqual(payload["action"], "redistill_request")
        self.assertEqual(payload["severity"], "medium")
        self.assertEqual(payload["skill_slugs"], ["fastapi"])

    def test_propose_redistill_tickets_respects_thresholds_and_cap(self) -> None:
        now = datetime.now(UTC).isoformat()
        events = [
            {
                "event_id": "a1",
                "observed_at": now,
                "run_ref": "traces/raw/a/run.json",
                "failure_code": "prompt_hash_mismatch",
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "skill_slugs": ["fastapi"],
            },
            {
                "event_id": "a2",
                "observed_at": now,
                "run_ref": "traces/raw/b/run.json",
                "failure_code": "prompt_hash_mismatch",
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "high",
                "skill_slugs": ["fastapi"],
            },
            {
                "event_id": "b1",
                "observed_at": now,
                "run_ref": "traces/raw/c/run.json",
                "failure_code": "admission_needs_clarification",
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "skill_slugs": ["dtnds"],
            },
            {
                "event_id": "b2",
                "observed_at": now,
                "run_ref": "traces/raw/d/run.json",
                "failure_code": "admission_needs_clarification",
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "skill_slugs": ["dtnds"],
            },
        ]
        tickets = propose_redistill_tickets(events, policy=FailurePolicy(window_days=7, daily_cap=1))
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["skill_slug"], "fastapi")
        self.assertEqual(tickets[0]["failure_code"], "prompt_hash_mismatch")

    def test_read_and_summarize_failure_events_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_a = root / "run-a"
            run_b = root / "run-b"
            run_a.mkdir(parents=True, exist_ok=True)
            run_b.mkdir(parents=True, exist_ok=True)
            fresh = create_failure_event(
                run_ref=str(run_a / "run.json"),
                source_stage="ingest",
                failure_code="prompt_hash_mismatch",
                repro_ref=str(run_a / "input.json"),
                deterministic=True,
                skill_slugs=("fastapi",),
            ).to_dict()
            old = create_failure_event(
                run_ref=str(run_b / "run.json"),
                source_stage="ingest",
                failure_code="prompt_hash_mismatch",
                repro_ref=str(run_b / "input.json"),
                deterministic=True,
                skill_slugs=("fastapi",),
            ).to_dict()
            old["observed_at"] = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            (run_a / "failure-events.jsonl").write_text(json.dumps(fresh, ensure_ascii=False) + "\n", encoding="utf-8")
            (run_b / "failure-events.jsonl").write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")

            events = read_failure_events(root, window_days=7)
            self.assertEqual(len(events), 1)
            summary = summarize_failure_events(events)
            self.assertEqual(summary["event_count"], 1)
            self.assertEqual(summary["by_code"][0]["key"], "prompt_hash_mismatch")

    def test_write_redistill_tickets(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ticket = {
                "ticket_version": "v1",
                "ticket_id": "t-1",
                "created_at": datetime.now(UTC).isoformat(),
                "skill_slug": "fastapi",
                "failure_code": "prompt_hash_mismatch",
                "window_days": 7,
                "frequency": 2,
                "max_severity": "medium",
                "sample_event_refs": [],
                "reason": "demo",
            }
            path = write_redistill_tickets(root, [ticket])
            self.assertIsNotNone(path)
            self.assertTrue(path.exists())
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["ticket_id"], "t-1")

    def test_propose_redistill_tickets_honors_existing_daily_tickets(self) -> None:
        now = datetime.now(UTC).isoformat()
        events = [
            {
                "event_id": "a1",
                "observed_at": now,
                "run_ref": "traces/raw/a/run.json",
                "failure_code": "prompt_hash_mismatch",
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "skill_slugs": ["fastapi"],
            },
            {
                "event_id": "a2",
                "observed_at": now,
                "run_ref": "traces/raw/b/run.json",
                "failure_code": "prompt_hash_mismatch",
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "skill_slugs": ["fastapi"],
            },
            {
                "event_id": "b1",
                "observed_at": now,
                "run_ref": "traces/raw/c/run.json",
                "failure_code": "admission_needs_clarification",
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "skill_slugs": ["dtnds"],
            },
            {
                "event_id": "b2",
                "observed_at": now,
                "run_ref": "traces/raw/d/run.json",
                "failure_code": "admission_needs_clarification",
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "skill_slugs": ["dtnds"],
            },
        ]
        existing = [
            {
                "ticket_version": "v1",
                "ticket_id": "existing-1",
                "skill_slug": "fastapi",
                "failure_code": "prompt_hash_mismatch",
            }
        ]

        none_left = propose_redistill_tickets(
            events,
            policy=FailurePolicy(window_days=7, daily_cap=1),
            existing_tickets=existing,
        )
        self.assertEqual(none_left, [])

        one_left = propose_redistill_tickets(
            events,
            policy=FailurePolicy(window_days=7, daily_cap=2),
            existing_tickets=existing,
        )
        self.assertEqual(len(one_left), 1)
        self.assertEqual(one_left[0]["skill_slug"], "dtnds")
        self.assertEqual(one_left[0]["failure_code"], "admission_needs_clarification")

    def test_write_redistill_tickets_dedupes_same_skill_and_failure_code(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_ticket = {
                "ticket_version": "v1",
                "ticket_id": "t-1",
                "created_at": datetime.now(UTC).isoformat(),
                "skill_slug": "fastapi",
                "failure_code": "prompt_hash_mismatch",
                "window_days": 7,
                "frequency": 2,
                "max_severity": "medium",
                "sample_event_refs": [],
                "reason": "demo",
            }
            first_path = write_redistill_tickets(root, [base_ticket])
            self.assertIsNotNone(first_path)
            duplicate_ticket = dict(base_ticket)
            duplicate_ticket["ticket_id"] = "t-2"
            second_path = write_redistill_tickets(root, [duplicate_ticket])
            self.assertIsNone(second_path)

            tickets = read_redistill_tickets(root)
            self.assertEqual(len(tickets), 1)
            self.assertEqual(tickets[0]["ticket_id"], "t-1")


if __name__ == "__main__":
    unittest.main()
