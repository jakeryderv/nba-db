"""Dagger pipelines shared by local development and GitHub Actions."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Annotated

import dagger
from dagger import DefaultPath, check, dag, function, object_type, up

from .impact import Impact, classify_paths

PYTHON_IMAGE = "python:3.11.14-slim-bookworm"
UV_IMAGE = "ghcr.io/astral-sh/uv:0.10.4"
POSTGRES_MAJOR = "18"
POSTGRES_IMAGE = f"postgres:{POSTGRES_MAJOR}-bookworm"
WORKDIR = "/workspace"
PYTHON_PATHS = ["etl/", "app/", "db/", "scripts/", "tests/", ".dagger/src/", "nba_config.py"]
MYPY_PATHS = ["etl/", "app/", "db/", "scripts/", "nba_config.py"]


@object_type
class NbaDbCi:
    """Build, validate, test, and operate the project in reproducible containers."""

    def _dependencies(self, source: dagger.Directory) -> dagger.Container:
        uv_image = dag.container().from_(UV_IMAGE)
        manifests = (
            dag.directory()
            .with_file("pyproject.toml", source.file("pyproject.toml"))
            .with_file("uv.lock", source.file("uv.lock"))
            .with_file("README.md", source.file("README.md"))
        )
        return (
            dag.container()
            .from_(PYTHON_IMAGE)
            .with_file("/usr/local/bin/uv", uv_image.file("/uv"))
            .with_file("/usr/local/bin/uvx", uv_image.file("/uvx"))
            .with_env_variable("UV_LINK_MODE", "copy")
            .with_env_variable("UV_PROJECT_ENVIRONMENT", "/opt/venv")
            .with_mounted_cache("/root/.cache/uv", dag.cache_volume("nba-db-uv-v1"))
            .with_directory(WORKDIR, manifests)
            .with_workdir(WORKDIR)
            .with_exec(["uv", "sync", "--locked", "--no-install-project"])
        )

    def _base(self, source: dagger.Directory) -> dagger.Container:
        return self._dependencies(source).with_directory(WORKDIR, source)

    def _with_test_tools(self, container: dagger.Container) -> dagger.Container:
        postgres_tools = dag.container().from_(POSTGRES_IMAGE)
        return (
            container.with_env_variable("DEBIAN_FRONTEND", "noninteractive")
            .with_exec(
                [
                    "sh",
                    "-c",
                    "apt-get update && "
                    "apt-get install -y --no-install-recommends make nodejs postgresql-client && "
                    "rm -rf /var/lib/apt/lists/*",
                ]
            )
            .with_file(
                "/usr/local/bin/pg_dump",
                postgres_tools.file(f"/usr/lib/postgresql/{POSTGRES_MAJOR}/bin/pg_dump"),
            )
            .with_file(
                "/usr/local/bin/pg_restore",
                postgres_tools.file(f"/usr/lib/postgresql/{POSTGRES_MAJOR}/bin/pg_restore"),
            )
        )

    def _test_base(self, source: dagger.Directory) -> dagger.Container:
        return self._with_test_tools(self._dependencies(source)).with_directory(WORKDIR, source)

    def _browser_base(self, source: dagger.Directory) -> dagger.Container:
        return (
            self._with_test_tools(self._dependencies(source))
            .with_mounted_cache(
                "/root/.cache/ms-playwright", dag.cache_volume("nba-db-playwright-v1")
            )
            .with_exec(["uv", "run", "playwright", "install", "--with-deps", "chromium"])
            .with_directory(WORKDIR, source)
        )

    def _postgres(self) -> dagger.Service:
        return (
            dag.container()
            .from_(POSTGRES_IMAGE)
            .with_env_variable("POSTGRES_DB", "nba_db")
            .with_env_variable("POSTGRES_USER", "nba_user")
            .with_env_variable("POSTGRES_PASSWORD", "nba_password")
            .with_exposed_port(5432)
            .as_service()
        )

    def _with_test_database(self, container: dagger.Container) -> dagger.Container:
        return (
            container.with_service_binding("database", self._postgres())
            .with_env_variable("DATABASE_URL", "")
            .with_env_variable("DB_HOST", "database")
            .with_env_variable("DB_PORT", "5432")
            .with_env_variable("DB_USER", "nba_user")
            .with_env_variable("DB_PASSWORD", "nba_password")
            .with_env_variable("CI", "true")
        )

    @function
    @check
    async def formatting(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> str:
        """Verify that committed Python files use Ruff formatting."""
        return await (
            self._base(source)
            .with_exec(["uv", "run", "ruff", "format", "--check", *PYTHON_PATHS])
            .stdout()
        )

    @function
    @check
    async def lint(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> str:
        """Run Ruff over application, ETL, test, and Dagger code."""
        return await (
            self._base(source).with_exec(["uv", "run", "ruff", "check", *PYTHON_PATHS]).stdout()
        )

    @function
    @check
    async def typecheck(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> str:
        """Run the project's static type checks."""
        return await self._base(source).with_exec(["uv", "run", "mypy", *MYPY_PATHS]).stdout()

    @function
    @check
    async def docs(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> str:
        """Validate Markdown structure and local links."""
        return await (
            self._base(source).with_exec(["uv", "run", "python", "scripts/check_docs.py"]).stdout()
        )

    @function
    @check
    async def test(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> str:
        """Run the complete PostgreSQL-backed and browser test suite."""
        return await (
            self._with_test_database(self._browser_base(source))
            .with_exec(["uv", "run", "pytest", "tests/", "-v"])
            .stdout()
        )

    @function
    async def frontend(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> str:
        """Run focused static-asset safety and browser journeys."""
        return await (
            self._with_test_database(self._browser_base(source))
            .with_exec(
                [
                    "uv",
                    "run",
                    "pytest",
                    "tests/test_frontend_safety.py",
                    "tests/test_browser.py",
                    "-v",
                ]
            )
            .stdout()
        )

    @function
    async def lifecycle(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> str:
        """Run Python quality checks and the focused season-lifecycle tests."""
        checks = await asyncio.gather(
            self.formatting(source),
            self.lint(source),
            self.typecheck(source),
            self._with_test_database(self._test_base(source))
            .with_exec(
                [
                    "uv",
                    "run",
                    "pytest",
                    "tests/test_season_lifecycle.py",
                    "tests/test_etl_load.py",
                    "tests/test_shot_pipeline.py",
                    "-v",
                ]
            )
            .stdout(),
        )
        return "\n".join(result for result in checks if result)

    @function
    async def full(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> str:
        """Run every deterministic merge check concurrently."""
        checks = await asyncio.gather(
            self.formatting(source),
            self.lint(source),
            self.typecheck(source),
            self.docs(source),
            self.test(source),
        )
        return "\n".join(result for result in checks if result)

    @function
    async def check_affected(
        self,
        changed_paths_b64: str,
        source: Annotated[dagger.Directory, DefaultPath(".")],
    ) -> str:
        """Run conservative checks selected from a base64-encoded changed-path list."""
        try:
            payload = base64.b64decode(changed_paths_b64, validate=True).decode()
            paths = json.loads(payload)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("changed-paths-b64 must contain a base64-encoded JSON list") from exc
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ValueError("changed-paths-b64 must decode to a JSON string list")

        impact = classify_paths(paths)
        if impact is Impact.DOCS:
            await self.docs(source)
        elif impact is Impact.FRONTEND:
            await asyncio.gather(self.docs(source), self.frontend(source))
        elif impact is Impact.LIFECYCLE:
            await asyncio.gather(self.docs(source), self.lifecycle(source))
        else:
            await self.full(source)
        return f"Affected checks passed ({impact.value})"

    @function(cache="never")
    async def dependency_audit(
        self,
        audit_key: str,
        source: Annotated[dagger.Directory, DefaultPath(".")],
    ) -> str:
        """Audit locked runtime dependencies; intended for nightly/manual CI."""
        if not audit_key.strip():
            raise ValueError("audit-key is required to refresh vulnerability data")
        return await (
            self._base(source)
            .with_env_variable("DAGGER_AUDIT_KEY", audit_key)
            .with_exec(["uv", "run", "pip-audit", "--progress-spinner", "off"])
            .stdout()
        )

    @function
    @up
    def dev(self, source: Annotated[dagger.Directory, DefaultPath(".")]) -> dagger.Service:
        """Run an isolated development API and PostgreSQL service."""
        return (
            self._with_test_database(self._base(source))
            .with_exposed_port(8000)
            .as_service(
                args=[
                    "sh",
                    "-c",
                    "uv run python scripts/init_db.py && "
                    "uv run uvicorn app.main:app --host 0.0.0.0 --port 8000",
                ]
            )
        )

    def _season_builder(
        self, source: dagger.Directory, season: str, refresh_key: str
    ) -> dagger.Container:
        if not refresh_key.strip():
            raise ValueError("refresh-key is required for network-backed season builds")
        return (
            self._base(source)
            .with_env_variable("DAGGER_REFRESH_KEY", refresh_key)
            .with_exec(
                [
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "etl.season_lifecycle",
                    "validate-season",
                    "--season",
                    season,
                ]
            )
            .with_exec(["uv", "run", "python", "etl/extract.py", "--season", season, "--force"])
            .with_exec(["uv", "run", "python", "etl/transform.py", "--season", season])
            .with_exec(
                ["uv", "run", "python", "-m", "etl.official_verification", "--season", season]
            )
            .with_exec(
                [
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "etl.season_lifecycle",
                    "manifest",
                    "--season",
                    season,
                ]
            )
        )

    @function
    def season_build(
        self,
        season: str,
        refresh_key: str,
        source: Annotated[dagger.Directory, DefaultPath(".")],
    ) -> dagger.Directory:
        """Build and verify a fresh season, returning the exportable data directory."""
        return self._season_builder(source, season, refresh_key).directory(f"{WORKDIR}/data")

    @function(cache="never")
    @up
    def local_refresh(
        self,
        season: str,
        refresh_key: str,
        operation_id: str,
        source: Annotated[dagger.Directory, DefaultPath(".")],
    ) -> dagger.Service:
        """Build, load, and serve a fresh season in an isolated local environment."""
        if not operation_id.strip():
            raise ValueError("operation-id is required for the mutating refresh")
        database = self._postgres()
        refreshed = (
            self._season_builder(source, season, refresh_key)
            .with_service_binding("database", database)
            .with_env_variable("DB_HOST", "database")
            .with_env_variable("DB_PORT", "5432")
            .with_env_variable("DB_NAME", "nba_db")
            .with_env_variable("DB_USER", "nba_user")
            .with_env_variable("DB_PASSWORD", "nba_password")
            .with_env_variable("DAGGER_OPERATION_ID", operation_id)
            .with_env_variable("DAGGER_LOCAL_CONFIRMATION", "LOCAL DOCKER DATABASE")
            .with_exec(
                [
                    "uv",
                    "run",
                    "python",
                    "scripts/dagger_local_load.py",
                    "--season",
                    season,
                ]
            )
            .with_exposed_port(8000)
        )
        return refreshed.as_service(
            args=[
                "uv",
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ]
        )

    @function(cache="never")
    async def local_load(
        self,
        database: dagger.Service,
        operation_id: str,
        confirm_local_target: str,
        data: Annotated[dagger.Directory, DefaultPath("data")],
        source: Annotated[dagger.Directory, DefaultPath(".")],
        season: str,
    ) -> str:
        """Replace a caller-provided local PostgreSQL service with one manifested season."""
        if not operation_id.strip():
            raise ValueError("operation-id is required for mutating local loads")
        if confirm_local_target != "LOCAL DOCKER DATABASE":
            raise ValueError("confirm-local-target must be 'LOCAL DOCKER DATABASE'")
        loader = (
            self._base(source)
            .with_directory(f"{WORKDIR}/data", data)
            .with_service_binding("database", database)
            .with_env_variable("DB_HOST", "database")
            .with_env_variable("DB_PORT", "5432")
            .with_env_variable("DB_NAME", "nba_db")
            .with_env_variable("DB_USER", "nba_user")
            .with_env_variable("DB_PASSWORD", "nba_password")
            .with_env_variable("DAGGER_OPERATION_ID", operation_id)
            .with_env_variable("DAGGER_LOCAL_CONFIRMATION", confirm_local_target)
            .with_exec(
                [
                    "uv",
                    "run",
                    "python",
                    "scripts/dagger_local_load.py",
                    "--season",
                    season,
                ]
            )
        )
        return await loader.stdout()

    @function(cache="never")
    def promote(
        self,
        season: str,
        confirm_season: str,
        confirm_single_season: str,
        api_url: str,
        backup_name: str,
        operation_id: str,
        production_database_url: dagger.Secret,
        data: Annotated[dagger.Directory, DefaultPath("data")],
        source: Annotated[dagger.Directory, DefaultPath(".")],
    ) -> dagger.File:
        """Back up and promote one season; returns the protected pg_dump artifact."""
        if not operation_id.strip():
            raise ValueError("operation-id is required for production promotion")
        if not backup_name or "/" in backup_name or backup_name in {".", ".."}:
            raise ValueError("backup-name must be a single new filename")
        backup_path = f"/backups/{backup_name}"
        promoted = (
            self._with_test_tools(self._base(source))
            .with_directory(f"{WORKDIR}/data", data)
            .with_secret_variable("PRODUCTION_DATABASE_URL", production_database_url)
            .with_env_variable("DAGGER_OPERATION_ID", operation_id)
            .with_exec(["install", "-d", "-m", "700", "/backups"])
            .with_exec(
                [
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "etl.season_lifecycle",
                    "promote",
                    "--season",
                    season,
                    "--target",
                    "production",
                    "--confirm-season",
                    confirm_season,
                    "--confirm-single-season",
                    confirm_single_season,
                    "--backup-file",
                    backup_path,
                    "--api-url",
                    api_url,
                ]
            )
        )
        return promoted.file(backup_path)
