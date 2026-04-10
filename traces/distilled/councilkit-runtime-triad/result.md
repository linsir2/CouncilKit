# CouncilKit State & Retrieval Boundary Synthesis

Brief: # CouncilKit Runtime Triad Brief

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

## Summary
All three skills converge on a core architectural tension: CouncilKit must add stateful execution (via LangGraph) and data-aware retrieval (via LlamaIndex) without eroding its foundational guarantees—replayability, explicit turn contracts, and the strict separation of runtime state (what happened, when, and who said it) from data state (what was retrieved, how, and from where). FastAPI reinforces that the HTTP layer must project only immutable, versioned artifacts—not expose or mediate underlying state.

## Decision
Enforce the retrieval/data pipeline boundary as the non-negotiable separation point—requiring per-session, isolated `StorageContext` and `VectorStoreIndex` instances, with retrieval results explicitly serialized into turn artifacts via versioned schemas—because this is the only boundary whose collapse directly and irreversibly corrupts replay provenance (e.g., 'what was cited' vs.

## Key Decisions
- The retrieval/data pipeline lifecycle must be strictly isolated from turn execution lifecycle—no shared indexes, no global retrievers, no implicit citation state in graph nodes.
- LangGraph’s checkpointed `StateGraph` must replace the current append-only turn loop in `harness_runtime.py`, but only after defining reducer-enforced, immutable state keys and wiring a production checkpointer (e.g., Postgres).
- FastAPI route handlers must depend exclusively on versioned Pydantic projection models (e.g., `SessionTraceResponse`)—never on `VectorStore`, `State`, or `Index`—with all data/state access routed through controlled tasks or dependencies.

## Strongest Objections
- LangGraph (high): CouncilKit’s existing turn loop assumes linear, append-only, stateless progression—introducing LangGraph’s mutable, checkpointed, interruptible graph state without rewriting that loop creates an unresolvable tension: either the old log-based trace becomes obsolete (breaking replay), or the new graph state becomes a redundant shadow.
- FastAPI (high): FastAPI alone cannot enforce separation of runtime vs.
- LlamaIndex (medium): CouncilKit’s `loader.py` hardcodes chunking and parsing logic without metadata-aware node construction, meaning any LlamaIndex integration risks baking implicit data assumptions into the runtime layer—undermining the very separation it seeks to enforce.

## Next Steps
- Audit `harness_runtime.py` for existing `StateGraph`, `checkpointer`, or `interrupt()` usage—and if absent, draft a minimal `StateGraph` wrapper that preserves `session_spec.py` contract while enabling checkpointed recovery.
- Refactor `harness_ingest.py` to emit `Document`/`Node` objects compatible with `StorageContext` isolation, and define a `RetrievalRequest` schema with citation scope, reranking policy, and synthesizer selection.
- Introduce versioned Pydantic models in `src/councilkit/artifacts/` (e.g., `TurnLog`, `SessionTraceResponse`) and update `main.py` to use `response_model` exclusively—removing all direct injection of LlamaIndex or LangGraph primitives.

## Open Questions
- Can `harness_runtime.py` be incrementally refactored to delegate turn orchestration to a `StateGraph` without breaking existing `session_spec.py` contracts?

## Skill Notes
- FastAPI: FastAPI’s strength is output filtering via `response_model`; its weakness is zero enforcement over dependency injection—so enforcement must shift upstream to harness-level state modeling and dependency scoping.
- LangGraph: LangGraph treats checkpointing not as optional durability but as the foundation of replay safety—meaning CouncilKit’s current append-only logs are incompatible with durable workflows unless fully replaced or rigorously bridged.
- LlamaIndex: LlamaIndex’s value is in *disposable, request-scoped* data pipelines—not persistent agent memory—so CouncilKit must treat ingestion and indexing as per-session setup, not runtime infrastructure.
