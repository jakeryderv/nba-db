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


def test_maintenance_alerts_are_keyed_per_operation() -> None:
    """A successful backup must not close a failed restore drill's alert.

    The two schedules run different operations, so one shared issue title meant
    either operation's success cleared the other's alert — and the restore
    drill's next signal is a month away.
    """
    workflow = (ROOT / ".github/workflows/maintenance.yml").read_text()

    assert "Production backup failed" in workflow
    assert "Production restore drill failed" in workflow
    # Reconciliation is driven by which operation ran and how it ended, not by
    # whether the job as a whole succeeded.
    assert "BACKUP_OUTCOME: ${{ steps.backup.outcome }}" in workflow
    assert "RESTORE_OUTCOME: ${{ steps.restore.outcome }}" in workflow
    assert "DOWNLOAD_OUTCOME: ${{ steps.download.outcome }}" in workflow


def test_alerting_steps_can_reach_the_repository_without_a_checkout() -> None:
    """gh cannot infer the repository with no checkout.

    The observer's checkout is gated on CI success, so its alert steps ran
    without repo context on exactly the failures they exist to report.
    """
    observer = (ROOT / ".github/workflows/release-observer.yml").read_text()
    maintenance = (ROOT / ".github/workflows/maintenance.yml").read_text()

    assert observer.count("GH_REPO: ${{ github.repository }}") >= 2
    assert "GH_REPO: ${{ github.repository }}" in maintenance


def test_a_cancelled_ci_run_is_not_a_broken_release() -> None:
    observer = (ROOT / ".github/workflows/release-observer.yml").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()

    assert "github.event.workflow_run.conclusion != 'cancelled'" in observer
    # And main runs should not be cancelled in the first place: Railway deploys
    # that commit regardless, so a cancelled run leaves it unverified.
    assert "cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}" in ci
