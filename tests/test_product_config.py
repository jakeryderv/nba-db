"""Single-season product defaults and guarded command boundaries."""

import subprocess
import sys
from pathlib import Path

from nba_config import DEFAULT_SEASON

PROJECT_ROOT = Path(__file__).parents[1]


def test_verified_product_default_is_2025_26() -> None:
    assert DEFAULT_SEASON == "2025-26"
    makefile = (PROJECT_ROOT / "Makefile").read_text()
    assert "SEASON ?= 2025-26" in makefile


def test_extract_and_transform_help_advertise_the_product_default() -> None:
    for script in ("etl/extract.py", "etl/transform.py"):
        result = subprocess.run(
            [sys.executable, script, "--help"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "default: 2025-26" in result.stdout


def test_direct_legacy_loader_is_disabled() -> None:
    result = subprocess.run(
        [sys.executable, "etl/load.py"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Direct loading is disabled" in result.stderr
