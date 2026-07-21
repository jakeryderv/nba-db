"""End-to-end browser coverage for the primary exploration paths."""

import os
import re
import shutil
import socket
import threading
import time
from collections.abc import Generator

import httpx
import pytest
import uvicorn
from playwright.sync_api import Browser, Page, Playwright, expect, sync_playwright

from tests.conftest import LAKERS, LEBRON


@pytest.fixture(scope="module")
def live_url(client) -> Generator[str, None, None]:
    """Serve the seeded test app on an unused loopback port."""
    from app.main import app

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
            ws="none",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("Browser test server did not become ready")

    yield url

    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive(), "Browser test server did not stop"


@pytest.fixture(scope="module")
def browser() -> Generator[Browser, None, None]:
    with sync_playwright() as playwright:
        launched = _launch_browser(playwright)
        yield launched
        launched.close()


def _launch_browser(playwright: Playwright) -> Browser:
    """Use system Chrome when available, or a locally installed Playwright browser."""
    chrome = (
        shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
        or shutil.which("chromium")
    )
    if chrome:
        return playwright.chromium.launch(headless=True, executable_path=chrome)

    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        if os.environ.get("CI"):
            pytest.fail(f"CI runner has no usable Chromium browser: {exc}")
        pytest.skip(f"No Chromium browser is installed: {exc}")


@pytest.fixture
def page(browser: Browser) -> Generator[Page, None, None]:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    context.close()
    assert errors == []


def test_standings_open_team_dashboard(page: Page, live_url: str) -> None:
    page.goto(live_url)

    expect(page.locator("#season-label")).to_have_text("2024-25 Regular Season")
    page.get_by_role("link", name="Los Angeles Lakers", exact=True).click()

    expect(page).to_have_url(re.compile(rf"#team/{LAKERS}$"))
    dialog = page.get_by_role("dialog", name="Los Angeles Lakers")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("10-0", exact=True).first).to_be_visible()
    expect(dialog.get_by_role("link", name="LeBron James")).to_be_visible()
    expect(dialog.get_by_role("button", name="Close team dashboard")).to_be_focused()

    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(page).to_have_url(re.compile(r"#standings$"))


def test_leader_opens_player_profile_and_game_log(page: Page, live_url: str) -> None:
    page.goto(f"{live_url}/#leaders")
    page.get_by_role("link", name="LeBron James", exact=True).click()

    expect(page).to_have_url(re.compile(rf"#player/{LEBRON}$"))
    dialog = page.get_by_role("dialog", name="LeBron James")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("LAL", exact=True)).to_be_visible()
    expect(dialog.get_by_role("heading", name="Recent Games")).to_be_visible()
    expect(dialog.get_by_role("cell", name="vs BOS", exact=True).first).to_be_visible()


def test_game_card_opens_full_box_score(page: Page, live_url: str) -> None:
    page.goto(f"{live_url}/#games")
    page.locator(".game-card").last.click()

    expect(page).to_have_url(re.compile(r"#game/00224000\d{2}$"))
    dialog = page.get_by_role("dialog", name=re.compile("Boston Celtics @ Los Angeles Lakers"))
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("link", name="LeBron James")).to_be_visible()
    expect(dialog.get_by_role("link", name="Jayson Tatum")).to_be_visible()


def test_team_dashboard_collapses_to_one_column_on_mobile(page: Page, live_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_url}/#team/{LAKERS}")

    dialog = page.get_by_role("dialog", name="Los Angeles Lakers")
    expect(dialog).to_be_visible()
    box = dialog.bounding_box()
    assert box is not None and box["width"] <= 390
    columns = dialog.locator(".detail-columns").evaluate(
        "element => getComputedStyle(element).gridTemplateColumns"
    )
    assert len(columns.split()) == 1
