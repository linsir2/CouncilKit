# CouncilKit

CouncilKit is a bounded judgment session runtime for a managed local skill universe.

It does one thing:

Take a set of distilled local `SKILL.md` files, load them as runtime participants, let them review a project brief, and produce replayable run artifacts plus a synthesis memo.

## Core principles

- `SKILL.md` is the only semantic source.
- Runtime artifacts are projections, not second truth sources.
- Modes are layered on top of a generic turn runtime.
- The current baseline mode is `review`.
- The current runtime is intentionally single-process, single-coordinator, and append-only.

## Product definition

CouncilKit is not trying to model the whole world.

It assumes:

- `project-incarnation` or an equivalent authoring flow produces local subskills
- those subskills live under `skills/`
- the runtime operates over that managed local universe

CouncilKit is responsible for:

- deciding whether a bounded judgment session is runnable
- running the session over a selected local skill set
- preserving replayable traces and disagreement

CouncilKit is not responsible for:

- global skill discovery
- world ontology or universal object classification
- a second semantic layer on top of `SKILL.md`
- bundle-era sidecars or registry-heavy runtime metadata

## Repository layout

```text
CouncilKit/
├── authoring/
│   └── project-incarnation/     # canonical authoring compiler skill
├── skills/                      # runtime-loaded single-file skills
├── examples/
│   ├── briefs/                  # checked-in live sample briefs
│   └── ingest/                  # checked-in harness payload fixtures
├── traces/
│   ├── raw/                     # replayable raw traces
│   └── distilled/               # same-shape distilled projections
├── src/councilkit/              # runtime code
│   ├── app/                     # CLI-facing use-case orchestration
│   ├── ingest/                  # external dispatch ingest internals
│   └── validation/              # shared runtime/ingest payload validation
├── .codex/skills/               # optional Codex adapter symlink
└── .claude/skills/              # optional Claude adapter symlink
```

Path roles:

- `authoring/`: canonical source for authoring/compiler skills
- `skills/`: canonical runtime skill root, and the identity truth for the local skill universe
- `traces/`: runtime projections for replay, comparison, provenance, and eval
- `.codex/` / `.claude/`: tool adapters only, not sources of truth

Internal module boundaries:

- `app/`: use-case orchestration for CLI workflows; keeps `cli.py` thin
- `ingest/`: parse / validate / map / write internals for external harness payloads
- `validation/`: shared turn / synthesis / contract / schedule checks reused by runtime and ingest

## What counts as a runtime skill

The canonical runtime unit is a **single-file skill**.

The runtime only requires:

- `SKILL.md`

`SKILL.md` is both the wisdom artifact and the runtime-facing reasoning contract.

If a skill directory happens to contain legacy sidecar files from older systems, CouncilKit ignores them.

Current checked-in runtime skills include:

- `fastapi`
- `do-things-that-dont-scale`
- `langgraph`
- `llama-index`

## Core objects

The baseline runtime is organized around:

- `SkillSpec`
- `SkillInstance`
- `TaskEnvelope`
- `ContextFrame`
- `TurnResult`
- `PatchProposal`
- `RunTrace`

`council`, `debate`, `review`, or `consensus` are not core ontology objects. They are modes layered on top.

## Runtime outputs

Each run writes:

- `run.json`
- `transcript.md`
- `result.md`
- `debate.md`

`debate.md` is a human-facing projection that makes participant provenance, admission rationale,
turn-level conflict, synthesis carry-over, and harness handoff visible without introducing a
second semantic layer.

`run.json` is a replay/comparison artifact, not a semantic charter.

For harness integration, `run.json` also carries a runtime-only `harness` section with:

- contract version and source-of-truth marker (`SKILL.md`)
- six-slot reducibility contract (`judgment`, `evidence`, `tradeoff`, `objection`, `needs_verification`, `confidence`)
- mode/stage metadata
- selected skill slugs and loaded skill prompt provenance (`skill_file`, `skill_mtime`, `prompt_sha256`)

This contract is derived at runtime only. It does not require any extra fields inside child `SKILL.md`.

For the full external harness integration surface, see `docs/harness-contract.md`.
Portable checked-in harness fixtures now live under `examples/ingest/`.

`traces/distilled/` is not a second ontology. A distilled trace must stay schema-isomorphic with the raw trace:

- same top-level shape
- same task / skills / turns / synthesis slots
- only higher-signal selection and compression
- no dependency on the live skill directory still existing

## Quickstart

```bash
pip install -r requirements.txt
cp env.example .env
```

