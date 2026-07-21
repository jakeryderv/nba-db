"""Focused safety checks for the dependency-free browser UI."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).parents[1] / "app" / "templates" / "index.html"


def test_dynamic_actions_do_not_use_inline_javascript_handlers() -> None:
    html = TEMPLATE.read_text()

    assert not re.search(r"<[^>]+\sonclick\s*=", html, re.IGNORECASE)
    assert 'data-action="player"' in html
    assert 'data-action="game"' in html
    assert 'data-action="team"' in html


def test_status_messages_are_inserted_as_text() -> None:
    html = TEMPLATE.read_text()

    assert "status.textContent = message" in html
    assert "container.replaceChildren(status)" in html
    assert 'innerHTML = `<div class="error">' not in html


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_html_escaping_and_zero_value_helpers() -> None:
    """Execute the small pure helpers without requiring a browser or DOM library."""
    html = TEMPLATE.read_text()
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    assert len(scripts) == 1

    probe = """
const values = {
    escaped: h(`<img src=x onerror=\"alert('x')\">&`),
    zero: present(0),
    zeroPercent: pct(0),
    missing: present(null)
};
process.stdout.write(JSON.stringify(values));
"""
    result = subprocess.run(
        ["node", "-e", "global.document = {addEventListener() {}};\n" + scripts[0] + probe],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert json.loads(result.stdout) == {
        "escaped": "&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;",
        "zero": 0,
        "zeroPercent": "0.0%",
        "missing": "-",
    }


def test_zero_values_are_not_coalesced_to_missing_markers() -> None:
    html = TEMPLATE.read_text()

    for field in ("ppg", "rpg", "apg", "spg", "bpg", "games_played", "wins", "losses"):
        assert f"{field} || '-'" not in html


def test_single_loaded_season_is_presented_as_a_label() -> None:
    html = TEMPLATE.read_text()

    assert 'id="season-label"' in html
    assert 'id="season-select"' not in html
    assert "`${season} Regular Season`" in html


def test_detail_views_have_linkable_hash_routes() -> None:
    html = TEMPLATE.read_text()

    assert "window.addEventListener('hashchange', route)" in html
    for detail in ("team", "player", "game"):
        assert f'href="#{detail}/${{encodeURIComponent(' in html


def test_detail_dialogs_expose_accessible_names() -> None:
    html = TEMPLATE.read_text()

    assert html.count('role="dialog"') == 3
    assert html.count('aria-modal="true"') == 3
    assert 'aria-label="Close player profile"' in html
    assert 'aria-label="Close game box score"' in html
    assert 'aria-label="Close team dashboard"' in html
