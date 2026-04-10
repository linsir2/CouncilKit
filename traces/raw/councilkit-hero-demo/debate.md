# CouncilKit Debate Projection

## Brief
# CouncilKit Hero Demo Brief

Run a bounded judgment session on the `CouncilKit` repository using the local skills:

- `fastapi`
- `do-things-that-dont-scale`

Focus on one concrete question:

How should CouncilKit ship a first version that is both replayable and useful, without becoming a general multi-agent platform?

Requirements:

- preserve disagreement in synthesis
- keep runtime responsibilities narrow
- identify the sharpest technical objection
- state one tradeoff that remains unresolved

## Trace Context
- source_kind: raw
- mode: review
- created_at: 20260410T025037Z
- project_root: /home/linsir365/projects/CouncilKit

## Participants & Provenance

### FastAPI
- slug: fastapi
- boundary: 先把边界写成类型，再让框架替你推导校验、文档、安全和运行时行为。
- skill_file: /home/linsir365/projects/CouncilKit/skills/fastapi/SKILL.md
- prompt_sha256: f1c8350894aec6a0305cd381e8095b9ffe2470d844753c9956cc42344814af8a
- matched_terms: fastapi

### Do Things That Don't Scale
- slug: do-things-that-dont-scale
- boundary: 在早期，最危险的不是做不规模化的事，而是拿成熟公司的尺度审判一个还没点火的系统。
- skill_file: /home/linsir365/projects/CouncilKit/skills/do-things-that-dont-scale/SKILL.md
- prompt_sha256: 4dc479aa2d4a38bf2d88c99b085d9ae45742cd4559122bed15323d6c28c7dbcd
- matched_terms: none

## Admission Rationale

- status: accept
- reason: Session is runnable with 2 selected skill(s).
- selected_skills: fastapi, do-things-that-dont-scale
- warnings: none
- rejected_skills: none

## Debate Map

### survey

#### round 1

##### FastAPI
- position: CouncilKit’s first version should expose a minimal, type-driven FastAPI interface that accepts only a project brief and a list of local skill paths, returns replayable session artifacts (traces + synthesis memo) as structured JSON, and enforces strict input/output contracts via Pydantic models—no dynamic routing, no plugin registry, no async I/O beyond what Uvicorn provides out of the box.
- judgment: The runtime must treat its HTTP boundary as the *only* externally observable contract: every request body, response shape, and error code must be declared in types—not inferred, not duck-typed, not deferred to runtime logic. This satisfies ‘replayable and useful’ by making the API self-documenting, verifiable, and stable across minor FastAPI upgrades, while resisting multi-agent drift by refusing to model agents, states, or messages as first-class domain objects.
- objection: The current `main.py` exposes no typed request/response models—just raw `dict`-based endpoints—so the API contract is currently *de facto* undocumented, unvalidated, and unversioned; this violates FastAPI’s core principle that ‘type declaration *is* the contract’, and makes replay impossible if payloads evolve silently.
- tradeoff: Enforcing full Pydantic modeling for all inputs (e.g., arbitrary SKILL.md structure, nested briefs, dynamic harness specs) sacrifices rapid iteration on ad-hoc authoring flows—teams must stabilize their skill schema before the API will accept it, trading early flexibility for long-term replay fidelity.
- confidence: high
- evidence_path: main.py contains a single FastAPI app with no APIRouter decomposition yet, src/councilkit/runtime.py shows synchronous session execution without async I/O dependencies, README explicitly forbids world ontology or universal object classification
- needs_verification: Whether main.py uses Pydantic models for request/response, Whether harness_contract.py defines serializable output schemas, Whether any endpoint declares response_model or return type

