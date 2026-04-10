from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .constants import DEFAULT_BRIEF_FILE, SKILL_ROOT
from .models import SkillSpec

SNAPSHOT_FILE_LIMIT = 20
SNAPSHOT_EXACT_PRIORITY = (
    "README.md",
    "main.py",
    "src/councilkit/cli.py",
    "src/councilkit/runtime.py",
    "src/councilkit/harness_ingest.py",
    "src/councilkit/harness.py",
    "src/councilkit/loader.py",
    "src/councilkit/session_spec.py",
    "authoring/project-incarnation/SKILL.md",
    "docs/harness-contract.md",
    "examples/briefs/councilkit-hero-demo.md",
    "examples/briefs/councilkit-runtime-triad.md",
)
SNAPSHOT_PREFIX_PRIORITY = (
    "src/",
    "skills/",
    "authoring/",
    "examples/briefs/",
    "examples/ingest/",
    "docs/",
    "tests/",
)
SNAPSHOT_SKIP_PARTS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    ".venv",
    "artifacts",
    "traces",
}


def parse_frontmatter(markdown: str) -> dict[str, str]:
    if not markdown.startswith("---\n"):
        return {}
    try:
        _, frontmatter, _ = markdown.split("---", 2)
    except ValueError:
        return {}
    payload: dict[str, str] = {}
    current_key: str | None = None
    buffer: list[str] = []
    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if current_key and (line.startswith("  ") or line.startswith("\t")):
            buffer.append(line.strip())
            continue
        if current_key:
            payload[current_key] = "\n".join(buffer).strip()
            current_key = None
            buffer = []
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "|":
            current_key = key
            buffer = []
        else:
            payload[key] = value
    if current_key:
        payload[current_key] = "\n".join(buffer).strip()
    return payload


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9._-]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or "skill"


def load_prompt(repo_root: Path, prompt: str | None, brief: str | None) -> str:
    if brief:
        brief_path = Path(brief)
        if not brief_path.is_absolute():
            brief_path = repo_root / brief_path
        return brief_path.read_text(encoding="utf-8").strip()
    if prompt:
        return prompt.strip()
    return (repo_root / DEFAULT_BRIEF_FILE).read_text(encoding="utf-8").strip()


def project_snapshot(project_root: Path) -> str:
    readme_path = project_root / "README.md"
    readme_excerpt = ""
    if readme_path.exists():
        readme_excerpt = readme_path.read_text(encoding="utf-8")[:1200].strip()

    project_files = _collect_project_snapshot_files(project_root)

    lines = [f"Project root: {project_root}"]
    if project_files:
        lines.append("Top project files:")
        lines.extend(f"- {path}" for path in project_files)
    if readme_excerpt:
        lines.append("")
        lines.append("README excerpt:")
        lines.append(readme_excerpt)
    return "\n".join(lines)


def _collect_project_snapshot_files(project_root: Path) -> list[str]:
    files = _git_live_files(project_root)
    if not files:
        files = _walk_live_files(project_root)
    return sorted(files, key=_snapshot_sort_key)[:SNAPSHOT_FILE_LIMIT]


def _git_live_files(project_root: Path) -> list[str]:
    git_dir = project_root / ".git"
    if not git_dir.exists():
        return []
    candidates: list[str] = []
    try:
        tracked = subprocess.run(
            ["git", "-C", str(project_root), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
        untracked = subprocess.run(
            ["git", "-C", str(project_root), "ls-files", "--others", "--exclude-standard"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    seen: set[str] = set()
    for output in (tracked.stdout, untracked.stdout):
        for raw_line in output.splitlines():
            relative = raw_line.strip()
            if not relative or relative in seen:
                continue
            seen.add(relative)
            path = project_root / relative
            if _include_snapshot_path(path, project_root):
                candidates.append(relative)
    return candidates


def _walk_live_files(project_root: Path) -> list[str]:
    candidates: list[str] = []
    for path in project_root.rglob("*"):
        if _include_snapshot_path(path, project_root):
            candidates.append(str(path.relative_to(project_root)))
    return candidates


def _include_snapshot_path(path: Path, project_root: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    relative = path.relative_to(project_root)
    if any(part in SNAPSHOT_SKIP_PARTS for part in relative.parts):
        return False
    return True


def _snapshot_sort_key(relative_path: str) -> tuple[int, int, str]:
    exact_rank = SNAPSHOT_FILE_LIMIT + 100
    for index, exact in enumerate(SNAPSHOT_EXACT_PRIORITY):
        if relative_path == exact:
            exact_rank = index
            break

    prefix_rank = SNAPSHOT_FILE_LIMIT + 200
    for index, prefix in enumerate(SNAPSHOT_PREFIX_PRIORITY):
        if relative_path.startswith(prefix):
            prefix_rank = index
            break

    return (exact_rank, prefix_rank, relative_path)


def _path_like(value: str) -> bool:
    return "/" in value or "\\" in value or value.startswith(".")


def resolve_skill_dir(spec: str, repo_root: Path, skill_root: Path) -> Path:
    if _path_like(spec):
        candidate = Path(spec)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        if candidate.exists() and candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"Skill directory not found: {candidate}")

    candidates = [
        skill_root / spec,
        repo_root / SKILL_ROOT / spec,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Could not resolve skill '{spec}'. Searched: {searched}")


def load_skill_specs(
    repo_root: Path,
    skill_root: Path = SKILL_ROOT,
    selected_skills: list[str] | None = None,
) -> list[SkillSpec]:
    resolved_root = skill_root if skill_root.is_absolute() else repo_root / skill_root
    if selected_skills:
        skill_dirs = [resolve_skill_dir(spec, repo_root, resolved_root) for spec in selected_skills]
    else:
        if not resolved_root.exists():
            raise FileNotFoundError(f"Skill root not found: {resolved_root}")
        skill_dirs = sorted(path for path in resolved_root.iterdir() if path.is_dir())

    skills: list[SkillSpec] = []
    for skill_dir in skill_dirs:
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            raise FileNotFoundError(f"Missing required skill file: {skill_file}")

        skill_markdown = skill_file.read_text(encoding="utf-8").strip()
        frontmatter = parse_frontmatter(skill_markdown)
        title_match = re.search(r"^#\s+(.+)$", skill_markdown, flags=re.MULTILINE)
        tagline_match = re.search(r"^>\s+(.+)$", skill_markdown, flags=re.MULTILINE)

        name = (
            frontmatter.get("name")
            or (title_match.group(1).strip() if title_match else "")
            or skill_dir.name
        )
        title = (title_match.group(1).strip() if title_match else "") or name
        description = frontmatter.get("description", "").strip()
        tagline = tagline_match.group(1).strip() if tagline_match else ""

        skills.append(
            SkillSpec(
                slug=slugify(frontmatter.get("name") or skill_dir.name),
                name=title,
                description=description,
                tagline=tagline,
                skill_markdown=skill_markdown,
                skill_dir=skill_dir,
                skill_file=skill_file,
                skill_mtime=skill_file.stat().st_mtime,
            )
        )

    return skills
