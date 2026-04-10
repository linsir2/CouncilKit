from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


class LLMClient:
    def __init__(self, api_key: str, model: str, base_url: str | None) -> None:
        self.model = model
        self.base_url = base_url
        self.client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=90)

    @classmethod
    def from_env(cls, repo_root: Path) -> "LLMClient":
        load_dotenv(repo_root / ".env")

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required.")

        model = os.environ.get("OPENAI_MODEL", "").strip() or "qwen-plus"
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
        return cls(api_key=api_key, model=model, base_url=base_url)

    def complete_json(self, *, role: str, stage: str, prompt: str, context: str) -> dict[str, Any]:
        if stage == "synthesis":
            schema_hint = (
                '{"title":"short title","summary":"one short paragraph","decision":"one short paragraph",'
                '"key_decisions":["one sentence"],'
                '"strongest_objections":[{"skill":"name","objection":"one sentence","severity":"low|medium|high"}],'
                '"next_steps":["one sentence"],'
                '"open_questions":["one sentence"],'
                '"skill_notes":[{"skill":"name","note":"one sentence"}]}'
            )
            system_prompt = (
                f"You are {role} in a single-file skill runtime.\n"
                "Synthesize a concise review memo from the prior turns.\n"
                "Preserve disagreement and tradeoffs.\n"
                "Return JSON only."
            )
        else:
            schema_hint = (
                '{"message":"one short paragraph","judgment":"one short paragraph","evidence":["short bullet"],'
                '"tradeoff":"one short paragraph","objection":"one short paragraph or empty string",'
                '"needs_verification":["short item"],"confidence":"high|medium|low"}'
            )
            system_prompt = (
                f"You are {role}.\n"
                "Treat the supplied SKILL.md as your persona and reasoning contract.\n"
                "Use only the brief, shared context, prior turns, and supplied skill text.\n"
                "Return JSON only."
            )

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"{system_prompt}\nSchema: {schema_hint}"},
                {"role": "user", "content": f"User brief:\n{prompt}\n\nRuntime context:\n{context}"},
            ],
            temperature=0.4,
        )
        raw = completion.choices[0].message.content or ""
        return extract_json_object(raw)


def extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(f"Model did not return JSON: {raw[:200]}")
    return json.loads(text[start : end + 1])
