# Harness Contract

CouncilKit exposes a narrow harness integration surface.

This document defines the current `v1` contract for:

- runtime-derived harness metadata
- session handoff artifacts
- external dispatch payload validation
- ingest back into CouncilKit artifacts

It does not define a second semantic layer on top of child `SKILL.md`.

## Principles

- `SKILL.md` is the only semantic source.
- Harness metadata is runtime-derived and disposable.
- Child skills stay single-file and self-contained.
- External harnesses may read runtime metadata, but should not write new semantics back into child skills.

## Canonical flow

The intended integration flow is:

1. `--emit-harness-contract`
2. `--verify-harness-contract`
3. `--emit-session-spec`
4. `--emit-dispatch-template`
5. external harness fills `turns` + `synthesis`
6. `--validate-dispatch-payload`
7. `--ingest-session-run`

The same shape can also be reconstructed from a CouncilKit `run.json`.

Checked-in reference fixtures live under `examples/ingest/`:

- `examples/ingest/session-spec.json`
- `examples/ingest/dispatch-template.json`
- `examples/ingest/external-run.json`

These fixtures are intended to be derived from a real CouncilKit run, not handwritten synthetic debate content.

## Surface 1: Harness Contract

Command:

```bash
python main.py \
  --emit-harness-contract \
  --brief examples/briefs/councilkit-hero-demo.md \
  --skills fastapi,do-things-that-dont-scale
```

Purpose:

- publish the runtime-facing contract without running model turns
- let an external harness read mode metadata, loaded skill provenance, and the six-slot reduction contract

Important fields:

- `harness.version`
- `harness.source_of_truth`
- `harness.prompt_contract`
- `harness.reduction_slots`
- `harness.mode`
- `harness.stage_order`
- `harness.rounds_per_stage`
- `harness.selected_skill_slugs`
- `harness.loaded_skill_slugs`
- `harness.skills[*].skill_file`
- `harness.skills[*].prompt_sha256`
- `admission.status`

Validation:

```bash
python main.py --verify-harness-contract traces/raw/councilkit-hero-demo/run.json
```

`--verify-harness-contract` checks:

- `source_of_truth == SKILL.md`
- canonical six-slot ordering
- selected vs loaded skill consistency
- current skill file existence
- prompt hash drift

## Surface 2: Session Spec

Command:

```bash
python main.py \
  --emit-session-spec \
  --session-spec-from traces/raw/councilkit-hero-demo/run.json
```

Purpose:

- publish a harness-readable session contract
- make the canonical dispatch order explicit

Stable fields:

- `version`
- `mode`
- `source_of_truth`
- `prompt_contract`
- `reduction_slots`
- `stages`
- `participants`
- `selected_skill_slugs`
- `loaded_skill_slugs`
- `turn_schedule`
- `admission`

Notes:

- `turn_schedule` is runtime-derived.
- External harnesses should consume `turn_schedule` directly instead of re-implementing participant rotation.
- `participants[*].prompt_sha256` is the replay/provenance guard.
- Relative `participants[*].skill_file` paths are resolved against the payload location first, then the repo root.

## Surface 3: Dispatch Template

Command:

```bash
python main.py \
  --emit-dispatch-template \
  --dispatch-template-from traces/raw/councilkit-hero-demo/run.json
```

Purpose:

- publish a fillable payload shell for external execution
- avoid bespoke payload assembly logic in harness code

Stable fields:

- `template_version`
- `prompt`
- `project_root`
- `shared_brief`
- `session_spec`
- `turns`
- `synthesis`

Turn scaffold shape:

```json
{
  "turn_index": 1,
  "stage": "survey",
  "round_index": 1,
  "skill_slug": "fastapi",
  "skill_name": "FastAPI",
  "message": "",
  "judgment": "",
  "evidence": [],
  "tradeoff": "",
  "objection": "",
  "needs_verification": [],
  "confidence": ""
}
```

Synthesis scaffold shape:

```json
{
  "title": "",
  "summary": "",
  "decision": "",
  "key_decisions": [],
  "strongest_objections": [],
  "next_steps": [],
  "open_questions": [],
  "skill_notes": []
}
```

## Surface 4: Dispatch Payload Validation

