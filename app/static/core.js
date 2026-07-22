(function () {
    'use strict';

    const HTML_ESCAPES = {'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'};

    function h(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => HTML_ESCAPES[char]);
    }

    function present(value, fallback = '-') {
        return value === null || value === undefined || value === '' ? fallback : value;
    }

    function pct(value) {
        const number = Number(value);
        return value === null || value === undefined || value === '' || !Number.isFinite(number)
            ? '-'
            : `${(number * 100).toFixed(1)}%`;
    }

    function showStatus(container, kind, message) {
        const status = document.createElement('div');
        status.className = kind;
        status.textContent = message;
        status.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        container.replaceChildren(status);
    }

    function showLoading(container, subject) {
        showStatus(container, 'loading', `Loading ${subject}`);
    }

    function showError(container, subject, error) {
        showStatus(container, 'error', `Error loading ${subject}: ${error.message}`);
    }

    async function api(url) {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    }

    function trackUsage(event, view) {
        fetch('/api/telemetry', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({event, view}),
            keepalive: true
        }).catch(() => {});
    }

    globalThis.NbaCore = Object.freeze({h, present, pct, showStatus, showLoading, showError, api, trackUsage});
}());
