# CouncilKit Debate Projection

## Brief
# CouncilKit Runtime Triad Brief

Run a bounded judgment session on the `CouncilKit` repository using the local skills:

- `fastapi`
- `langgraph`
- `llama-index`

Focus on one concrete question:

If CouncilKit evolves beyond a minimal review runtime, how should it add stateful execution and data-aware retrieval boundaries without collapsing into a general-purpose agent platform?

Requirements:

- preserve replayability and explicit turn contracts
- distinguish runtime state from retrieval/data state
- identify one boundary that must remain separate
- surface one migration risk if workflows or durable execution are added

## Trace Context
- source_kind: distilled
- mode: review
- created_at: 20260410T025234Z
- project_root: /home/linsir365/projects/CouncilKit

## Participants & Provenance

### FastAPI
- slug: fastapi
- boundary: 先把边界写成类型，再让框架替你推导校验、文档、安全和运行时行为。
- skill_file: /home/linsir365/projects/CouncilKit/skills/fastapi/SKILL.md
- prompt_sha256: f1c8350894aec6a0305cd381e8095b9ffe2470d844753c9956cc42344814af8a
- matched_terms: fastapi

### LangGraph
- slug: langgraph
- boundary: 先把状态如何演进、如何暂停、如何恢复、如何重放讲清楚，再谈 agent 看起来像不像在思考。
- skill_file: /home/linsir365/projects/CouncilKit/skills/langgraph/SKILL.md
- prompt_sha256: cddab42308e1291a462179bfe05b0850accbc2ce10ab0490bf695cd266c2cd49
- matched_terms: agent, durable, execution, langgraph, migration, state, surface

### LlamaIndex
- slug: llama-index
- boundary: 先把数据怎么进、怎么存、怎么找、怎么答拆清楚，再谈 agent 会不会显得聪明。
- skill_file: /home/linsir365/projects/CouncilKit/skills/llama-index/SKILL.md
- prompt_sha256: 571d226fbb8a8998f065c3d00757fc0addf6561a07661704b08ada3593eb043d
- matched_terms: agent, data, durable, execution, langgraph, state, workflows

## Admission Rationale

- status: accept
- reason: Session is runnable with 3 selected skill(s).
- selected_skills: fastapi, langgraph, llama-index
- warnings: none
- rejected_skills: none

## Debate Map

### survey

#### round 1

##### FastAPI
- position: CouncilKit’s evolution must treat FastAPI not as an execution engine but as a strict, typed boundary layer for exposing stateful runtime capabilities—where every new endpoint (e.g., for workflow control or session resumption) is modeled with explicit Pydantic request/response contracts, `response_model`-enforced output filtering, and dependency-injected state accessors that *never* conflate runtime state (ephemeral turn coordination) with retrieval/data state (persistent, queryable artifacts).
- judgment: The one boundary that must remain separate is the HTTP API contract layer itself: it must *only* project runtime state (e.g., session trace IDs, turn indices, replayable logs) and never expose raw data store handles, LLM call stacks, or mutable skill state—because collapsing that boundary turns FastAPI into a generic agent RPC surface, violating CouncilKit’s principle that 'runtime artifacts are projections, not second truth sources.'
- objection: FastAPI alone cannot enforce separation of runtime vs.
- tradeoff: Enforcing this boundary sacrifices convenience: adding durable workflows will require explicit, versioned projection models (e.g., `WorkflowResumeRequest`, `SessionTraceResponse`) and careful dependency scoping—no direct `Depends[VectorStore]` in route handlers—slowing initial iteration but preserving replay fidelity and auditability.
- confidence: high
- evidence_path: FastAPI’s `response_model` is a hard security and schema boundary—not decoration—but only works if response types are strictly projection models, not domain objects, CouncilKit’s README explicitly forbids 'a second semantic' and treats artifacts as 'projections', which aligns precisely with FastAPI’s output filtering discipline
- needs_verification: Whether `src/councilkit/harness_runtime.py` currently exposes any data-store references to HTTP handlers

