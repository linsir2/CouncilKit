# CouncilKit Hero Demo Synthesis

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

## Summary
Both FastAPI and Do Things That Don't Scale agree CouncilKit’s first version must prioritize replayability and bounded utility by enforcing strict, observable contracts—either via typed HTTP interfaces (FastAPI) or manual-first execution with full trace observability (DTTDS). They converge on the runtime’s current failure to satisfy either: `main.py` lacks Pydantic models for request/response, and `runtime.py` lacks enforced, serializable turn boundaries—making traces opaque and replay impossible.

## Decision
Ship v0.1 as a CLI-only, append-only, single-process runtime that enforces per-turn output capture and structured serialization—*before* exposing any HTTP surface—while simultaneously adding minimal Pydantic models to `harness_contract.py` and `main.py` to declare the brief ingestion and synthesis output schemas, even if the API remains unexposed in v0.1.

## Key Decisions
- Require explicit, timestamped, per-participant output serialization in `runtime.py`'s `turn()` loop before shipping v0.1.
- Add versioned Pydantic models to `harness_contract.py` for brief ingestion and synthesis memo, regardless of whether `main.py` exposes them publicly yet.
- Defer HTTP API exposure until both turn-level replay and contract typing are verified—not as a feature, but as a hard gate.

## Strongest Objections
- FastAPI (high): The current `main.py` exposes raw dict-based endpoints with no Pydantic models or response_model declarations, violating FastAPI’s core principle that 'type declaration is the contract' and making replay impossible if payloads evolve silently.
- Do Things That Don't Scale (high): The absence of explicit, serializable turn boundaries in `runtime.py` means participant outputs are not captured, timestamped, or diffable per-turn—so even manual runs produce non-reproducible traces unless output interception and structured logging are added before shipping.

## Next Steps
- Instrument `runtime.py` to emit deterministic, JSON-serializable turn artifacts (input, skill ID, output, timestamp, error if any) to disk per turn.
- Define and implement `BriefIngestionRequest` and `SynthesisMemoResponse` Pydantic models in `harness_contract.py`, then verify they cover all fields used in `harness_ingest.py` and `harness.py`.
- Update `cli.py` to accept `--replay <session-id>` flag that reloads and re-executes from persisted turn artifacts.

## Open Questions
- Does `dispatch_template.py` rely on implicit filesystem ordering or mutable global state that breaks deterministic replay across environments?

## Skill Notes
- FastAPI: Type enforcement must begin at the contract boundary—even if the API isn’t public yet, the models must exist and be used internally to prevent silent drift in payload structure.
- Do Things That Don't Scale: Manual execution only delivers learning value if every step—including output capture, annotation, and provenance tracking—is explicit, inspectable, and repeatable by hand; automation before that is premature scaling.
