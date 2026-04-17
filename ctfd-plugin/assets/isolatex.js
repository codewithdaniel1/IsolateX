/**
 * IsolateX CTFd plugin — challenge instance panel
 *
 * Renders inside any challenge that has:
 *   <div data-isolatex-challenge="<challenge-id>"></div>
 *
 * Features:
 *   - Launch / Stop / Restart / Renew buttons
 *   - Live countdown timer showing time remaining
 *   - Auto-polls every 5s while instance is pending
 *   - Renew is disabled when instance is already at the 2-hour hard cap
 */
(function () {
  "use strict";

  const POLL_MS = 5000;

  // -------------------------------------------------------------------------
  // Bootstrap
  // -------------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", scanPanels);
  document.addEventListener("shown.bs.modal", scanPanels);

  function scanPanels() {
    document.querySelectorAll("[data-isolatex-challenge]").forEach((el) => {
      if (!el._ixInit) {
        el._ixInit = true;
        initPanel(el);
      }
    });
  }

  // -------------------------------------------------------------------------
  // Panel init
  // -------------------------------------------------------------------------

  function initPanel(panel) {
    const cid = panel.dataset.isolatexChallenge;
    if (!cid) return;

    panel.innerHTML = `
      <div class="card card-body bg-dark text-white mt-3 ix-panel">
        <h6 class="mb-2 ix-title">⚡ Live Instance</h6>
        <p class="ix-status text-muted small mb-1">Checking…</p>
        <p class="ix-endpoint mb-1" style="display:none"></p>
        <p class="ix-ttl text-warning small mb-2" style="display:none"></p>
        <div class="d-flex gap-2 flex-wrap ix-actions">
          <button class="btn btn-sm btn-primary  ix-btn-launch"  style="display:none">Launch</button>
          <button class="btn btn-sm btn-warning  ix-btn-restart" style="display:none">Restart</button>
          <button class="btn btn-sm btn-success  ix-btn-renew"   style="display:none">Renew Time</button>
          <button class="btn btn-sm btn-danger   ix-btn-stop"    style="display:none">Stop</button>
        </div>
        <p class="ix-msg text-danger small mt-1 mb-0" style="display:none"></p>
      </div>
    `;

    const ctx = {
      cid,
      panel,
      status:  panel.querySelector(".ix-status"),
      endpoint:panel.querySelector(".ix-endpoint"),
      ttl:     panel.querySelector(".ix-ttl"),
      msg:     panel.querySelector(".ix-msg"),
      btnLaunch:  panel.querySelector(".ix-btn-launch"),
      btnRestart: panel.querySelector(".ix-btn-restart"),
      btnRenew:   panel.querySelector(".ix-btn-renew"),
      btnStop:    panel.querySelector(".ix-btn-stop"),
      _timer: null,
    };

    ctx.btnLaunch.addEventListener("click",  () => doLaunch(ctx));
    ctx.btnRestart.addEventListener("click", () => doRestart(ctx));
    ctx.btnRenew.addEventListener("click",   () => doRenew(ctx));
    ctx.btnStop.addEventListener("click",    () => doStop(ctx));

    refresh(ctx);
  }

  // -------------------------------------------------------------------------
  // Refresh state from server
  // -------------------------------------------------------------------------

  async function refresh(ctx) {
    try {
      const data = await api(ctx.cid, "GET");
      render(ctx, data);
    } catch (e) {
      setStatus(ctx, "Error talking to IsolateX. Try refreshing.", "text-danger");
    }
  }

  function render(ctx, data) {
    clearMsg(ctx);
    stopTimer(ctx);
    hide(ctx.endpoint);
    hide(ctx.ttl);
    hideAllButtons(ctx);

    const status = data.status;

    if (!status || status === "none") {
      setStatus(ctx, "No instance running.");
      show(ctx.btnLaunch);
      return;
    }

    if (status === "pending") {
      setStatus(ctx, "Starting… (this can take a few seconds)");
      setTimeout(() => refresh(ctx), POLL_MS);
      return;
    }

    if (status === "running") {
      setStatus(ctx, "Running", "text-success");

      if (data.endpoint) {
        ctx.endpoint.innerHTML =
          `Endpoint: <a href="${esc(data.endpoint)}" target="_blank" rel="noopener"
            class="text-info">${esc(data.endpoint)}</a>`;
        show(ctx.endpoint);
      }

      if (data.expires_at) {
        startTimer(ctx, new Date(data.expires_at));
      }

      show(ctx.btnRestart);
      show(ctx.btnRenew);
      show(ctx.btnStop);
      return;
    }

    if (status === "error") {
      setStatus(ctx, "Instance failed to start. Contact an admin.", "text-danger");
      show(ctx.btnLaunch);
      return;
    }

    // destroyed / expired
    setStatus(ctx, `Instance ${status}.`);
    show(ctx.btnLaunch);
  }

  // -------------------------------------------------------------------------
  // Button actions
  // -------------------------------------------------------------------------

  async function doLaunch(ctx) {
    disableAll(ctx);
    setStatus(ctx, "Launching…");
    try {
      await api(ctx.cid, "POST");
      setTimeout(() => refresh(ctx), POLL_MS);
    } catch (e) {
      showMsg(ctx, `Launch failed: ${e.message}`);
      await refresh(ctx);
    }
  }

  async function doRestart(ctx) {
    disableAll(ctx);
    setStatus(ctx, "Restarting… (TTL will reset)");
    try {
      await apiFetch(`/isolatex/instance/${ctx.cid}/restart`, "POST");
      setTimeout(() => refresh(ctx), POLL_MS);
    } catch (e) {
      showMsg(ctx, `Restart failed: ${e.message}`);
      await refresh(ctx);
    }
  }

  async function doRenew(ctx) {
    disableAll(ctx);
    setStatus(ctx, "Renewing…");
    try {
      const data = await apiFetch(`/isolatex/instance/${ctx.cid}/renew`, "POST");
      showMsg(ctx, `Time extended by ${Math.round(data.seconds_added / 60)} minutes.`, "text-success");
      await refresh(ctx);
    } catch (e) {
      if (e.status === 409) {
        showMsg(ctx, "Already at the 2-hour maximum. Cannot extend further.");
      } else {
        showMsg(ctx, `Renew failed: ${e.message}`);
      }
      await refresh(ctx);
    }
  }

  async function doStop(ctx) {
    if (!confirm("Stop your instance? You can launch a new one anytime.")) return;
    disableAll(ctx);
    setStatus(ctx, "Stopping…");
    try {
      await api(ctx.cid, "DELETE");
    } catch (e) {
      showMsg(ctx, `Stop failed: ${e.message}`);
    }
    setTimeout(() => refresh(ctx), 1500);
  }

  // -------------------------------------------------------------------------
  // Countdown timer
  // -------------------------------------------------------------------------

  function startTimer(ctx, expiresAt) {
    stopTimer(ctx);
    show(ctx.ttl);

    function tick() {
      const remaining = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
      const h = Math.floor(remaining / 3600);
      const m = Math.floor((remaining % 3600) / 60);
      const s = remaining % 60;

      if (h > 0) {
        ctx.ttl.textContent = `Expires in: ${h}h ${m}m ${pad(s)}s`;
      } else {
        ctx.ttl.textContent = `Expires in: ${m}m ${pad(s)}s`;
      }

      if (remaining === 0) {
        stopTimer(ctx);
        ctx.ttl.textContent = "Instance expired.";
        ctx.ttl.className = "ix-ttl text-danger small mb-2";
        setTimeout(() => refresh(ctx), 2000);
      }
    }

    tick();
    ctx._timer = setInterval(tick, 1000);
  }

  function stopTimer(ctx) {
    if (ctx._timer) {
      clearInterval(ctx._timer);
      ctx._timer = null;
    }
    ctx.ttl.className = "ix-ttl text-warning small mb-2";
  }

  // -------------------------------------------------------------------------
  // UI helpers
  // -------------------------------------------------------------------------

  function setStatus(ctx, text, cls = "text-muted") {
    ctx.status.textContent = text;
    ctx.status.className = `ix-status small mb-1 ${cls}`;
  }

  function showMsg(ctx, text, cls = "text-danger") {
    ctx.msg.textContent = text;
    ctx.msg.className = `ix-msg small mt-1 mb-0 ${cls}`;
    show(ctx.msg);
  }

  function clearMsg(ctx) {
    ctx.msg.textContent = "";
    hide(ctx.msg);
  }

  function hideAllButtons(ctx) {
    [ctx.btnLaunch, ctx.btnRestart, ctx.btnRenew, ctx.btnStop].forEach(hide);
  }

  function disableAll(ctx) {
    [ctx.btnLaunch, ctx.btnRestart, ctx.btnRenew, ctx.btnStop].forEach((b) => {
      b.disabled = true;
    });
  }

  function show(el) { el.style.display = ""; }
  function hide(el) { el.style.display = "none"; }
  function pad(n)   { return String(n).padStart(2, "0"); }
  function esc(s)   { return s.replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

  // -------------------------------------------------------------------------
  // API helpers
  // -------------------------------------------------------------------------

  async function api(cid, method) {
    return apiFetch(`/isolatex/instance/${cid}`, method);
  }

  async function apiFetch(url, method) {
    const resp = await fetch(url, { method });
    let data;
    try { data = await resp.json(); } catch { data = {}; }
    if (!resp.ok) {
      const err = new Error(data.error || resp.statusText);
      err.status = resp.status;
      throw err;
    }
    return data;
  }

})();
