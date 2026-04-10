from __future__ import annotations

import re

from .models import AdmissionCandidate, AdmissionResult, RejectedSkill, SkillSpec

RUNNABLE_STATUSES = {"accept", "accept_with_warning"}
ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]{1,}")
CJK_SEQUENCE_RE = re.compile(r"[\u4e00-\u9fff]+")
EN_STOPWORDS = {
    "about",
    "after",
    "against",
    "also",
    "and",
    "are",
    "back",
    "before",
    "build",
    "brief",
    "could",
    "design",
    "does",
    "first",
    "from",
    "have",
    "into",
    "keep",
    "mode",
    "more",
    "must",
    "need",
    "next",
    "only",
    "plan",
    "project",
    "review",
    "risk",
    "runtime",
    "should",
    "some",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "those",
    "using",
    "what",
    "with",
}


def prepare_session(
    *,
    skill_specs: list[SkillSpec],
    prompt: str,
    explicit_skill_selection: bool,
    max_default_selected: int = 3,
    hard_cap: int = 4,
) -> AdmissionResult:
    if not skill_specs:
        return AdmissionResult(
            status="needs_clarification",
            reason="No runtime skills were found. Add at least one SKILL.md under the selected skill root.",
            candidate_skills=(),
            selected_skills=(),
            warnings=("No skills available for this session.",),
        )

    prompt_terms = _tokenize(prompt)
    probed = tuple(_probe_skill(spec, prompt_terms) for spec in skill_specs)

    if explicit_skill_selection:
        candidate_skills = probed
        selected = tuple(item.slug for item in candidate_skills)
    else:
        ranked = sorted(probed, key=lambda item: (-item.score, item.name.lower()))
        candidate_skills = tuple(ranked)
        if not ranked or ranked[0].score <= 0:
            return AdmissionResult(
                status="needs_clarification",
                reason="No candidate skill could be selected. Clarify the brief or provide explicit --skills.",
                candidate_skills=candidate_skills,
                selected_skills=(),
                warnings=("No selected skills for this session.",),
            )
        selected = tuple(item.slug for item in ranked if item.score > 0)[:max_default_selected]

    warnings: list[str] = []
    rejected: list[RejectedSkill] = []

    if explicit_skill_selection and len(selected) > hard_cap:
        kept = selected[:hard_cap]
        dropped = selected[hard_cap:]
        rejected.extend(
            RejectedSkill(slug=slug, reason=f"Exceeds v1 hard cap of {hard_cap} selected skills.")
            for slug in dropped
        )
        warnings.append(f"Selected {len(selected)} skills, but v1 supports at most {hard_cap}.")
        return AdmissionResult(
            status="out_of_scope",
            reason=f"Requested {len(selected)} skills. Reduce to at most {hard_cap} for v1 runtime sessions.",
            candidate_skills=candidate_skills,
            selected_skills=kept,
            rejected_skills=tuple(rejected),
            warnings=tuple(warnings),
        )

    if not selected:
        return AdmissionResult(
            status="needs_clarification",
            reason="No candidate skill could be selected. Clarify the brief or provide explicit --skills.",
            candidate_skills=candidate_skills,
            selected_skills=(),
            warnings=("No selected skills for this session.",),
        )

    overflow = selected[max_default_selected:]
    if overflow:
        warnings.append(
            f"Session selected {len(selected)} skills; default is {max_default_selected}. "
            "Expect broader context and less focused discussion."
        )
        return AdmissionResult(
            status="accept_with_warning",
            reason=f"Session is runnable, but selected skill count is above the default ({max_default_selected}).",
            candidate_skills=candidate_skills,
            selected_skills=selected,
            warnings=tuple(warnings),
        )

    trimmed = set(item.slug for item in candidate_skills) - set(selected)
    rejected.extend(
        RejectedSkill(slug=slug, reason=f"Not selected in this run (default cap {max_default_selected}).")
        for slug in sorted(trimmed)
    )
    return AdmissionResult(
        status="accept",
        reason=f"Session is runnable with {len(selected)} selected skill(s).",
        candidate_skills=candidate_skills,
        selected_skills=selected,
        rejected_skills=tuple(rejected),
        warnings=tuple(warnings),
    )


