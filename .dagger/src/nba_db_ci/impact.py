"""Conservative changed-path classification shared by Dagger and host hooks."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum


class Impact(str, Enum):
    DOCS = "docs"
    FRONTEND = "frontend"
    LIFECYCLE = "lifecycle"
    FULL = "full"


DOC_SUFFIXES = {".md", ".mdx", ".txt"}
DOC_EXACT = {"LICENSE", "LICENSE.md"}
FRONTEND_PREFIXES = ("app/static/", "app/templates/")
FRONTEND_EXACT = {"tests/test_frontend_safety.py", "tests/test_browser.py"}
LIFECYCLE_PREFIXES = ("etl/",)
LIFECYCLE_EXACT = {"tests/test_season_lifecycle.py", "tests/test_etl_load.py"}


def _normalize(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_docs(path: str) -> bool:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return path in DOC_EXACT or path.startswith("docs/") or suffix in DOC_SUFFIXES


def _is_frontend(path: str) -> bool:
    return path in FRONTEND_EXACT or path.startswith(FRONTEND_PREFIXES)


def _is_lifecycle(path: str) -> bool:
    return path in LIFECYCLE_EXACT or path.startswith(LIFECYCLE_PREFIXES)


def classify_paths(paths: Sequence[str]) -> Impact:
    """Return the narrowest safe check group for the changed paths."""
    normalized = [path for value in paths if (path := _normalize(value))]
    if not normalized:
        return Impact.FULL
    if all(_is_docs(path) for path in normalized):
        return Impact.DOCS
    if all(_is_docs(path) or _is_frontend(path) for path in normalized):
        return Impact.FRONTEND
    if all(_is_docs(path) or _is_lifecycle(path) for path in normalized):
        return Impact.LIFECYCLE
    return Impact.FULL
