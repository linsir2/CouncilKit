from pathlib import Path


DEFAULT_BRIEF_FILE = Path("examples/briefs/ai-support-backend.md")
AUTHORING_ROOT = Path("authoring")
SKILL_ROOT = Path("skills")
TRACE_ROOT = Path("traces")
RAW_TRACE_ROOT = TRACE_ROOT / "raw"
DISTILLED_TRACE_ROOT = TRACE_ROOT / "distilled"
DERIVED_TRACE_ROOT = TRACE_ROOT / "derived"
REDISTILL_TICKET_ROOT = DERIVED_TRACE_ROOT / "redistill-tickets"
REDISTILL_WORKLIST_ROOT = DERIVED_TRACE_ROOT / "redistill-worklists"
REDISTILL_EXECUTION_ROOT = DERIVED_TRACE_ROOT / "redistill-executions"
DEFAULT_MODE = "review"