##### LangGraph
- position: CouncilKit must treat LangGraph’s state graph as the sole source of truth for *execution state*—not data, not memory, not skill outputs—but the explicit, versioned, replayable contract governing how turns evolve, pause, resume, and recover.
- judgment: The boundary that must remain separate is *execution state* (governed by LangGraph’s checkpointed, reducer-enforced graph) from *retrieval/data state* (managed by LlamaIndex or external stores). Collapsing them—e.g., letting retrieval logic mutate graph state directly or embedding vector store handles in `State`—violates LangGraph’s core discipline and erodes replay fidelity.
- objection: CouncilKit’s current `harness_runtime.py` shows no evidence of StateGraph usage or checkpointing; adding LangGraph without refactoring the existing turn loop risks layering incompatible state models—e.g., mixing append-only session logs with mutable graph state—creating unresolvable replay conflicts.
- tradeoff: Enforcing this boundary demands upfront rigor: defining immutable state schemas, wiring a production-grade checkpointer (e.g., Postgres), and routing all data access through controlled tasks—not convenience wrappers. This slows prototyping but prevents silent corruption of replay traces when workflows scale.
- confidence: high
- evidence_path: LangGraph’s state is a strict contract: keys default to overwrite unless explicitly reduced ([E3]); conflating retrieval results with execution state breaks merge semantics and replay safety., Checkpointing is not optional—it’s the foundation of recovery, thread continuity, and interrupt semantics ([E5]); without it, durable workflows are illusory.
- needs_verification: Whether `harness_runtime.py` currently uses any LangGraph primitives (e.g., `StateGraph`, `checkpointer`)

##### LlamaIndex
- position: CouncilKit must preserve the boundary between *retrieval/data state* (managed by LlamaIndex’s ingestion→index→retriever→synthesizer pipeline) and *runtime state* (e.g., turn sequence, participant roles, session trace IDs), because collapsing them—like embedding vector store handles in graph state or letting retrieval logic mutate execution context—turns LlamaIndex into an agent runtime proxy rather than a data-aware boundary layer.
- judgment: The one boundary that must remain separate is the LlamaIndex retrieval/data pipeline (ingestion, indexing, retrieval, synthesis) from CouncilKit’s turn-based execution state—this ensures data-awareness stays explicit, auditable, and replaceable without conflating 'what was retrieved' with 'who said what when'.
- objection: CouncilKit’s current `harness_ingest.py` and `harness_runtime.py` show no use of `StorageContext`, `VectorStoreIndex`, or retriever composition—so adding LlamaIndex as a first-class data boundary now risks retrofitting without clear ingestion/retrieval contracts, leading to implicit coupling (e.g., hardcoding chunking logic in `loader.py`) that undermines the very separation it seeks.
- tradeoff: Enforcing this boundary requires CouncilKit to treat LlamaIndex components as *data services*, not runtime extensions—meaning explicit, versioned retrieval contracts (e.g., `RetrievalRequest`, `CitationNode`) must be defined and validated at harness ingress, sacrificing ad-hoc retrieval flexibility for reproducible, replayable data provenance.
- confidence: high
- evidence_path: LlamaIndex’s core identity is 'LLM over your data', not general agent orchestration [E2] [E3], Its value lies in拆able boundaries: retriever ≠ synthesizer ≠ query engine [E5] [E6] [E9]
- needs_verification: Whether `harness_ingest.py` currently uses `VectorStoreIndex` or raw `Document` ingestion

### review

#### round 1

##### FastAPI
- position: The strongest objection remains that FastAPI’s HTTP layer—while essential for exposing CouncilKit’s runtime state—is fundamentally incapable of enforcing the required separation between runtime and data state; it can only project what upstream components (e.g., `harness_runtime.py`, LangGraph’s checkpointing, LlamaIndex’s retrieval contracts) rigorously maintain.
- judgment: FastAPI must enforce a strict projection-only contract: all route handlers must depend solely on immutable, versioned runtime state models (e.g., `SessionTraceResponse`, `TurnLog`) and never accept or return raw `VectorStore`, `Index`, or `StateGraph` references—even via `Depends`. This preserves replayability by ensuring HTTP responses are deterministic projections, not live views into evolving data or execution state.
- objection: FastAPI alone cannot enforce separation of runtime vs.
- tradeoff: Enforcing this requires defining and maintaining versioned projection models for every runtime artifact surface (e.g., `/v1/sessions/{id}/trace`, `/v1/turns/{id}/log`), which sacrifices rapid iteration on ad-hoc endpoints—but prevents irreversible coupling between transport and domain state.
- confidence: high
- evidence_path: FastAPI’s `response_model` and type-driven validation are designed to filter and constrain output—not to mediate state ownership or mutability, Current `main.py` and `src/councilkit/runtime.py` show no use of `response_model` for session trace serialization, risking implicit leakage of internal objects
- needs_verification: Whether `src/councilkit/harness_runtime.py` already defines or imports Pydantic models for session/turn artifacts

