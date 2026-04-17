/**
 * IsolateX CTFd plugin — challenge instance panel
 * Injected into challenge modal pages via CTFd's plugin asset system.
 *
 * Looks for a <div id="isolatex-panel" data-challenge-id="..."> in the
 * challenge description and renders a Launch/Stop button + status display.
 */

(function () {
  "use strict";

  const POLL_INTERVAL_MS = 5000;

  function initPanel(panel) {
    const challengeId = panel.dataset.challengeId;
    if (!challengeId) return;

    panel.innerHTML = `
      <div class="isolatex-widget card card-body bg-dark text-white mt-3">
        <h6 class="mb-2">🔒 Live Instance</h6>
        <div id="ix-status-${challengeId}" class="mb-2 text-muted small">Checking...</div>
        <div id="ix-endpoint-${challengeId}" class="mb-2"></div>
        <div id="ix-ttl-${challengeId}" class="mb-2 text-warning small"></div>
        <button id="ix-btn-${challengeId}" class="btn btn-sm btn-primary" disabled>...</button>
      </div>
    `;

    refreshStatus(challengeId);
  }

  async function refreshStatus(challengeId) {
    const statusEl   = document.getElementById(`ix-status-${challengeId}`);
    const endpointEl = document.getElementById(`ix-endpoint-${challengeId}`);
    const ttlEl      = document.getElementById(`ix-ttl-${challengeId}`);
    const btn        = document.getElementById(`ix-btn-${challengeId}`);

    try {
      const resp = await fetch(`/isolatex/instance/${challengeId}`);
      const data = await resp.json();

      if (!data.status || data.status === "none") {
        statusEl.textContent = "No instance running.";
        endpointEl.innerHTML = "";
        ttlEl.textContent = "";
        btn.textContent = "Launch Instance";
        btn.disabled = false;
        btn.onclick = () => launchInstance(challengeId);
        return;
      }

      const status = data.status;
      statusEl.textContent = `Status: ${status}`;

      if (status === "running" && data.endpoint) {
        endpointEl.innerHTML = `
          Endpoint: <a href="${data.endpoint}" target="_blank" rel="noopener"
            class="text-info">${data.endpoint}</a>
        `;
        const expiresAt = new Date(data.expires_at);
        startCountdown(ttlEl, expiresAt);
        btn.textContent = "Stop Instance";
        btn.disabled = false;
        btn.onclick = () => stopInstance(challengeId);
      } else if (status === "pending") {
        statusEl.textContent = "Starting… (this may take a few seconds)";
        btn.textContent = "Starting…";
        btn.disabled = true;
        setTimeout(() => refreshStatus(challengeId), POLL_INTERVAL_MS);
      } else if (status === "error") {
        statusEl.textContent = "Instance failed to start. Contact an admin.";
        btn.textContent = "Retry";
        btn.disabled = false;
        btn.onclick = () => launchInstance(challengeId);
      } else {
        statusEl.textContent = `Instance ${status}.`;
        btn.textContent = "Launch Instance";
        btn.disabled = false;
        btn.onclick = () => launchInstance(challengeId);
      }
    } catch (err) {
      statusEl.textContent = "Error communicating with IsolateX.";
      console.error("IsolateX error:", err);
    }
  }

  async function launchInstance(challengeId) {
    const btn = document.getElementById(`ix-btn-${challengeId}`);
    const statusEl = document.getElementById(`ix-status-${challengeId}`);
    btn.disabled = true;
    btn.textContent = "Launching…";
    statusEl.textContent = "Requesting instance…";

    try {
      const resp = await fetch(`/isolatex/instance/${challengeId}`, { method: "POST" });
      if (!resp.ok) {
        const err = await resp.json();
        statusEl.textContent = `Error: ${err.error || resp.statusText}`;
        btn.disabled = false;
        btn.textContent = "Retry";
        return;
      }
      // Poll for running status
      setTimeout(() => refreshStatus(challengeId), POLL_INTERVAL_MS);
    } catch (err) {
      statusEl.textContent = "Launch request failed.";
      btn.disabled = false;
      btn.textContent = "Retry";
    }
  }

  async function stopInstance(challengeId) {
    const btn = document.getElementById(`ix-btn-${challengeId}`);
    btn.disabled = true;
    btn.textContent = "Stopping…";

    try {
      await fetch(`/isolatex/instance/${challengeId}`, { method: "DELETE" });
    } catch (err) {
      console.error("Stop failed:", err);
    }
    setTimeout(() => refreshStatus(challengeId), 1500);
  }

  function startCountdown(el, expiresAt) {
    if (el._countdownTimer) clearInterval(el._countdownTimer);
    el._countdownTimer = setInterval(() => {
      const remaining = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
      const m = Math.floor(remaining / 60);
      const s = remaining % 60;
      el.textContent = `Expires in: ${m}m ${s.toString().padStart(2, "0")}s`;
      if (remaining === 0) {
        clearInterval(el._countdownTimer);
        el.textContent = "Instance expired.";
      }
    }, 1000);
  }

  // Initialize all panels on the page
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-isolatex-challenge]").forEach(initPanel);
  });

  // CTFd opens challenges in a modal — re-scan when modal opens
  document.addEventListener("shown.bs.modal", () => {
    document.querySelectorAll("[data-isolatex-challenge]").forEach((panel) => {
      if (!panel._isolatexInit) {
        panel._isolatexInit = true;
        initPanel(panel);
      }
    });
  });
})();
