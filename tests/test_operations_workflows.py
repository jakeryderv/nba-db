"""Static contracts for production maintenance and release-observer workflows."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_maintenance_workflow_schedules_backups_retention_and_restore_drills() -> None:
    workflow = (ROOT / ".github/workflows/maintenance.yml").read_text()

    assert 'cron: "13 8 * * *"' in workflow
    assert 'cron: "43 9 1 * *"' in workflow
    assert "postgres:18-bookworm" in workflow
    assert "--retention-days 30" in workflow
    assert "--minimum-copies 7" in workflow
    assert "restore-backup" in workflow
    assert "production-alert" in workflow


def test_release_observer_requires_ci_revision_and_live_contract() -> None:
    workflow = (ROOT / ".github/workflows/release-observer.yml").read_text()

    assert "workflow_run:" in workflow
    assert "check_release.py" in workflow
    assert "github.event.workflow_run.head_sha" in workflow
    assert "check_live.py" in workflow
    assert "issues: write" in workflow
    assert "Production release requires attention" in workflow