Set:

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=...
OPENAI_BASE_URL=
```

## Run the default example

```bash
python main.py
```

This uses:

- brief: `examples/briefs/ai-support-backend.md`
- skills: every directory under `skills/`
- output root: `traces/raw/`

## Run with an inline brief and selected skills

```bash
python main.py \
  --prompt "Design the first single-file skill runtime." \
  --skills fastapi,do-things-that-dont-scale
```

## Run against a custom project root

```bash
python main.py \
  --brief docs/idea.md \
  --skills my-project-skill,fastapi \
  --skill-root skills \
  --project-root .
```

Resolution order for skill names is:

1. explicit path
2. `--skill-root`
3. `skills/`

## Emit harness contract only (no model call)

When external harness code only needs session routing metadata (without running survey/review turns), emit the contract directly:

```bash
python main.py \
  --emit-harness-contract \
  --brief examples/briefs/councilkit-hero-demo.md \
  --skills fastapi,do-things-that-dont-scale
```

Optional file output:

```bash
python main.py \
  --emit-harness-contract \
  --brief examples/briefs/councilkit-hero-demo.md \
  --skills fastapi,do-things-that-dont-scale \
  --contract-output traces/raw/councilkit-hero-demo/harness-contract.json
```

Validate an existing contract (or a `run.json` that includes `harness`) before wiring it into an external harness:

```bash
python main.py --verify-harness-contract traces/raw/councilkit-hero-demo/run.json
```

If you want hash drift to report as warnings instead of failure:

```bash
python main.py \
  --verify-harness-contract traces/raw/councilkit-hero-demo/run.json \
  --ignore-hash-mismatch
```

Emit a harness-facing session spec (participants + stage contract) from an existing contract payload:

```bash
python main.py \
  --emit-session-spec \
  --session-spec-from traces/raw/councilkit-hero-demo/run.json
```

The emitted session spec now includes an explicit `turn_schedule` array.
That lets external harnesses consume the canonical dispatch order directly
instead of re-implementing CouncilKit's round-rotation logic.

You can also emit it directly from local brief + skills (no model call):

```bash
python main.py \
  --emit-session-spec \
  --brief examples/briefs/councilkit-hero-demo.md \
  --skills fastapi,do-things-that-dont-scale
```

Emit a harness-fillable dispatch payload template:

```bash
python main.py \
  --emit-dispatch-template \
  --brief examples/briefs/councilkit-hero-demo.md \
  --skills fastapi,do-things-that-dont-scale
```

The template includes:

- task context (`prompt`, `project_root`, `shared_brief`)
- embedded `session_spec`
- scaffolded `turns` aligned to the canonical `turn_schedule`
- an empty `synthesis` shell with the required keys

You can also derive the same template from an existing `run.json` or session spec file:

```bash
python main.py \
  --emit-dispatch-template \
  --dispatch-template-from traces/raw/councilkit-hero-demo/run.json
```

Validate a filled dispatch payload before ingest:

```bash
python main.py \
  --validate-dispatch-payload examples/ingest/external-run.json
```

This is a preflight check only:

- no `run.json` / `transcript.md` / `result.md` / `debate.md` is written
- the same schedule, slot, synthesis, and hash checks are reused from ingest
- warnings surface as `pass_with_warning`; hard failures return `fail`
- `expected_contract` exposes the canonical slot/synthesis requirements
- `repair_hints` provides machine-readable fix guidance for harness code
- `issues` can include `turn_index`, `field_path`, `expected`, and `actual` for direct field-level repair
- `issues_by_turn` and `issues_by_section` pre-group failures for orchestration or repair UIs
- grouped views include stable `priority_rank` and `blocking` metadata for repair ordering
- `recommended_repair_order` flattens the groups into a single repair queue for harness scheduling

The validator accepts either a harness-style dispatch payload or an existing CouncilKit `run.json`.

Ingest external harness dispatch output into CouncilKit artifacts (`run.json`, `transcript.md`, `result.md`, `debate.md`):

```bash
python main.py \
  --ingest-session-run examples/ingest/external-run.json \
  --output-root traces/raw \
  --ingest-directory-name imported-harness-run
```

`external-run.json` must contain:

- `prompt`
- `session_spec` (from `--emit-session-spec`)
- `turns` (ordered, one entry per scheduled turn, each entry includes the six-slot fields)
- `synthesis` (same shape as runtime synthesis payload)

If `session_spec.turn_schedule` is present, ingest validates it against the
canonical runtime schedule before accepting the run.

Failure events are written per run to `traces/raw/<run>/failure-events.jsonl`.

Summarize recent failures:

```bash
python main.py \
  --summarize-failures \
  --window-days 7
