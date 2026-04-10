from __future__ import annotations

from pathlib import Path

from ..runtime import run


def run_session(
    *,
    repo_root: Path,
    prompt_arg: str | None,
    brief_arg: str | None,
    skill_root: Path,
    selected_skills: list[str] | None,
    project_root: Path,
    output_root: Path,
    quiet: bool,
) -> Path:
    return run(
        prompt=prompt_arg,
        brief=brief_arg,
        skill_root=skill_root,
        skills=selected_skills,
        project_root=project_root,
        output_root=output_root,
        repo_root=repo_root,
        echo=not quiet,
    )