##### Do Things That Don't Scale
- position: CouncilKit’s first version should ship as a manually coordinated, founder-run bounded judgment session: the team personally selects 3–5 local skills (e.g., `fastapi`, `do-things-that-dont-scale`, `admission`), loads them into a single-process runtime, and runs *one* real project brief end-to-end—with full manual trace annotation, human-led synthesis, and no automation of dispatch, disagreement resolution, or memo generation.
- judgment: This approach satisfies ‘replayable and useful’ by forcing the team to manually enact every step—loading, routing, turning, synthesizing—thereby exposing exactly which parts of the skill contract are ambiguous, incomplete, or unimplementable; it avoids multi-agent drift by refusing to model coordination as anything more than sequential function calls over typed inputs/outputs.
- objection: The sharpest technical objection is that `runtime.py` currently lacks explicit, enforced turn boundaries: there’s no mechanism to pause, inspect, or replay individual participant outputs mid-session — meaning even manual runs produce opaque, non-reproducible traces unless instrumentation is added *before* any demo shipment.
- tradeoff: By requiring founders to manually run, annotate, and synthesize each session, CouncilKit sacrifices velocity for fidelity: teams cannot batch-run briefs or scale to >10 skills until the manual loop proves robust—but that slowness is the point, because it prevents premature platformization.
- confidence: high
- evidence_path: The README explicitly states runtime is 'intentionally single-process, single-coordinator, and append-only' — this matches the manual-first constraint, SKILL.md files are declared the 'only semantic source', so manual execution surfaces gaps before automation hides them, The harness_contract.py and session_spec.py already define narrow, declarative interfaces — manual use tests their sufficiency
- needs_verification: Whether `harness_runtime.py` actually enforces strict input/output typing per participant turn, Whether `session_spec.py` captures enough metadata to reconstruct disagreement provenance (e.g., which skill rejected which claim), Whether `dispatch_template.py` is truly deterministic or relies on implicit order/state

### review

#### round 1

##### FastAPI
- position: CouncilKit’s first version must expose a strictly typed FastAPI HTTP boundary—where every brief, skill set, and synthesis output is modeled via Pydantic—while simultaneously enforcing manual, stepwise execution in `runtime.py` to surface ambiguity before automation; this dual constraint ensures replayability (via declarative contracts) and usefulness (via observable, inspectable turns), without drifting into multi-agent abstraction.
- judgment: The sharpest technical objection remains: the current API surface in `main.py` uses untyped `dict` payloads and lacks declared request/response models, making replay impossible by FastAPI’s own standards—and `runtime.py` has no turn-level checkpointing or output capture, so even manual runs yield opaque traces.
- objection: The current `main.py` exposes no typed request/response models—just raw `dict`-based endpoints—so the API contract is currently *de facto* undocumented, unvalidated, and unversioned; this violates FastAPI’s core principle that ‘type declaration *is* the contract’, and makes replay impossible if payloads evolve silently.
- tradeoff: Enforcing full Pydantic modeling for dynamic authoring artifacts (e.g., arbitrary SKILL.md structure, nested briefs) sacrifices early flexibility—teams must stabilize their skill schema *before* the API accepts it—trading rapid prototyping for guaranteed replay fidelity across upgrades.
- confidence: high
- evidence_path: main.py exposes raw dict-based endpoints with no Pydantic models or response_model declarations, runtime.py contains no explicit turn boundaries, pause points, or structured output serialization
- needs_verification: Whether `harness_contract.py` defines stable, versioned Pydantic models for brief ingestion and synthesis output, Whether `runtime.py`’s `turn()` loop emits serializable, timestamped, per-participant output artifacts

##### Do Things That Don't Scale
- position: CouncilKit’s first version should ship as a manually orchestrated, single-session CLI tool—not an API—where the founder runs `councilkit review --brief <path> --skills <glob>` and watches each participant execute in sequence with full stdout/stderr capture, explicit turn boundaries, and deterministic filesystem-based trace logging; this forces confrontation with SKILL.md ambiguities before any abstraction is built, preserves replay via shell history + logs, and avoids multi-agent drift by refusing to model coordination beyond sequential function calls.
- judgment: This satisfies ‘replayable and useful’ by making every judgment step observable, annotatable, and re-runnable by hand—turning the CLI into both execution engine and learning instrument—while keeping runtime responsibilities narrow: no HTTP server, no state, no dispatch loop, just skill loading, brief binding, turn iteration, and artifact serialization.
- objection: The sharpest technical objection remains in `runtime.py`: absence of explicit, serializable turn boundaries means participant outputs are not captured, timestamped, or diffable per-turn—so even manual runs produce non-reproducible traces unless output interception and structured logging are added *before* shipping.
- tradeoff: Shipping CLI-first sacrifices immediate integrability (no HTTP API for IDEs or dashboards) and team-wide parallel session execution—but that constraint is intentional: it prevents premature platformization by forcing founders to manually experience every friction point before automating any part of the flow.
- confidence: high
- evidence_path: CLI entrypoint `src/councilkit/cli.py` already exists and routes to `harness.py`, `runtime.py` contains turn logic but lacks enforced pause/inspect points, README explicitly states runtime is 'single-process, single-coordinator, append-only'
- needs_verification: Whether `cli.py` currently captures and persists full participant stdout/stderr per-turn, Whether `harness.py` guarantees deterministic ordering when loading skills from glob

