"""Tests for conservative path classification and Markdown checks."""

from pathlib import Path

from scripts.check_docs import check_file
from scripts.ci_impact import Impact, classify_paths, encode_paths


def test_empty_and_unknown_changes_fail_safe_to_full() -> None:
    assert classify_paths([]) is Impact.FULL
    assert classify_paths(["pyproject.toml"]) is Impact.FULL
    assert classify_paths(["unexpected/component.file"]) is Impact.FULL


def test_docs_only_changes_are_narrow() -> None:
    assert classify_paths(["README.md", "docs/guide.md"]) is Impact.DOCS


def test_frontend_and_docs_changes_select_frontend() -> None:
    assert classify_paths(["app/static/app.js", "README.md"]) is Impact.FRONTEND
    assert classify_paths(["app/templates/index.html"]) is Impact.FRONTEND


def test_lifecycle_and_docs_changes_select_lifecycle() -> None:
    assert classify_paths(["etl/transform.py", "docs/lifecycle.md"]) is Impact.LIFECYCLE
    assert classify_paths(["tests/test_season_lifecycle.py"]) is Impact.LIFECYCLE
    assert classify_paths(["tests/test_shot_pipeline.py"]) is Impact.LIFECYCLE


def test_mixed_components_select_full() -> None:
    assert classify_paths(["etl/load.py", "app/static/app.js"]) is Impact.FULL
    assert classify_paths(["app/main.py", "README.md"]) is Impact.FULL


def test_encoded_paths_round_trip() -> None:
    import base64
    import json

    encoded = encode_paths(["README.md", "app/static/app.js"])
    assert json.loads(base64.b64decode(encoded)) == ["README.md", "app/static/app.js"]


def test_markdown_checker_reports_hygiene_and_bad_links(tmp_path: Path) -> None:
    document = tmp_path / "README.md"
    document.write_text("[missing](nope.md)  \n```python\n")

    errors = check_file(document)

    assert any("trailing whitespace" in error for error in errors)
    assert any("unclosed fenced code block" in error for error in errors)
    assert any("local link does not exist" in error for error in errors)


def test_markdown_checker_accepts_valid_local_link(tmp_path: Path) -> None:
    (tmp_path / "guide.md").write_text("# Guide\n")
    document = tmp_path / "README.md"
    document.write_text("[guide](guide.md)\n")

    assert check_file(document) == []