```

Propose redistill tickets from recent failure events:

```bash
python main.py \
  --propose-redistill \
  --window-days 7 \
  --daily-cap 3
```

`daily-cap` is enforced per UTC day across repeated runs. Re-running the command
on the same day will not exceed the cap or duplicate the same `(skill_slug, failure_code)` ticket.

Dry-run proposal mode (no ticket file written):

```bash
python main.py \
  --propose-redistill \
  --window-days 7 \
  --daily-cap 3 \
  --dry-run
```

Ticket files are written to `traces/derived/redistill-tickets/<YYYY-MM-DD>.jsonl`.

Emit executable redistill work items (ticket -> actionable task list for `authoring/project-incarnation`):

```bash
python main.py \
  --emit-redistill-worklist \
  --ticket-day 2026-04-09
```

Optional roots:

```bash
python main.py \
  --emit-redistill-worklist \
  --ticket-root traces/derived/redistill-tickets \
  --worklist-root traces/derived/redistill-worklists
```

Worklists are written to `traces/derived/redistill-worklists/<YYYY-MM-DD>.jsonl`.

Execute worklists into idempotent execution requests:

```bash
python main.py \
  --execute-redistill-worklist \
  --worklist-day 2026-04-09
```

Optional execution root and dry-run:

```bash
python main.py \
  --execute-redistill-worklist \
  --worklist-root traces/derived/redistill-worklists \
  --execution-root traces/derived/redistill-executions \
  --dry-run
```

Execution records are written to `traces/derived/redistill-executions/<YYYY-MM-DD>.jsonl`, and prepared
execution request markdown files are written to `traces/derived/redistill-executions/requests/`.

## Harness runtime skeleton API

For in-process harness integration, use `src/councilkit/harness_runtime.py`:

- `build_turn_schedule(session_spec)` for round scheduling
- `dispatch_turns(schedule, dispatcher)` for per-turn dispatch
- `to_turn_records(dispatched, skill_instances=...)` for adapting to CouncilKit turn records
- `render_transcript(prompt, dispatched)` for markdown transcript projection

## Canonical hero demo fixture

This repo ships a checked-in hero demo fixture used for structural regression.

- brief: `examples/briefs/councilkit-hero-demo.md`
- raw trace: `traces/raw/councilkit-hero-demo/`
- distilled trace: `traces/distilled/councilkit-hero-demo/`
- fixed skill set: `fastapi`, `do-things-that-dont-scale`

Each trace directory includes `debate.md` as the hero projection artifact.

Run a fresh live session with the same brief and skill set:

```bash
python main.py \
  --brief examples/briefs/councilkit-hero-demo.md \
  --skills fastapi,do-things-that-dont-scale \
  --project-root .
```

Distill the fresh raw trace:

```bash
python main.py --distill-from traces/raw/<timestamp-run-dir>
```

Validate fixture invariants:

```bash
python -m unittest tests.test_main.MainFlowTests.test_repository_hero_demo_assets_exist_and_preserve_contract -v
```

## Runtime triad sample

This repo also ships a live-generated three-skill sample:

- brief: `examples/briefs/councilkit-runtime-triad.md`
- raw trace: `traces/raw/councilkit-runtime-triad/`
- distilled trace: `traces/distilled/councilkit-runtime-triad/`
- fixed skill set: `fastapi`, `langgraph`, `llama-index`

Each trace directory includes `debate.md` beside the replay and synthesis artifacts.

## Distill a raw trace into a benchmark trace

```bash
python main.py --distill-from traces/raw/councilkit-runtime-triad
```

This writes a same-shape artifact under `traces/distilled/councilkit-runtime-triad/`.

The first distillation rule is intentionally conservative:

- preserve the six-slot turn contract
- keep all turns
- deduplicate and trim long lists
- compress wording without inventing new semantic fields

You can also distill every raw trace currently in the repo:

```bash
python main.py --distill-all
```

## Scope of this repo

This repo contains:

- the runtime baseline
- runtime single-file skills
- a canonical authoring compiler under `authoring/project-incarnation/`
- example/legacy materials for migration reference

It is not yet:

- a general-purpose multi-agent chat platform
- a marketplace
- a GUI-first product
- a registry
- a code-executing swarm runtime

That is intentional.

The wedge is simple:

**use distilled single-file skills to produce more inspectable judgments than one-shot prompting.**