## Synthesis Delta

### Coordinator Summary
Both FastAPI and Do Things That Don't Scale agree CouncilKit’s first version must prioritize replayability and bounded utility by enforcing strict, observable contracts—either via typed HTTP interfaces (FastAPI) or manual-first execution with full trace observability (DTTDS). They converge on the runtime’s current failure to satisfy either: `main.py` lacks Pydantic models for request/response, and `runtime.py` lacks enforced, serializable turn boundaries—making traces opaque and replay impossible. Disagreement persists on *where* the contract lives: FastAPI insists it must be externalized via HTTP, while DTTDS insists it must be internalized via CLI-driven manual enactment.

### Final Decision
Ship v0.1 as a CLI-only, append-only, single-process runtime that enforces per-turn output capture and structured serialization—*before* exposing any HTTP surface—while simultaneously adding minimal Pydantic models to `harness_contract.py` and `main.py` to declare the brief ingestion and synthesis output schemas, even if the API remains unexposed in v0.1.

### Kept In Synthesis
- Require explicit, timestamped, per-participant output serialization in `runtime.py`'s `turn()` loop before shipping v0.1.
- Add versioned Pydantic models to `harness_contract.py` for brief ingestion and synthesis memo, regardless of whether `main.py` exposes them publicly yet.
- Defer HTTP API exposure until both turn-level replay and contract typing are verified—not as a feature, but as a hard gate.

### Strongest Objections Preserved
- FastAPI (high): The current `main.py` exposes raw dict-based endpoints with no Pydantic models or response_model declarations, violating FastAPI’s core principle that 'type declaration is the contract' and making replay impossible if payloads evolve silently.
- Do Things That Don't Scale (high): The absence of explicit, serializable turn boundaries in `runtime.py` means participant outputs are not captured, timestamped, or diffable per-turn—so even manual runs produce non-reproducible traces unless output interception and structured logging are added before shipping.

### Next Steps
- Instrument `runtime.py` to emit deterministic, JSON-serializable turn artifacts (input, skill ID, output, timestamp, error if any) to disk per turn.
- Define and implement `BriefIngestionRequest` and `SynthesisMemoResponse` Pydantic models in `harness_contract.py`, then verify they cover all fields used in `harness_ingest.py` and `harness.py`.
- Update `cli.py` to accept `--replay <session-id>` flag that reloads and re-executes from persisted turn artifacts.

### Still Unresolved
- Does `dispatch_template.py` rely on implicit filesystem ordering or mutable global state that breaks deterministic replay across environments?

### Skill Notes
- FastAPI: Type enforcement must begin at the contract boundary—even if the API isn’t public yet, the models must exist and be used internally to prevent silent drift in payload structure.
- Do Things That Don't Scale: Manual execution only delivers learning value if every step—including output capture, annotation, and provenance tracking—is explicit, inspectable, and repeatable by hand; automation before that is premature scaling.

## Harness Handoff

- mode: review
- stage_order: survey, review, synthesis
- reduction_slots: judgment, evidence, tradeoff, objection, needs_verification, confidence
- selected_skill_slugs: fastapi, do-things-that-dont-scale
- handoff_path: --emit-harness-contract -> --emit-session-spec -> --emit-dispatch-template -> --validate-dispatch-payload -> --ingest-session-run
