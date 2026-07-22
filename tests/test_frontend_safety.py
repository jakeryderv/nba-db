"""Focused safety checks for the dependency-free browser UI."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).parents[1] / "app" / "templates" / "index.html"
SCRIPT = Path(__file__).parents[1] / "app" / "static" / "app.js"
CORE_SCRIPT = Path(__file__).parents[1] / "app" / "static" / "core.js"
STYLES = Path(__file__).parents[1] / "app" / "static" / "styles.css"
FAVICON = Path(__file__).parents[1] / "app" / "static" / "favicon.svg"


def test_dynamic_actions_do_not_use_inline_javascript_handlers() -> None:
    html = TEMPLATE.read_text()
    javascript = CORE_SCRIPT.read_text() + "\n" + SCRIPT.read_text()

    assert not re.search(r"<[^>]+\sonclick\s*=", html, re.IGNORECASE)
    assert 'data-action="player"' in javascript
    assert 'data-action="game"' in javascript
    assert 'data-action="team"' in javascript


def test_status_messages_are_inserted_as_text() -> None:
    javascript = CORE_SCRIPT.read_text() + "\n" + SCRIPT.read_text()

    assert "status.textContent = message" in javascript
    assert "container.replaceChildren(status)" in javascript
    assert 'innerHTML = `<div class="error">' not in javascript


def test_assets_are_external_and_compatible_with_strict_csp() -> None:
    html = TEMPLATE.read_text()

    assert '<link rel="stylesheet" href="/static/styles.css">' in html
    assert '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">' in html
    assert '<script src="/static/app.js" defer></script>' in html
    assert '<script src="/static/core.js" defer></script>' in html
    assert "Copy view link" in html
    assert "<style" not in html
    assert not re.search(r"<script(?!\s+src=)", html)
    assert not re.search(r"\sstyle\s*=", html, re.IGNORECASE)
    assert SCRIPT.exists()
    assert CORE_SCRIPT.exists()
    assert STYLES.exists()
    assert FAVICON.exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_html_escaping_and_zero_value_helpers() -> None:
    """Execute the small pure helpers without requiring a browser or DOM library."""
    javascript = CORE_SCRIPT.read_text() + "\n" + SCRIPT.read_text()

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
        ["node", "-e", "global.document = {addEventListener() {}};\n" + javascript + probe],
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
    javascript = CORE_SCRIPT.read_text() + "\n" + SCRIPT.read_text()

    for field in ("ppg", "rpg", "apg", "spg", "bpg", "games_played", "wins", "losses"):
        assert f"{field} || '-'" not in javascript


def test_single_loaded_season_is_presented_as_a_label() -> None:
    html = TEMPLATE.read_text()
    javascript = CORE_SCRIPT.read_text() + "\n" + SCRIPT.read_text()

    assert 'id="season-label"' in html
    assert 'id="season-select"' not in html
    assert "`${season} Regular Season`" in javascript


def test_detail_views_have_linkable_hash_routes() -> None:
    javascript = CORE_SCRIPT.read_text() + "\n" + SCRIPT.read_text()

    assert "window.addEventListener('hashchange', route)" in javascript
    for detail in ("team", "player", "game"):
        assert f'href="#{detail}/${{encodeURIComponent(' in javascript
    assert "#shots/${encodeURIComponent(type)}" in javascript
    assert "new URLSearchParams({game_id: gameId})" in javascript


def test_shot_chart_is_accessible_and_uses_no_third_party_script() -> None:
    html = TEMPLATE.read_text()
    javascript = CORE_SCRIPT.read_text() + "\n" + SCRIPT.read_text()

    assert 'id="shot-chart-form"' in html
    assert 'aria-live="polite"' in html
    assert '<select class="filter-select" id="shot-game">' in html
    assert 'id="shot-action-type"' in html
    assert 'id="shot-home-away"' in html
    assert 'id="shot-date-from"' in html
    assert 'id="shot-date-to"' in html
    assert 'role="img" aria-label="Half-court shot chart"' in javascript
    assert 'role="img" aria-label="Shot density heatmap"' in javascript
    assert "frequency" in javascript
    assert "fg_pct_vs_league" in javascript
    assert "https://" not in javascript
    assert "/api/shot-chart.csv?" in javascript


def test_detail_dialogs_expose_accessible_names() -> None:
    html = TEMPLATE.read_text()

    assert html.count('role="dialog"') == 3
    assert html.count('aria-modal="true"') == 3
    assert 'aria-label="Close player profile"' in html
    assert 'aria-label="Close game box score"' in html
    assert 'aria-label="Close team dashboard"' in html
