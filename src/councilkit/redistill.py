from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

WORKLIST_VERSION = "v1"
EXECUTION_VERSION = "v1"


def build_redistill_work_items(
    tickets: list[dict[str, Any]],
    *,
    repo_root: Path,
    authoring_skill_file: Path,
) -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    items: list[dict[str, Any]] = []
    for ticket in tickets:
        skill_slug = str(ticket.get("skill_slug", "")).strip()
        failure_code = str(ticket.get("failure_code", "")).strip()
        ticket_id = str(ticket.get("ticket_id", "")).strip()
        reason = str(ticket.get("reason", "")).strip()
        if not skill_slug or not failure_code:
            continue
        target_skill_file = repo_root / "skills" / skill_slug / "SKILL.md"
        work_item = {
            "work_version": WORKLIST_VERSION,
            "work_id": str(uuid4()),
            "created_at": now,
            "ticket_id": ticket_id or None,
            "skill_slug": skill_slug,
            "failure_code": failure_code,
            "failure_reason": reason,
            "target_skill_file": str(target_skill_file),
            "authoring_skill_file": str(authoring_skill_file),
            "objective": (
                f"Update skill '{skill_slug}' to address recurring failure '{failure_code}' "
                "without breaking single-file independence."
            ),
            "constraints": [
                "Keep child SKILL.md self-contained.",
                "Do not add harness-only semantic fields to child SKILL.md.",
                "Preserve six-slot reducibility for harness projection.",
                "Keep canonical path in skills/<slug>/SKILL.md.",
            ],
            "suggested_command": (
                "Use authoring/project-incarnation with this ticket context to update "
                f"skills/{skill_slug}/SKILL.md."
            ),
            "prompt_template": _build_prompt_template(
                skill_slug=skill_slug,
                failure_code=failure_code,
                reason=reason,
            ),
        }
        items.append(work_item)
    return items


def write_redistill_work_items(work_root: Path, items: list[dict[str, Any]]) -> Path | None:
    if not items:
        return None
    work_root.mkdir(parents=True, exist_ok=True)
    date_stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    file_path = work_root / f"{date_stamp}.jsonl"
    with file_path.open("a", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False))
            handle.write("\n")
    return file_path


def read_redistill_work_items(work_root: Path, *, day: str | None = None) -> list[dict[str, Any]]:
    date_stamp = day or datetime.now(UTC).strftime("%Y-%m-%d")
    file_path = work_root / f"{date_stamp}.jsonl"
    if not file_path.exists():
        return []
    payloads: list[dict[str, Any]] = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def execute_redistill_work_items(
    work_items: list[dict[str, Any]],
    *,
    execution_root: Path,
    day: str | None = None,
    retry_failed: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    date_stamp = day or datetime.now(UTC).strftime("%Y-%m-%d")
    latest_status = _read_latest_execution_status(execution_root, day=date_stamp)

    completed = 0
    failed = 0
    skipped = 0
    planned = 0
    records: list[dict[str, Any]] = []
    for item in work_items:
        work_id = str(item.get("work_id", "")).strip()
        if not work_id:
            continue
        prior_status = latest_status.get(work_id)
        if prior_status in {"prepared", "succeeded"}:
            skipped += 1
            continue
        if prior_status == "failed" and not retry_failed:
            skipped += 1
            continue
        if dry_run:
            planned += 1
            continue

        target_skill_file = Path(str(item.get("target_skill_file", "")).strip())
        authoring_skill_file = Path(str(item.get("authoring_skill_file", "")).strip())
        if not target_skill_file.exists() or not authoring_skill_file.exists():
            failed += 1
            reason = "target_skill_file missing" if not target_skill_file.exists() else "authoring_skill_file missing"
            records.append(_build_execution_record(work_id=work_id, status="failed", reason=reason, artifact_ref=None))
            continue

        request_dir = execution_root / "requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"{work_id}.md"
        request_path.write_text(_render_execution_request(item), encoding="utf-8")
        completed += 1
        records.append(
            _build_execution_record(
                work_id=work_id,
                status="prepared",
                reason="execution request prepared",
                artifact_ref=str(request_path),
            )
        )

    record_path = None
    if records and not dry_run:
        record_path = write_redistill_execution_records(execution_root, records, day=date_stamp)
    return {
        "work_item_count": len(work_items),
        "planned_count": planned,
        "prepared_count": completed,
        "failed_count": failed,
        "skipped_count": skipped,
        "record_path": str(record_path) if record_path is not None else None,
        "dry_run": dry_run,
        "retry_failed": retry_failed,
        "day": date_stamp,
    }


def write_redistill_execution_records(
    execution_root: Path,
    records: list[dict[str, Any]],
    *,
    day: str | None = None,
) -> Path | None:
    if not records:
        return None
    date_stamp = day or datetime.now(UTC).strftime("%Y-%m-%d")
    execution_root.mkdir(parents=True, exist_ok=True)
    file_path = execution_root / f"{date_stamp}.jsonl"
    with file_path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
    return file_path


def _read_latest_execution_status(execution_root: Path, *, day: str | None = None) -> dict[str, str]:
    date_stamp = day or datetime.now(UTC).strftime("%Y-%m-%d")
    file_path = execution_root / f"{date_stamp}.jsonl"
    if not file_path.exists():
        return {}
    latest: dict[str, str] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        work_id = str(payload.get("work_id", "")).strip()
        status = str(payload.get("status", "")).strip()
        if work_id and status:
            latest[work_id] = status
    return latest


def _build_execution_record(
    *,
    work_id: str,
    status: str,
    reason: str,
    artifact_ref: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "execution_version": EXECUTION_VERSION,
        "execution_id": str(uuid4()),
        "executed_at": datetime.now(UTC).isoformat(),
        "work_id": work_id,
        "status": status,
        "reason": reason,
    }
    if artifact_ref:
        payload["artifact_ref"] = artifact_ref
    return payload


def _render_execution_request(item: dict[str, Any]) -> str:
    lines = [
        "# Redistill Execution Request",
        "",
        f"- work_id: {item.get('work_id', '')}",
        f"- ticket_id: {item.get('ticket_id', '')}",
        f"- skill_slug: {item.get('skill_slug', '')}",
        f"- failure_code: {item.get('failure_code', '')}",
        f"- target_skill_file: {item.get('target_skill_file', '')}",
        "",
        "## Objective",
        str(item.get("objective", "")).strip(),
        "",
        "## Constraints",
    ]
    constraints = item.get("constraints", [])
    if isinstance(constraints, list):
        for entry in constraints:
            text = str(entry).strip()
            if text:
                lines.append(f"- {text}")
    lines.extend(
        [
            "",
            "## Prompt Template",
            str(item.get("prompt_template", "")).strip(),
            "",
        ]
    )
    return "\n".join(lines)


def _build_prompt_template(*, skill_slug: str, failure_code: str, reason: str) -> str:
    return (
        f"更新子 skill: {skill_slug}\n"
        f"失败信号: {failure_code}\n"
        f"触发原因: {reason or 'n/a'}\n\n"
        "要求:\n"
        "- 只修改 skills/<slug>/SKILL.md\n"
        "- 保持单文件自包含，不新增 sidecar\n"
        "- 不添加 harness 语义字段到子 skill\n"
        "- 强化误判警报、watchlist、边界与证据路径\n"
        "- 输出后可稳定归约到六槽位接口\n"
    )
