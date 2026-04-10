from __future__ import annotations

import argparse
import json
from pathlib import Path

from .admission import prepare_session
from .constants import (
    DISTILLED_TRACE_ROOT,
    RAW_TRACE_ROOT,
    REDISTILL_EXECUTION_ROOT,
    REDISTILL_TICKET_ROOT,
    REDISTILL_WORKLIST_ROOT,
    SKILL_ROOT,
)
from .dispatch_template import build_dispatch_template, load_dispatch_template_inputs
from .failures import (
    FailurePolicy,
    propose_redistill_tickets,
    read_failure_events,
    read_redistill_tickets,
    summarize_failure_events,
    write_redistill_tickets,
)
from .harness_contract import build_harness_contract
from .harness import load_harness_payload, validate_harness_contract
from .harness_ingest import ingest_session_run, validate_session_run_payload
from .loader import load_prompt, load_skill_specs
from .models import SkillInstance
from .modes import DEFAULT_MODE_SPEC
from .redistill import build_redistill_work_items, write_redistill_work_items
from .redistill import execute_redistill_work_items, read_redistill_work_items
from .runtime import run
from .session_spec import build_session_spec
from .traces import distill_trace_artifacts


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run the CouncilKit single-file skill runtime baseline.")
    parser.add_argument("--prompt", help="Optional inline brief. Ignored when --brief is provided.")
    parser.add_argument(
        "--brief",
        help="Optional markdown/text brief file. Defaults to examples/briefs/ai-support-backend.md",
    )
    parser.add_argument(
        "--skills",
        help="Comma-separated skill names or skill directories. Defaults to every skill under --skill-root.",
    )
    parser.add_argument(
        "--skill-root",
        default=str(SKILL_ROOT),
        help="Skill root used when resolving names. Defaults to skills/.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root to snapshot during runtime. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Directory where artifacts will be written. Defaults to traces/raw or traces/distilled for distill mode.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable real-time terminal logs.",
    )
    parser.add_argument(
        "--distill-from",
        help="Distill one raw trace directory or run.json file into traces/distilled.",
    )
    parser.add_argument(
        "--distill-all",
        action="store_true",
        help="Distill every trace directory under traces/raw into traces/distilled.",
    )
    parser.add_argument(
        "--emit-harness-contract",
        action="store_true",
        help="Emit the runtime harness contract and admission result without running model turns.",
    )
    parser.add_argument(
        "--contract-output",
        default=None,
        help="Optional output path for --emit-harness-contract. Defaults to stdout.",
    )
    parser.add_argument(
        "--verify-harness-contract",
        default=None,
        help="Validate a harness contract payload file or run trace run.json path.",
    )
    parser.add_argument(
        "--ignore-hash-mismatch",
        action="store_true",
        help="Downgrade prompt hash mismatches to warnings in --verify-harness-contract mode.",
    )
    parser.add_argument(
        "--emit-session-spec",
        action="store_true",
        help="Emit a harness-ready session spec from a contract payload or local skill selection.",
    )
    parser.add_argument(
        "--session-spec-from",
        default=None,
        help="Optional source payload (run.json or harness contract JSON) for --emit-session-spec.",
    )
    parser.add_argument(
        "--session-spec-output",
        default=None,
        help="Optional output path for --emit-session-spec. Defaults to stdout.",
    )
    parser.add_argument(
        "--emit-dispatch-template",
        action="store_true",
        help="Emit a harness-fillable dispatch payload template with scaffolded turns and synthesis slots.",
    )
    parser.add_argument(
        "--dispatch-template-from",
        default=None,
        help="Optional source payload (session spec, run.json, or harness contract JSON) for --emit-dispatch-template.",
    )
    parser.add_argument(
        "--dispatch-template-output",
        default=None,
        help="Optional output path for --emit-dispatch-template. Defaults to stdout.",
    )
    parser.add_argument(
        "--ingest-session-run",
        default=None,
        help="Ingest external harness dispatch JSON and write run artifacts.",
    )
    parser.add_argument(
        "--validate-dispatch-payload",
        default=None,
        help="Validate an external harness dispatch payload without writing run artifacts.",
    )
    parser.add_argument(
        "--ingest-directory-name",
        default=None,
        help="Optional directory name override for --ingest-session-run output.",
    )
    parser.add_argument(
        "--summarize-failures",
        action="store_true",
        help="Summarize recent failure events from traces/raw.",
    )
    parser.add_argument(
        "--propose-redistill",
        action="store_true",
        help="Propose redistill tickets from recent failure events.",
    )
    parser.add_argument(
        "--emit-redistill-worklist",
        action="store_true",
        help="Emit executable redistill work items from ticket files.",
    )
    parser.add_argument(
        "--execute-redistill-worklist",
        action="store_true",
        help="Execute redistill work items into prepared execution requests with idempotent status records.",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="Window in days for --summarize-failures/--propose-redistill (default: 7).",
    )
    parser.add_argument(
        "--failure-root",
        default=None,
        help="Optional root path for failure event scan. Defaults to traces/raw.",
    )
    parser.add_argument(
        "--daily-cap",
        type=int,
        default=3,
        help="Daily cap for --propose-redistill (default: 3).",
    )
    parser.add_argument(
        "--ticket-root",
        default=None,
        help="Optional root path for redistill tickets. Defaults to traces/derived/redistill-tickets.",
    )
    parser.add_argument(
        "--ticket-day",
        default=None,
        help="Optional UTC day (YYYY-MM-DD) for --emit-redistill-worklist. Defaults to today.",
    )
    parser.add_argument(
        "--worklist-root",
        default=None,
        help="Optional output root for redistill worklists. Defaults to traces/derived/redistill-worklists.",
    )
    parser.add_argument(
        "--worklist-day",
        default=None,
        help="Optional UTC day (YYYY-MM-DD) for worklist read/execute. Defaults to today.",
    )
    parser.add_argument(
        "--execution-root",
        default=None,
        help="Optional output root for redistill execution records. Defaults to traces/derived/redistill-executions.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry previously failed work items in --execute-redistill-worklist mode.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write tickets in --propose-redistill mode; print only.",
    )
    args = parser.parse_args()

    output_root = None
    if args.output_root:
        candidate = Path(args.output_root)
        output_root = candidate if candidate.is_absolute() else repo_root / candidate

    if (args.session_spec_from or args.session_spec_output) and not args.emit_session_spec:
        parser.error("--session-spec-from/--session-spec-output require --emit-session-spec")
    if (args.dispatch_template_from or args.dispatch_template_output) and not args.emit_dispatch_template:
        parser.error("--dispatch-template-from/--dispatch-template-output require --emit-dispatch-template")
    if args.ingest_directory_name and not args.ingest_session_run:
        parser.error("--ingest-directory-name requires --ingest-session-run")
    if args.dry_run and not args.propose_redistill:
        if not args.execute_redistill_worklist:
            parser.error("--dry-run requires --propose-redistill or --execute-redistill-worklist")
    if args.retry_failed and not args.execute_redistill_worklist:
        parser.error("--retry-failed requires --execute-redistill-worklist")
    if args.daily_cap < 1:
        parser.error("--daily-cap must be >= 1")
    if args.window_days < 1:
        parser.error("--window-days must be >= 1")

    mode_count = sum(
        bool(flag)
        for flag in (
            args.emit_harness_contract,
            args.verify_harness_contract,
            args.emit_session_spec,
            args.emit_dispatch_template,
            args.validate_dispatch_payload,
            args.ingest_session_run,
            args.summarize_failures,
            args.propose_redistill,
            args.emit_redistill_worklist,
            args.execute_redistill_worklist,
            args.distill_from or args.distill_all,
        )
    )
    if mode_count > 1:
        parser.error(
            "--emit-harness-contract, --verify-harness-contract, --emit-session-spec, --emit-dispatch-template, --validate-dispatch-payload, --ingest-session-run, --summarize-failures, --propose-redistill, --emit-redistill-worklist, --execute-redistill-worklist, and distill modes are mutually exclusive"
        )

    if args.distill_from or args.distill_all:
        trace_output_root = output_root or (repo_root / DISTILLED_TRACE_ROOT)
        if args.distill_all:
            raw_root = repo_root / RAW_TRACE_ROOT
            trace_refs = sorted(path for path in raw_root.iterdir() if path.is_dir())
        else:
            trace_ref = Path(args.distill_from)
            if not trace_ref.is_absolute():
                trace_ref = repo_root / trace_ref
            trace_refs = [trace_ref]

        for trace_ref in trace_refs:
            print(distill_trace_artifacts(trace_ref, output_root=trace_output_root))
        return 0

    if args.verify_harness_contract:
        contract_ref = Path(args.verify_harness_contract)
        if not contract_ref.is_absolute():
            contract_ref = repo_root / contract_ref
        harness, _ = load_harness_payload(contract_ref)
        report = validate_harness_contract(
            harness,
            strict_hash=not args.ignore_hash_mismatch,
            repo_root=repo_root,
            contract_ref=contract_ref,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.status != "fail" else 2

    if args.ingest_session_run:
        ingest_ref = Path(args.ingest_session_run)
        if not ingest_ref.is_absolute():
            ingest_ref = repo_root / ingest_ref
        run_dir = ingest_session_run(
            payload_ref=ingest_ref,
            repo_root=repo_root,
            output_root=output_root or (repo_root / RAW_TRACE_ROOT),
            directory_name=str(args.ingest_directory_name).strip() or None,
            strict_hash=not args.ignore_hash_mismatch,
        )
        print(run_dir)
        return 0

    if args.validate_dispatch_payload:
        payload_ref = Path(args.validate_dispatch_payload)
        if not payload_ref.is_absolute():
            payload_ref = repo_root / payload_ref
        report = validate_session_run_payload(
            payload_ref=payload_ref,
            repo_root=repo_root,
            strict_hash=not args.ignore_hash_mismatch,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.status != "fail" else 2

    if args.summarize_failures or args.propose_redistill:
        failure_root = Path(args.failure_root) if args.failure_root else (repo_root / RAW_TRACE_ROOT)
        if not failure_root.is_absolute():
            failure_root = repo_root / failure_root
        events = read_failure_events(failure_root, window_days=args.window_days)
        summary = summarize_failure_events(events)
        if args.summarize_failures:
            payload = {
                "window_days": args.window_days,
                "failure_root": str(failure_root),
                "summary": summary,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        policy = FailurePolicy(window_days=args.window_days, daily_cap=args.daily_cap)
        ticket_root = Path(args.ticket_root) if args.ticket_root else (repo_root / REDISTILL_TICKET_ROOT)
        if not ticket_root.is_absolute():
            ticket_root = repo_root / ticket_root
        existing_tickets = read_redistill_tickets(ticket_root)
        tickets = propose_redistill_tickets(
            events,
            policy=policy,
            existing_tickets=existing_tickets,
        )
        ticket_path = None
        if not args.dry_run:
            ticket_path = write_redistill_tickets(ticket_root, tickets)
        payload = {
            "window_days": args.window_days,
            "daily_cap": args.daily_cap,
            "existing_ticket_count": len(existing_tickets),
            "remaining_cap": max(args.daily_cap - len(existing_tickets), 0),
            "event_count": len(events),
            "ticket_count": len(tickets),
            "ticket_path": str(ticket_path) if ticket_path is not None else None,
            "tickets": tickets,
            "summary": summary,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.emit_redistill_worklist:
        ticket_root = Path(args.ticket_root) if args.ticket_root else (repo_root / REDISTILL_TICKET_ROOT)
        if not ticket_root.is_absolute():
            ticket_root = repo_root / ticket_root
        ticket_day = str(args.ticket_day).strip() if args.ticket_day else None
        tickets = read_redistill_tickets(ticket_root, day=ticket_day)

        worklist_root = Path(args.worklist_root) if args.worklist_root else (repo_root / REDISTILL_WORKLIST_ROOT)
        if not worklist_root.is_absolute():
            worklist_root = repo_root / worklist_root

        authoring_skill_file = repo_root / "authoring" / "project-incarnation" / "SKILL.md"
        work_items = build_redistill_work_items(
            tickets,
            repo_root=repo_root,
            authoring_skill_file=authoring_skill_file,
        )
        worklist_path = write_redistill_work_items(worklist_root, work_items)
        payload = {
            "ticket_root": str(ticket_root),
            "ticket_day": ticket_day or "today",
            "ticket_count": len(tickets),
            "worklist_root": str(worklist_root),
            "work_item_count": len(work_items),
            "worklist_path": str(worklist_path) if worklist_path is not None else None,
            "work_items": work_items,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.execute_redistill_worklist:
        worklist_root = Path(args.worklist_root) if args.worklist_root else (repo_root / REDISTILL_WORKLIST_ROOT)
        if not worklist_root.is_absolute():
            worklist_root = repo_root / worklist_root
        worklist_day = str(args.worklist_day).strip() if args.worklist_day else None
        work_items = read_redistill_work_items(worklist_root, day=worklist_day)

        execution_root = Path(args.execution_root) if args.execution_root else (repo_root / REDISTILL_EXECUTION_ROOT)
        if not execution_root.is_absolute():
            execution_root = repo_root / execution_root

        execution = execute_redistill_work_items(
            work_items,
            execution_root=execution_root,
            day=worklist_day,
            retry_failed=args.retry_failed,
            dry_run=args.dry_run,
        )
        payload = {
            "worklist_root": str(worklist_root),
            "worklist_day": worklist_day or "today",
            "execution_root": str(execution_root),
            **execution,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    skill_root = Path(args.skill_root)
    if not skill_root.is_absolute():
        skill_root = repo_root / skill_root

    project_root = Path(args.project_root)
    if not project_root.is_absolute():
        project_root = (Path.cwd() / project_root).resolve()

    selected_skills = None
    if args.skills:
        selected_skills = [item.strip() for item in args.skills.split(",") if item.strip()]

    def _contract_from_selection() -> tuple[object, object]:
        final_prompt = load_prompt(repo_root, args.prompt, args.brief)
        skill_specs = load_skill_specs(repo_root, skill_root, selected_skills)
        admission = prepare_session(
            skill_specs=skill_specs,
            prompt=final_prompt,
            explicit_skill_selection=selected_skills is not None,
        )
        selected_slugs = set(admission.selected_skills)
        selected_specs = [spec for spec in skill_specs if spec.slug in selected_slugs]
        skill_instances = tuple(
            SkillInstance(spec=spec, instance_id=f"{spec.slug}-instance")
            for spec in selected_specs
        )
        contract = build_harness_contract(
            mode=DEFAULT_MODE_SPEC.name,
            mode_spec=DEFAULT_MODE_SPEC,
            skill_instances=skill_instances,
            admission=admission,
        )
        return contract, admission

    def _emit_json(content: str, output_arg: str | None) -> None:
        if output_arg:
            output_path = Path(output_arg)
            if not output_path.is_absolute():
                output_path = repo_root / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
            print(output_path)
        else:
            print(content)

    if args.emit_harness_contract:
        contract, admission = _contract_from_selection()
        payload = {
            "harness": contract.to_dict(),
            "admission": admission.to_dict(),
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        _emit_json(content, args.contract_output)
        return 0

    if args.emit_session_spec:
        if args.session_spec_from:
            contract_ref = Path(args.session_spec_from)
            if not contract_ref.is_absolute():
                contract_ref = repo_root / contract_ref
            contract, admission = load_harness_payload(contract_ref)
        else:
            contract, admission = _contract_from_selection()
        payload = build_session_spec(harness=contract, admission=admission)
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        _emit_json(content, args.session_spec_output)
        return 0

    if args.emit_dispatch_template:
        source_ref = None
        if args.dispatch_template_from:
            source_ref = Path(args.dispatch_template_from)
            if not source_ref.is_absolute():
                source_ref = repo_root / source_ref
        else:
            contract, admission = _contract_from_selection()
        session_spec, prompt, template_project_root, shared_brief = load_dispatch_template_inputs(
            source_ref=source_ref,
            repo_root=repo_root,
            project_root=project_root,
            prompt_arg=args.prompt,
            brief_arg=args.brief,
            contract=contract if not args.dispatch_template_from else None,
            admission=admission if not args.dispatch_template_from else None,
        )
        payload = build_dispatch_template(
            session_spec=session_spec,
            prompt=prompt,
            project_root=template_project_root,
            shared_brief=shared_brief,
        )
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        _emit_json(content, args.dispatch_template_output)
        return 0

    run_dir = run(
        prompt=args.prompt,
        brief=args.brief,
        skill_root=skill_root,
        skills=selected_skills,
        project_root=project_root,
        output_root=output_root or (repo_root / RAW_TRACE_ROOT),
        repo_root=repo_root,
        echo=not args.quiet,
    )
    print(run_dir)
    return 0


__all__ = ["main", "run", "load_skill_specs", "distill_trace_artifacts"]
