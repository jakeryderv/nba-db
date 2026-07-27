"""Static contracts for production maintenance and release-observer workflows."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


RECONCILE_ACTION = ROOT / ".github/actions/reconcile-alert/action.yml"


def test_maintenance_workflow_schedules_backups_retention_and_restore_drills() -> None:
    workflow = (ROOT / ".github/workflows/maintenance.yml").read_text()

    assert 'cron: "13 8 * * *"' in workflow
    assert 'cron: "43 9 1 * *"' in workflow
    assert "postgres:18-bookworm" in workflow
    assert "--retention-days 30" in workflow
    assert "--minimum-copies 7" in workflow
    assert "restore-backup" in workflow
    # Alerting moved into the shared action; the label lives there now.
    assert "./.github/actions/reconcile-alert" in workflow
    assert "production-alert" in RECONCILE_ACTION.read_text()


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
    assert "steps.backup.outcome == 'success'" in workflow
    assert "steps.restore.outcome == 'success'" in workflow
    assert "steps.download.outcome == 'success'" in workflow


def test_alert_titles_are_matched_exactly_not_searched() -> None:
    """GitHub search ANDs word tokens, so a superset title matches a subset's query.

    "Production backup freshness check failed" contains every word of
    "Production backup failed", so a search-based lookup would let the backup
    job's recovery close the freshness alert. Every reconciler must compare
    titles literally.
    """
    reconcilers = [
        RECONCILE_ACTION,
        ROOT / ".github/workflows/release-observer.yml",
    ]
    for path in reconcilers:
        text = path.read_text()
        # Comments name the rejected approach, so judge the executable lines only.
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert "in:title" not in code, f"{path} still resolves alerts by search"
        assert "--search" not in code, f"{path} still resolves alerts by search"
        assert "select(.title == env.ALERT_TITLE)" in code


def test_alerting_steps_can_reach_the_repository_without_a_checkout() -> None:
    """gh cannot infer the repository with no checkout.

    The observer's checkout is gated on CI success, so its alert steps ran
    without repo context on exactly the failures they exist to report.
    """
    observer = (ROOT / ".github/workflows/release-observer.yml").read_text()

    assert observer.count("GH_REPO: ${{ github.repository }}") >= 2
    # Maintenance delegates to the shared action, which sets it for every caller.
    assert "GH_REPO: ${{ github.repository }}" in RECONCILE_ACTION.read_text()


def test_release_observer_alert_names_its_recovery() -> None:
    """An unserved revision is recoverable in one command; the alert must carry it.

    Railway intermittently marks a main deployment SKIPPED and serves the previous
    revision with no error anywhere (#64). The observer is the only detection, so
    leaving the operator to rediscover `railway redeploy` is the slow part of the
    recovery, not the diagnosis.
    """
    observer = (ROOT / ".github/workflows/release-observer.yml").read_text()

    assert "railway redeploy" in observer
    assert "--from-source" in observer
    # Empty by default: redeploying does not fix a failed product contract, so the
    # guidance attaches to the unserved-revision branch alone rather than to every
    # unhealthy observation.
    assert 'recovery=""' in observer


def test_release_observer_does_not_depend_on_the_repo_local_action() -> None:
    """Its checkout is conditional, so a repo-local action would silence it.

    The observer's alert must file when CI failed -- which is exactly when its
    checkout is skipped. Routing it through .github/actions/ would reintroduce
    the bug the GH_REPO fix closed, so its duplication is deliberate.
    """
    observer = (ROOT / ".github/workflows/release-observer.yml").read_text()

    assert "./.github/actions/reconcile-alert" not in observer


def test_production_watch_covers_liveness_and_freshness_separately() -> None:
    workflow = (ROOT / ".github/workflows/production-watch.yml").read_text()

    assert 'cron: "*/10 * * * *"' in workflow
    assert 'cron: "0 14 * * *"' in workflow
    # Distinct titles, so neither closes the other's alert nor maintenance's.
    assert "Production liveness check failed" in workflow
    assert "Production backup freshness check failed" in workflow
    assert "check_backup_freshness.py" in workflow


def test_liveness_probe_cannot_be_satisfied_by_a_cache() -> None:
    """A cached response outlives the instance that produced it.

    Answering the probe from cache asserts that production was healthy when the
    response was stored, which is the one claim the check exists to avoid.
    """
    workflow = (ROOT / ".github/workflows/production-watch.yml").read_text()

    assert "Cache-Control: no-cache" in workflow
    assert "Pragma: no-cache" in workflow
    assert "/ready" in workflow


def test_restore_drill_compares_the_manifest_and_records_the_proven_copy() -> None:
    workflow = (ROOT / ".github/workflows/maintenance.yml").read_text()

    assert "--manifest-sha256=${{ steps.download.outputs.manifest }}" in workflow
    assert "record_proven_backup.py" in workflow
    # A drill that passes but fails to record its proven copy leaves retention
    # unprotected, so it must not report success.
    assert "steps.record.outcome == 'success'" in workflow


def test_a_cancelled_ci_run_is_not_a_broken_release() -> None:
    observer = (ROOT / ".github/workflows/release-observer.yml").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()

    assert "github.event.workflow_run.conclusion != 'cancelled'" in observer
    # And main runs should not be cancelled in the first place: Railway deploys
    # that commit regardless, so a cancelled run leaves it unverified.
    assert "cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}" in ci