##### LangGraph
- position: CouncilKit’s evolution beyond minimal review must treat LangGraph’s graph state as the sole source of truth for *execution continuity*—not just turn sequencing—by anchoring all durable workflows to explicit `StateGraph` schemas, checkpointed persistence, and `interrupt()`-driven human-in-the-loop boundaries; this preserves replayability only if runtime state (who did what, when, and how it resumed) is strictly decoupled from retrieval state (what was retrieved, how indexed, and where stored).
- judgment: The boundary that must remain separate is *graph execution state* (managed by LangGraph’s reducer-enforced, checkpointed `StateGraph`) from *retrieval/data state* (managed by LlamaIndex’s immutable `StorageContext`, `VectorStoreIndex`, and `Retriever` contracts)—because conflating them—e.g., embedding retrieval handles in graph state or letting retrieval nodes mutate core execution fields—violates LangGraph’s ‘state is contract’ discipline and breaks replay fidelity at the runtime root.
- objection: CouncilKit’s existing turn loop in `harness_runtime.py` assumes linear, append-only, stateless progression—introducing LangGraph’s mutable, checkpointed, interruptible graph state without rewriting that loop creates an unresolvable tension: either the old log-based trace becomes obsolete (breaking replay), or the new graph state becomes a redundant shadow (wasting durability guarantees).
- tradeoff: Enforcing this boundary demands upfront investment: defining versioned `State` schemas with strict reducer logic, wiring a production checkpointer (e.g., Postgres), and routing *all* data access through isolated `task` nodes—not inline calls—slowing initial workflow prototyping but preventing irreversible replay divergence when scaling beyond single-turn reviews.
- confidence: high
- evidence_path: CouncilKit’s current `harness_runtime.py` shows no `StateGraph`, `checkpointer`, or `interrupt()` usage—so adding durable execution without refactoring risks silent replay corruption., LangGraph v1 requires explicit reducers for any state key updated by multiple nodes; CouncilKit’s append-only turn logs currently lack merge semantics, making concurrent retrieval + execution updates unsafe.
- needs_verification: Whether `harness_runtime.py` can be incrementally refactored to delegate turn orchestration to a `StateGraph` without breaking existing `session_spec.py` contracts.

##### LlamaIndex
- position: CouncilKit must treat LlamaIndex as a strictly bounded, request-scoped data service—not an embedded runtime extension—by enforcing that all retrieval operations flow through versioned, immutable contracts (e.g., `RetrievalRequest` → `CitationNode[]` → `SynthesisResult`) validated at harness ingress, with no shared `StorageContext` or `VectorStoreIndex` instances across turns or sessions.
- judgment: The one boundary that must remain separate is the *data pipeline lifecycle* (ingestion → index → retrieve → synthesize) from CouncilKit’s *turn execution lifecycle*—because collapsing them (e.g., reusing a global `VectorStoreIndex` across sessions or letting synthesis mutate turn state) conflates data provenance with judgment sequencing, violating replayability and enabling silent drift in what ‘was retrieved’ vs. ‘was said’.
- objection: CouncilKit’s `loader.py` currently hardcodes chunking and parsing logic without metadata-aware node construction, meaning any LlamaIndex integration risks baking implicit data assumptions into the runtime layer—undermining the very separation it seeks to enforce.
- tradeoff: Enforcing this boundary sacrifices convenience: adding durable workflows requires explicit, versioned retrieval contracts and isolated ingestion per session (not global index reuse), slowing iteration—but prevents irreversible coupling where retrieval outputs become indistinguishable from turn artifacts in replay logs.
- confidence: high
- evidence_path: LlamaIndex’s core design assumes data boundaries are per-request or per-workflow, not per-runtime-session [E5][E6], CouncilKit’s current `harness_ingest.py` lacks `StorageContext` usage or retriever composition, indicating no existing data pipeline contract [E8][E9]
- needs_verification: Whether `harness_ingest.py` can be refactored to emit `Document`/`Node` objects compatible with `VectorStoreIndex` without leaking mutable state

