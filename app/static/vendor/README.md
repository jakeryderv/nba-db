# Vendored third-party assets

Swagger UI, self-hosted so the interactive docs at `/docs` load under this
app's Content-Security-Policy. FastAPI's defaults fetch these from
`cdn.jsdelivr.net`, which `script-src 'self'` blocks.

| File | Version | Source | SHA-256 |
|------|---------|--------|---------|
| `swagger-ui-bundle.js` | 5.32.11 | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.11/swagger-ui-bundle.js` | `fcb81e2c79e7e3b76ddb9bd7fc791552045040fde05c19d3f98f9213e7f7724d` |
| `swagger-ui.css` | 5.32.11 | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.11/swagger-ui.css` | `ca238f7d7c2cf4480c1e77a9c3b9da915ab216e96ffd354e69076560c650c6de` |

`swagger-init.js` is ours, not vendored. It exists because FastAPI inlines the
`SwaggerUIBundle` call in a `<script>` block that the CSP blocks; moving it to
a file is what makes self-hosting sufficient.

## Refreshing

FastAPI's default URLs track `swagger-ui-dist@5`. When upgrading FastAPI, check
whether its expected major version moved, then:

```bash
V=<version>
curl -sSfL "https://cdn.jsdelivr.net/npm/swagger-ui-dist@${V}/swagger-ui-bundle.js" \
  -o app/static/vendor/swagger-ui-bundle.js
curl -sSfL "https://cdn.jsdelivr.net/npm/swagger-ui-dist@${V}/swagger-ui.css" \
  -o app/static/vendor/swagger-ui.css
sha256sum app/static/vendor/swagger-ui-bundle.js app/static/vendor/swagger-ui.css
```

Update the version and digests in the table above. `tests/test_docs_page.py`
asserts the digests still match, so a silent swap fails the suite.
