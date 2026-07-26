"""The advertised /docs page must work under the app's own CSP."""

import hashlib
import re
from pathlib import Path

VENDOR = Path(__file__).parents[1] / "app" / "static" / "vendor"
EXPECTED_DIGESTS = {
    "swagger-ui-bundle.js": "fcb81e2c79e7e3b76ddb9bd7fc791552045040fde05c19d3f98f9213e7f7724d",
    "swagger-ui.css": "ca238f7d7c2cf4480c1e77a9c3b9da915ab216e96ffd354e69076560c650c6de",
}


def test_vendored_assets_match_recorded_digests() -> None:
    """A silent swap of third-party code must fail the suite."""
    for name, expected in EXPECTED_DIGESTS.items():
        digest = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
        assert digest == expected, f"{name} does not match the digest recorded in vendor/README.md"


def test_docs_page_has_no_inline_script(client) -> None:
    """The inline initializer is exactly what the CSP blocks."""
    response = client.get("/docs")

    assert response.status_code == 200
    body = response.text
    assert not re.search(r"<script(?!\s+src=)", body)
    assert "<style" not in body
    assert "cdn.jsdelivr.net" not in body


def test_docs_page_loads_only_first_party_assets(client) -> None:
    response = client.get("/docs")
    body = response.text

    assert '<script src="/static/vendor/swagger-ui-bundle.js"></script>' in body
    assert '<script src="/static/vendor/swagger-init.js"></script>' in body
    assert '<link rel="stylesheet" href="/static/vendor/swagger-ui.css">' in body
    # Every referenced asset is actually served.
    for path in re.findall(r'(?:src|href)="(/static/[^"]+)"', body):
        assert client.get(path).status_code == 200, path


def test_content_security_policy_admits_no_external_scripts(client) -> None:
    response = client.get("/docs")
    policy = response.headers["content-security-policy"]

    assert "script-src 'self'" in policy
    assert "jsdelivr" not in policy
    assert "unsafe-inline" not in policy


def test_openapi_schema_is_available_to_the_docs_page(client) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "NBA Database API"
