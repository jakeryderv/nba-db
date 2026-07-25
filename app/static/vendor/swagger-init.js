// Swagger UI initializer.
//
// FastAPI's built-in /docs page inlines this call in a <script> block, which
// the app's Content-Security-Policy (script-src 'self') blocks -- so the page
// renders blank even when the bundle itself is self-hosted. Keeping the
// initializer in its own file is what makes the docs work under the policy.
window.addEventListener("load", function () {
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    layout: "BaseLayout",
    deepLinking: true,
    showExtensions: true,
    showCommonExtensions: true,
    // Only the apis preset: SwaggerUIStandalonePreset ships in a separate
    // file that is not vendored, and the standalone top bar is not wanted.
    presets: [SwaggerUIBundle.presets.apis],
  });
});