Command:

```bash
python main.py \
  --validate-dispatch-payload examples/ingest/external-run.json
```

Purpose:

- run preflight validation before ingest
- reuse the same structural checks as `--ingest-session-run`
- avoid writing CouncilKit artifacts during validation

Accepted inputs:

- a harness-style dispatch payload
- an existing CouncilKit `run.json`
- relative `project_root` and `skill_file` values are normalized through the same repo-aware resolution logic used by ingest

Top-level report fields:

- `status`
- `issues`
- `issues_by_turn`
- `issues_by_section`
- `recommended_repair_order`
- `repair_hints`
- `expected_contract`
- `checked_skills`
- `selected_skill_slugs`
- `turn_count`
- `source_ref`

Status semantics:

- `pass`: no issues
- `pass_with_warning`: non-blocking issues only
- `fail`: at least one blocking issue

### `issues`

The raw issue list is the most precise surface.

An issue may include:

- `level`
- `code`
- `message`
- `source_stage`
- `turn_index`
- `field_path`
- `expected`
- `actual`

Typical examples:

- `turns[0].confidence`
- `synthesis.title`
- `session_spec.participants[*].prompt_sha256`

### `issues_by_turn`

Grouped turn-local failures for harness repair loops.

Each item includes:

- `turn_index`
- `blocking`
- `blocking_issue_count`
- `non_blocking_issue_count`
- `priority_rank`
- `issue_count`
- `codes`
- `issues`

### `issues_by_section`

Grouped section-level failures for orchestration UIs.

Current sections include:

- `payload`
- `prompt`
- `session_spec`
- `turns`
- `synthesis`

Each item includes:

- `section`
- `blocking`
- `blocking_issue_count`
- `non_blocking_issue_count`
- `priority_rank`
- `issue_count`
- `codes`
- `issues`

### `repair_hints`

Machine-readable fix hints keyed by failure code.

Each hint includes:

- `code`
- `target`
- `action`
- `suggested_fix`
- optional `expected`

Examples of current actions:

- `fill_reduction_slots`
- `normalize_confidence`
- `realign_turn_count`
- `realign_turn_order`
- `fill_synthesis_contract`
- `regenerate_session_artifacts`

### `recommended_repair_order`

This is the preferred harness scheduling surface.

It flattens grouped failures into one queue so the harness does not need to merge `issues_by_turn` and `issues_by_section` itself.

Each queue item includes:

- `position`
- `scope_type`
- `scope_id`
- `blocking`
- `priority_rank`
- `issue_count`
- `codes`
- `issue_indexes`
- `primary_code`
- `primary_field_path`
- `primary_action`
- `suggested_fix`

Current ordering rules:

- blocking groups before non-blocking groups
- turn groups sorted by turn index
- section groups sorted by a stable internal section priority

## Surface 5: Ingest

Command:

```bash
python main.py \
  --ingest-session-run examples/ingest/external-run.json \
  --output-root traces/raw \
  --ingest-directory-name imported-harness-run
```

Purpose:

- convert validated external dispatch output into CouncilKit artifacts
- preserve replayability and provenance

Required payload content:

- `prompt` or `task.prompt`
- `session_spec` or `session_spec_path` or `harness`/`run.json`-compatible source
- `turns`
- `synthesis`

Ingest writes:

- `run.json`
- `transcript.md`
- `result.md`
- `debate.md`
- `failure-events.jsonl` when applicable

## Stable contract boundaries

CouncilKit treats the following as stable harness-facing runtime surfaces for `v1`:

- harness contract fields emitted by `--emit-harness-contract`
- session spec fields emitted by `--emit-session-spec`
- dispatch template fields emitted by `--emit-dispatch-template`
- validator report fields emitted by `--validate-dispatch-payload`
- ingest acceptance criteria enforced by `--ingest-session-run`

CouncilKit does not treat the following as external semantic contract:

- child skill internal prose structure beyond `SKILL.md` being the source of truth
- any bundle-era sidecar files
- any external registry or marketplace metadata

## Non-goals

This contract does not define:

- a universal skill ontology
- a distributed multi-agent runtime
- a GUI workflow
- a persistent skill registry
- mutation of child skills by the harness
