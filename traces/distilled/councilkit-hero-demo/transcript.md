# Skill Runtime Transcript

Brief: # CouncilKit Hero Demo Brief

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

## survey

### round 1

### FastAPI
CouncilKit’s first version should expose a minimal, type-driven FastAPI interface that accepts only a project brief and a list of local skill paths, returns replayable session artifacts (traces + synthesis memo) as structured JSON, and enforces strict input/output contracts via Pydantic models—no dynamic routing, no plugin registry, no async I/O beyond what Uvicorn provides out of the box.

- judgment: The runtime must treat its HTTP boundary as the *only* externally observable contract: every request body, response shape, and error code must be declared in types—not inferred, not duck-typed, not deferred to runtime logic. This satisfies ‘replayable and useful’ by making the API self-documenting, verifiable, and stable across minor FastAPI upgrades, while resisting multi-agent drift by refusing to model agents, states, or messages as first-class domain objects.
- evidence: main.py contains a single FastAPI app with no APIRouter decomposition yet; src/councilkit/runtime.py shows synchronous session execution without async I/O dependencies
- tradeoff: Enforcing full Pydantic modeling for all inputs (e.g., arbitrary SKILL.md structure, nested briefs, dynamic harness specs) sacrifices rapid iteration on ad-hoc authoring flows—teams must stabilize their skill schema before the API will accept it, trading early flexibility for long-term replay fidelity.
- objection: The current `main.py` exposes no typed request/response models—just raw `dict`-based endpoints—so the API contract is currently *de facto* undocumented, unvalidated, and unversioned; this violates FastAPI’s core principle that ‘type declaration *is* the contract’, and makes replay impossible if payloads evolve silently.
- needs_verification: Whether main.py uses Pydantic models for request/response
- confidence: high

### Do Things That Don't Scale
CouncilKit’s first version should ship as a manually coordinated, founder-run bounded judgment session: the team personally selects 3–5 local skills (e.g., `fastapi`, `do-things-that-dont-scale`, `admission`), loads them into a single-process runtime, and runs *one* real project brief end-to-end—with full manual trace annotation, human-led synthesis, and no automation of dispatch, disagreement resolution, or memo generation.

- judgment: This approach satisfies ‘replayable and useful’ by forcing the team to manually enact every step—loading, routing, turning, synthesizing—thereby exposing exactly which parts of the skill contract are ambiguous, incomplete, or unimplementable; it avoids multi-agent drift by refusing to model coordination as anything more than sequential function calls over typed inputs/outputs.
- evidence: The README explicitly states runtime is 'intentionally single-process, single-coordinator, and append-only' — this matches the manual-first constraint; SKILL.md files are declared the 'only semantic source', so manual execution surfaces gaps before automation hides them
- tradeoff: By requiring founders to manually run, annotate, and synthesize each session, CouncilKit sacrifices velocity for fidelity: teams cannot batch-run briefs or scale to >10 skills until the manual loop proves robust—but that slowness is the point, because it prevents premature platformization.
- objection: The sharpest technical objection is that `runtime.py` currently lacks explicit, enforced turn boundaries: there’s no mechanism to pause, inspect, or replay individual participant outputs mid-session — meaning even manual runs produce opaque, non-reproducible traces unless instrumentation is added *before* any demo shipment.
- needs_verification: Whether `harness_runtime.py` actually enforces strict input/output typing per participant turn
- confidence: high

## review

### round 1

### FastAPI
CouncilKit’s first version must expose a strictly typed FastAPI HTTP boundary—where every brief, skill set, and synthesis output is modeled via Pydantic—while simultaneously enforcing manual, stepwise execution in `runtime.py` to surface ambiguity before automation; this dual constraint ensures replayability (via declarative contracts) and usefulness (via observable, inspectable turns), without drifting into multi-agent abstraction.

- judgment: The sharpest technical objection remains: the current API surface in `main.py` uses untyped `dict` payloads and lacks declared request/response models, making replay impossible by FastAPI’s own standards—and `runtime.py` has no turn-level checkpointing or output capture, so even manual runs yield opaque traces.
- evidence: main.py exposes raw dict-based endpoints with no Pydantic models or response_model declarations; runtime.py contains no explicit turn boundaries, pause points, or structured output serialization
- tradeoff: Enforcing full Pydantic modeling for dynamic authoring artifacts (e.g., arbitrary SKILL.md structure, nested briefs) sacrifices early flexibility—teams must stabilize their skill schema *before* the API accepts it—trading rapid prototyping for guaranteed replay fidelity across upgrades.
- objection: The current `main.py` exposes no typed request/response models—just raw `dict`-based endpoints—so the API contract is currently *de facto* undocumented, unvalidated, and unversioned; this violates FastAPI’s core principle that ‘type declaration *is* the contract’, and makes replay impossible if payloads evolve silently.
- needs_verification: Whether `harness_contract.py` defines stable, versioned Pydantic models for brief ingestion and synthesis output
- confidence: high

### Do Things That Don't Scale
CouncilKit’s first version should ship as a manually orchestrated, single-session CLI tool—not an API—where the founder runs `councilkit review --brief <path> --skills <glob>` and watches each participant execute in sequence with full stdout/stderr capture, explicit turn boundaries, and deterministic filesystem-based trace logging; this forces confrontation with SKILL.md ambiguities before any abstraction is built, preserves replay via shell history + logs, and avoids multi-agent drift by refusing to model coordination beyond sequential function calls.

- judgment: This satisfies ‘replayable and useful’ by making every judgment step observable, annotatable, and re-runnable by hand—turning the CLI into both execution engine and learning instrument—while keeping runtime responsibilities narrow: no HTTP server, no state, no dispatch loop, just skill loading, brief binding, turn iteration, and artifact serialization.
- evidence: CLI entrypoint `src/councilkit/cli.py` already exists and routes to `harness.py`; `runtime.py` contains turn logic but lacks enforced pause/inspect points
- tradeoff: Shipping CLI-first sacrifices immediate integrability (no HTTP API for IDEs or dashboards) and team-wide parallel session execution—but that constraint is intentional: it prevents premature platformization by forcing founders to manually experience every friction point before automating any part of the flow.
- objection: The sharpest technical objection remains in `runtime.py`: absence of explicit, serializable turn boundaries means participant outputs are not captured, timestamped, or diffable per-turn—so even manual runs produce non-reproducible traces unless output interception and structured logging are added *before* shipping.
- needs_verification: Whether `cli.py` currently captures and persists full participant stdout/stderr per-turn
- confidence: high

## synthesis

### Coordinator
Both FastAPI and Do Things That Don't Scale agree CouncilKit’s first version must prioritize replayability and bounded utility by enforcing strict, observable contracts—either via typed HTTP interfaces (FastAPI) or manual-first execution with full trace observability (DTTDS). They converge on the runtime’s current failure to satisfy either: `main.py` lacks Pydantic models for request/response, and `runtime.py` lacks enforced, serializable turn boundaries—making traces opaque and replay impossible.

- decision: Ship v0.1 as a CLI-only, append-only, single-process runtime that enforces per-turn output capture and structured serialization—*before* exposing any HTTP surface—while simultaneously adding minimal Pydantic models to `harness_contract.py` and `main.py` to declare the brief ingestion and synthesis output schemas, even if the API remains unexposed in v0.1.
