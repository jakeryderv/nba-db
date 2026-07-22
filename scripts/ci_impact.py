#!/usr/bin/env python3
"""Classify changed paths and drive conservative affected Dagger checks."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from collections.abc import Sequence

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / ".dagger" / "src"))

from nba_db_ci.impact import Impact, classify_paths  # noqa: E402

__all__ = ["Impact", "classify_paths"]


def changed_paths(base_ref: str) -> list[str] | None:
    """Return committed paths changed from a merge base, or None when unavailable."""
    try:
        merge_base = subprocess.run(
            ["git", "merge-base", base_ref, "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        result = subprocess.run(
            ["git", "diff", "--name-only", "-z", merge_base, "HEAD"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        return [path.decode() for path in result.stdout.split(b"\0") if path]
    except UnicodeDecodeError:
        return None


def encode_paths(paths: Sequence[str]) -> str:
    payload = json.dumps(list(paths), separators=(",", ":")).encode()
    return base64.b64encode(payload).decode()


def run_pre_push(base_ref: str) -> int:
    paths = changed_paths(base_ref)
    if paths is None:
        print(f"Could not compare with {base_ref}; running the full Dagger pipeline.")
        command = ["dagger", "call", "full", "--source=."]
    else:
        impact = classify_paths(paths)
        print(f"Pre-push impact: {impact.value} ({len(paths)} changed paths)")
        command = [
            "dagger",
            "call",
            "check-affected",
            "--source=.",
            f"--changed-paths-b64={encode_paths(paths)}",
        ]
    try:
        return subprocess.run(command, check=False).returncode
    except FileNotFoundError:
        print("ERROR: dagger is not installed or not available on PATH", file=sys.stderr)
        return 2


def write_github_output(base_ref: str) -> int:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        print("ERROR: GITHUB_OUTPUT is not set", file=sys.stderr)
        return 2
    paths = changed_paths(base_ref)
    if paths is None:
        paths = []  # Empty input deliberately fails safe to the full pipeline.
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"paths_b64={encode_paths(paths)}\n")
        output.write(f"impact={classify_paths(paths).value}\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser("classify")
    classify.add_argument("paths", nargs="*")

    encode = subparsers.add_parser("encode")
    encode.add_argument("--base-ref", required=True)

    pre_push = subparsers.add_parser("pre-push")
    pre_push.add_argument("--base-ref", default="origin/main")

    github = subparsers.add_parser("github-output")
    github.add_argument("--base-ref", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "classify":
        print(classify_paths(args.paths).value)
        return 0
    if args.command == "encode":
        paths = changed_paths(args.base_ref)
        if paths is None:
            return 2
        print(encode_paths(paths))
        return 0
    if args.command == "github-output":
        return write_github_output(args.base_ref)
    return run_pre_push(args.base_ref)


if __name__ == "__main__":
    raise SystemExit(main())
