# Typed Support Flow MVP

Prompt: # Example Input Prompt

Build a private-deployable AI support backend with:

- typed HTTP APIs
- persisted conversation state
- a bounded workflow engine
- one minimal smoke-testable support conversation flow

## Summary
A private-deployable AI support backend with strictly separated concerns: FastAPI exposes two typed HTTP endpoints for conversation lifecycle; LangGraph executes a minimal three-node state machine (classify → fetch → format) with explicit, relational checkpointing; PostgreSQL stores conversations, messages, and workflow state in normalized, constraint-enforced tables—no JSONB for core facts, no embedded logic, no untyped payloads.

## Architecture
FastAPI (transport) → LangGraph (orchestration) → PostgreSQL (persistence). FastAPI validates and routes via Pydantic v2 models. LangGraph runs a versioned graph with typed State, writing intent/resolution/status as first-class columns to PostgreSQL. PostgreSQL uses three tables with foreign keys, NOT NULL, CHECK constraints, and indexes—workflow_checkpoints omits state_json, promoting key fields to typed columns.

## MVP Scope
Two endpoints: POST /conversations (creates active conversation) and POST /conversations/{id}/messages (adds user message and triggers LangGraph run); one smoke-testable flow (user asks 'how do I reset password?' → system classifies intent → fetches canned resolution → formats response); all layers testable in isolation; deployable via Docker Compose with FastAPI, LangGraph, and PostgreSQL.
