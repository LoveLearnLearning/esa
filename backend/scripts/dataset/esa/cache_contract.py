"""Source fingerprints used to reject stale dataset caches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROMPT_SOURCE_GLOBS = (
    "backend/agent/skills/**/*.md",
    "backend/agent/learning/pedagogy_router.py",
    "backend/agent/learning/practice_context.py",
    "backend/agent/tools/bootstrap.py",
    "backend/agent/tools/catalog.py",
    "backend/agent/tools/contextual_schemas.py",
    "backend/agent/tools/skills.py",
    "backend/agent/skills/catalog.py",
    "backend/agent/workspaces/*.py",
    "backend/core/message/*.py",
    "backend/core/message/prompts/*.py",
    "backend/core/router/basic_router.py",
    "backend/core/router/context.py",
    "backend/core/router/models.py",
)


def _hash_files(repo: Path, files: set[Path]) -> dict[str, str]:
    """Hash source files by stable repository-relative path."""
    return {
        path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
        if path.is_file()
    }


def prompt_source_hashes(repo: Path) -> dict[str, str]:
    """Return hashes for every source that can affect a captured system prompt."""
    files: set[Path] = set()
    for pattern in PROMPT_SOURCE_GLOBS:
        files.update(repo.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no prompt source files found under {repo}")
    return _hash_files(repo, files)


def prompt_source_fingerprint(repo: Path) -> str:
    """Return one deterministic digest for the production prompt source set."""
    payload = json.dumps(
        prompt_source_hashes(repo),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def skill_source_hashes(repo: Path) -> dict[str, str]:
    """Return hashes for the complete recursive Skill source tree."""
    skills_dir = repo / "backend/agent/skills"
    files = set(skills_dir.rglob("*.md"))
    if not files:
        raise FileNotFoundError(f"no Skill files found under {skills_dir}")
    return {
        path.relative_to(skills_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(files)
    }