## Synthesis Delta

### Coordinator Summary
All three skills converge on a core architectural tension: CouncilKit must add stateful execution (via LangGraph) and data-aware retrieval (via LlamaIndex) without eroding its foundational guarantees—replayability, explicit turn contracts, and the strict separation of runtime state (what happened, when, and who said it) from data state (what was retrieved, how, and from where). FastAPI reinforces that the HTTP layer must project only immutable, versioned artifacts—not expose or mediate underlying state.

### Final Decision
Enforce the retrieval/data pipeline boundary as the non-negotiable separation point—requiring per-session, isolated `StorageContext` and `VectorStoreIndex` instances, with retrieval results explicitly serialized into turn artifacts via versioned schemas—because this is the only boundary whose collapse directly and irreversibly corrupts replay provenance (e.g., 'what was cited' vs.

### Kept In Synthesis
- The retrieval/data pipeline lifecycle must be strictly isolated from turn execution lifecycle—no shared indexes, no global retrievers, no implicit citation state in graph nodes.
- LangGraph’s checkpointed `StateGraph` must replace the current append-only turn loop in `harness_runtime.py`, but only after defining reducer-enforced, immutable state keys and wiring a production checkpointer (e.g., Postgres).
- FastAPI route handlers must depend exclusively on versioned Pydantic projection models (e.g., `SessionTraceResponse`)—never on `VectorStore`, `State`, or `Index`—with all data/state access routed through controlled tasks or dependencies.

### Strongest Objections Preserved
- LangGraph (high): CouncilKit’s existing turn loop assumes linear, append-only, stateless progression—introducing LangGraph’s mutable, checkpointed, interruptible graph state without rewriting that loop creates an unresolvable tension: either the old log-based trace becomes obsolete (breaking replay), or the new graph state becomes a redundant shadow.
- FastAPI (high): FastAPI alone cannot enforce separation of runtime vs.
- LlamaIndex (medium): CouncilKit’s `loader.py` hardcodes chunking and parsing logic without metadata-aware node construction, meaning any LlamaIndex integration risks baking implicit data assumptions into the runtime layer—undermining the very separation it seeks to enforce.

### Next Steps
- Audit `harness_runtime.py` for existing `StateGraph`, `checkpointer`, or `interrupt()` usage—and if absent, draft a minimal `StateGraph` wrapper that preserves `session_spec.py` contract while enabling checkpointed recovery.
- Refactor `harness_ingest.py` to emit `Document`/`Node` objects compatible with `StorageContext` isolation, and define a `RetrievalRequest` schema with citation scope, reranking policy, and synthesizer selection.
- Introduce versioned Pydantic models in `src/councilkit/artifacts/` (e.g., `TurnLog`, `SessionTraceResponse`) and update `main.py` to use `response_model` exclusively—removing all direct injection of LlamaIndex or LangGraph primitives.

### Still Unresolved
- Can `harness_runtime.py` be incrementally refactored to delegate turn orchestration to a `StateGraph` without breaking existing `session_spec.py` contracts?

### Skill Notes
- FastAPI: FastAPI’s strength is output filtering via `response_model`; its weakness is zero enforcement over dependency injection—so enforcement must shift upstream to harness-level state modeling and dependency scoping.
- LangGraph: LangGraph treats checkpointing not as optional durability but as the foundation of replay safety—meaning CouncilKit’s current append-only logs are incompatible with durable workflows unless fully replaced or rigorously bridged.
- LlamaIndex: LlamaIndex’s value is in *disposable, request-scoped* data pipelines—not persistent agent memory—so CouncilKit must treat ingestion and indexing as per-session setup, not runtime infrastructure.

## Harness Handoff

- mode: review
- stage_order: survey, review, synthesis
- reduction_slots: judgment, evidence, tradeoff, objection, needs_verification, confidence
- selected_skill_slugs: fastapi, langgraph, llama-index
- handoff_path: --emit-harness-contract -> --emit-session-spec -> --emit-dispatch-template -> --validate-dispatch-payload -> --ingest-session-run
