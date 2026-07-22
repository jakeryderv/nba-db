#!/usr/bin/env python3
"""Perform fast, dependency-free Markdown hygiene and local-link checks."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote

LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
REMOTE_SCHEMES = ("http://", "https://", "mailto:", "tel:")


def markdown_files(paths: Sequence[str]) -> list[Path]:
    if paths:
        return sorted(
            {Path(path) for path in paths if Path(path).suffix.lower() in {".md", ".mdx"}}
        )
    tracked_docs = [Path("README.md")]
    if Path("docs").is_dir():
        tracked_docs.extend(Path("docs").rglob("*.md"))
        tracked_docs.extend(Path("docs").rglob("*.mdx"))
    return sorted(path for path in tracked_docs if path.is_file())


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{path}: cannot read UTF-8 Markdown: {exc}"]

    if contents and not contents.endswith("\n"):
        errors.append(f"{path}: file must end with a newline")
    for number, line in enumerate(contents.splitlines(), start=1):
        if line.rstrip(" \t") != line:
            errors.append(f"{path}:{number}: trailing whitespace")

    fences: list[tuple[str, int]] = []
    for number, line in enumerate(contents.splitlines(), start=1):
        stripped = line.lstrip()
        marker = (
            "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        )
        if marker:
            if fences and fences[-1][0] == marker:
                fences.pop()
            elif not fences:
                fences.append((marker, number))
    for _, number in fences:
        errors.append(f"{path}:{number}: unclosed fenced code block")

    for match in LINK_PATTERN.finditer(contents):
        target = match.group(1).strip().strip("<>").split(maxsplit=1)[0]
        if not target or target.startswith(("#", *REMOTE_SCHEMES)):
            continue
        relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if relative and not (path.parent / relative).exists():
            line_number = contents.count("\n", 0, match.start()) + 1
            errors.append(f"{path}:{line_number}: local link does not exist: {relative}")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    errors = [error for path in markdown_files(args.paths) for error in check_file(path)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Markdown checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
