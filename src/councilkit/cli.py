from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app.distill import distill_traces
from .app.failures import propose_redistill_payload, summarize_failures_payload
from .app.harness_contracts import (
    emit_dispatch_template_payload,
    emit_harness_contract_payload,
    emit_session_spec_payload,
    verify_harness_contract_payload,
)
from .app.ingest import ingest_dispatch_run, validate_dispatch_run
from .app.redistill import emit_redistill_worklist_payload, execute_redistill_worklist_payload
from .constants import (
    DISTILLED_TRACE_ROOT,
    RAW_TRACE_ROOT,
    REDISTILL_EXECUTION_ROOT,
    REDISTILL_TICKET_ROOT,
    REDISTILL_WORKLIST_ROOT,
    SKILL_ROOT,
)
from .runtime import run
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

    def _resolve_repo_path(path_arg: str) -> Path:
        candidate = Path(path_arg)
        return candidate if candidate.is_absolute() else repo_root / candidate

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

    if args.distill_from or args.distill_all:
        trace_output_root = output_root or (repo_root / DISTILLED_TRACE_ROOT)
        trace_ref = _resolve_repo_path(args.distill_from) if args.distill_from else None
        for result in distill_traces(
            repo_root=repo_root,
            output_root=trace_output_root,
            distill_from=trace_ref,
            distill_all=args.distill_all,
        ):
            print(result)
        return 0

    if args.verify_harness_contract:
        report = verify_harness_contract_payload(
            repo_root=repo_root,
            contract_ref=_resolve_repo_path(args.verify_harness_contract),
            strict_hash=not args.ignore_hash_mismatch,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.status != "fail" else 2

    if args.ingest_session_run:
        run_dir = ingest_dispatch_run(
            repo_root=repo_root,
            payload_ref=_resolve_repo_path(args.ingest_session_run),
            output_root=output_root or (repo_root / RAW_TRACE_ROOT),
            directory_name=str(args.ingest_directory_name).strip() or None,
            strict_hash=not args.ignore_hash_mismatch,
        )
        print(run_dir)
        return 0

    if args.validate_dispatch_payload:
        report = validate_dispatch_run(
            repo_root=repo_root,
            payload_ref=_resolve_repo_path(args.validate_dispatch_payload),
            strict_hash=not args.ignore_hash_mismatch,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.status != "fail" else 2

    if args.summarize_failures or args.propose_redistill:
        failure_root = Path(args.failure_root) if args.failure_root else (repo_root / RAW_TRACE_ROOT)
        if not failure_root.is_absolute():
            failure_root = repo_root / failure_root
        if args.summarize_failures:
            payload = summarize_failures_payload(failure_root=failure_root, window_days=args.window_days)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        ticket_root = Path(args.ticket_root) if args.ticket_root else (repo_root / REDISTILL_TICKET_ROOT)
        if not ticket_root.is_absolute():
            ticket_root = repo_root / ticket_root
        payload = propose_redistill_payload(
            failure_root=failure_root,
            window_days=args.window_days,
            daily_cap=args.daily_cap,
            ticket_root=ticket_root,
            dry_run=args.dry_run,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.emit_redistill_worklist:
        ticket_root = Path(args.ticket_root) if args.ticket_root else (repo_root / REDISTILL_TICKET_ROOT)
        if not ticket_root.is_absolute():
            ticket_root = repo_root / ticket_root
        worklist_root = Path(args.worklist_root) if args.worklist_root else (repo_root / REDISTILL_WORKLIST_ROOT)
        if not worklist_root.is_absolute():
            worklist_root = repo_root / worklist_root
        payload = emit_redistill_worklist_payload(
            repo_root=repo_root,
            ticket_root=ticket_root,
            ticket_day=str(args.ticket_day).strip() if args.ticket_day else None,
            worklist_root=worklist_root,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.execute_redistill_worklist:
        worklist_root = Path(args.worklist_root) if args.worklist_root else (repo_root / REDISTILL_WORKLIST_ROOT)
        if not worklist_root.is_absolute():
            worklist_root = repo_root / worklist_root
        execution_root = Path(args.execution_root) if args.execution_root else (repo_root / REDISTILL_EXECUTION_ROOT)
        if not execution_root.is_absolute():
            execution_root = repo_root / execution_root
        payload = execute_redistill_worklist_payload(
            worklist_root=worklist_root,
            worklist_day=str(args.worklist_day).strip() if args.worklist_day else None,
            execution_root=execution_root,
            retry_failed=args.retry_failed,
            dry_run=args.dry_run,
        )
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

    if args.emit_harness_contract:
        payload = emit_harness_contract_payload(
            repo_root=repo_root,
            prompt_arg=args.prompt,
            brief_arg=args.brief,
            skill_root=skill_root,
            selected_skills=selected_skills,
        )
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        _emit_json(content, args.contract_output)
        return 0

    if args.emit_session_spec:
        payload = emit_session_spec_payload(
            repo_root=repo_root,
            source_ref=_resolve_repo_path(args.session_spec_from) if args.session_spec_from else None,
            prompt_arg=args.prompt,
            brief_arg=args.brief,
            skill_root=skill_root,
            selected_skills=selected_skills,
        )
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        _emit_json(content, args.session_spec_output)
        return 0

    if args.emit_dispatch_template:
        payload = emit_dispatch_template_payload(
            repo_root=repo_root,
            source_ref=_resolve_repo_path(args.dispatch_template_from) if args.dispatch_template_from else None,
            project_root=project_root,
            prompt_arg=args.prompt,
            brief_arg=args.brief,
            skill_root=skill_root,
            selected_skills=selected_skills,
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