def _probe_skill(spec: SkillSpec, prompt_terms: set[str]) -> AdmissionCandidate:
    slug_terms = {part for part in re.split(r"[-_.]+", spec.slug.lower()) if len(part) >= 2}
    name_terms = _tokenize(spec.name)
    description_terms = _tokenize(spec.description)
    tagline_terms = _tokenize(spec.tagline)
    trigger_terms = _extract_trigger_terms(spec.skill_markdown)
    section_terms = _extract_section_term_index(spec.skill_markdown)
    applicable_terms = section_terms["applicable"]
    anti_terms = section_terms["anti"]
    watch_terms = section_terms["watch"]
    scope_terms = (
        slug_terms
        | name_terms
        | description_terms
        | tagline_terms
        | trigger_terms
        | applicable_terms
        | watch_terms
        | anti_terms
    )

    matched_terms = sorted(term for term in prompt_terms if term in scope_terms)
    score = 0
    for term in matched_terms:
        if term in anti_terms:
            score -= 4
            continue
        if term in slug_terms:
            score += 4
            continue
        if term in applicable_terms:
            score += 3
            continue
        if term in name_terms or term in trigger_terms:
            score += 3
            continue
        if term in description_terms:
            score += 2
            continue
        if term in watch_terms:
            score += 1
            continue
        score += 1

    return AdmissionCandidate(
        slug=spec.slug,
        name=spec.name,
        score=score,
        matched_terms=tuple(matched_terms),
    )


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    tokens: set[str] = set()
    lowered = text.lower()
    for raw in ASCII_TOKEN_RE.findall(lowered):
        token = raw.strip("._-")
        if len(token) < 2 or token in EN_STOPWORDS:
            continue
        tokens.add(token)
    for sequence in CJK_SEQUENCE_RE.findall(text):
        tokens.update(_tokenize_cjk_sequence(sequence))
    return tokens


def _tokenize_cjk_sequence(sequence: str) -> set[str]:
    normalized = "".join(ch for ch in sequence if ch.strip())
    if not normalized:
        return set()
    if len(normalized) == 1:
        return set()
    tokens = {normalized[index : index + 2] for index in range(len(normalized) - 1)}
    if len(normalized) <= 6:
        tokens.add(normalized)
    return tokens


def _extract_trigger_terms(markdown: str) -> set[str]:
    if not markdown:
        return set()
    tokens: set[str] = set()
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "触发词" not in line and "trigger" not in line.lower():
            continue
        if "：" in line:
            _, payload = line.split("：", 1)
        elif ":" in line:
            _, payload = line.split(":", 1)
        else:
            continue
        for part in re.split(r"[、,，;/；|]", payload):
            tokens.update(_tokenize(part))
    return tokens


def _extract_section_term_index(markdown: str) -> dict[str, set[str]]:
    if not markdown:
        return {"applicable": set(), "anti": set(), "watch": set()}

    collected = {"applicable": set(), "anti": set(), "watch": set()}
    current_key: str | None = None
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            current_key = _heading_bucket(line[3:].strip())
            continue
        if current_key is None:
            continue
        content = line.lstrip("-*0123456789. ").strip()
        if not content:
            continue
        collected[current_key].update(_tokenize(content))
    return collected


def _heading_bucket(raw_heading: str) -> str | None:
    heading = raw_heading.lower().replace(" ", "")
    if "适用问题" in raw_heading or "applicable" in heading:
        return "applicable"
    if "不适用问题" in raw_heading or "误判警报" in raw_heading:
        return "anti"
    if "notapplicable" in heading or "outofscope" in heading or "misuse" in heading or "confusion" in heading:
        return "anti"
    if "watchlist" in heading:
        return "watch"
    return None
