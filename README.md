# Minimal Debate MVP

This project is now intentionally small.

## Project Philosophy

This project is not trying to build yet another scaffold. It validates one core idea:
personify the project itself as a debating team, where each tech-stack agent carries accumulated team wisdom in runnable `agent.json` files, then lets FastAPI/LangGraph/PostgreSQL debate the same request and converge on a practical design.

In this framing, `agent.json` is not a prompt template. It is a compact, executable memory of team judgment: boundaries, principles, evidence anchors, representative cases, and known controversies.

The MVP goals are explicit:

- One command to run: `python main.py`
- Visible process: round-by-round terminal output for screen recording
- Traceable outcomes: keep `transcript.md`, `result.md`, and `run.json`
- Clear boundaries: FastAPI / LangGraph / PostgreSQL each hold their own responsibility
- Evidence-backed consensus: `agent.json` includes anchors/cases/controversies instead of vague personas

In short, this repository demonstrates how team intelligence can be structured and reused, not how much code can be added.

It keeps only:

- `main.py`: the runnable MVP
- `examples/packs/*/agent.json`: the three project agents used in the debate
- `examples/prompts/ai-support-backend.md`: the default prompt

## Setup

```bash
pip install -r requirements.txt
cp env.example .env
```

Fill `.env` with one compatible endpoint:

- OpenAI official: leave `OPENAI_BASE_URL` empty
- DashScope compatible endpoint
- DeepSeek compatible endpoint

## Run

Run with the default example prompt:

```bash
python main.py
```

By default, debate turns are printed live in terminal (stage/round/agent) for screen recording.
The MVP runs 3 rounds for each debate stage (`alignment`, `proposal`, `challenge`).

Run with an inline prompt:

```bash
python main.py --prompt "Build a private-deployable AI support backend."
```

Disable live terminal logs:

```bash
python main.py --quiet
```

Artifacts are written under `runs/<timestamp>/`:

- `transcript.md`
- `result.md`
- `run.json`

Pack format note:

- This runtime is `agent.json` only.
- If an agent pack misses `agent.json`, `main.py` exits with an explicit error.
