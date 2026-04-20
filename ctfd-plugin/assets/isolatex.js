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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initObserver, { once: true });
  } else {
    initObserver();
  }
  document.addEventListener("shown.bs.modal", () => {
    // Give Alpine.js a tick to render the challenge content before injecting
    setTimeout(() => {
      autoInjectPanel();
      scanDescriptions();
      scanPanels();
    }, 50);
  });

  function initObserver() {
    // Watch for CTFd dynamically injecting challenge content
    const observer = new MutationObserver(() => {
      scanDescriptions();
      scanPanels();
      // Auto-inject panel if we're on a challenge page
      autoInjectPanel();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: false,
    });

    scanDescriptions();
    scanPanels();
    autoInjectPanel();
  }

  function autoInjectPanel() {
    const titleEl = document.querySelector(".challenge-name");
    if (!titleEl) return;

    const cid = titleEl.textContent?.trim().toLowerCase().replace(/\s+/g, "-") || "";
    if (!cid || document.querySelector(`[data-isolatex-challenge="${cid}"]`)) return;

    // Insert after the challenge description span (CTFd core theme: .challenge-desc)
    const insertAfter = document.querySelector(".challenge-desc") ||
                        document.querySelector(".challenge-description") ||
                        titleEl;

    const panel = document.createElement("div");
    panel.setAttribute("data-isolatex-challenge", cid);
    panel.style.marginTop = "1rem";
    insertAfter.parentNode.insertBefore(panel, insertAfter.nextSibling);
  }

  function scanPanels() {
    document.querySelectorAll("[data-isolatex-challenge]").forEach((el) => {
      if (!el._ixInit) {
        el._ixInit = true;
        initPanel(el);
      }
    });
  }

  function scanDescriptions() {
    // Look for challenge description elements that contain our marker
    document.querySelectorAll("[data-description]").forEach((el) => {
      if (el._ixScanned) return;
      el._ixScanned = true;

      const desc = el.getAttribute("data-description") || el.textContent;
      const match = desc.match(/data-isolatex-challenge="([^"]+)"/);
      if (match) {
        const cid = match[1];
        // Create and insert a panel after the description
        const panel = document.createElement("div");
        panel.setAttribute("data-isolatex-challenge", cid);
        el.parentNode.insertBefore(panel, el.nextSibling);
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
        <h6 class="mb-2 ix-title">Live Instance</h6>
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
      if (e.status === 404) {
        // Challenge not registered for instancing — hide the panel entirely
        ctx.panel.style.display = "none";
      } else {
        setStatus(ctx, "Error talking to IsolateX. Try refreshing.", "text-danger");
      }
    }
  }

  function render(ctx, data) {
    clearMsg(ctx);
    stopTimer(ctx);
    setLaunchPending(ctx, false);
    hide(ctx.endpoint);
    hide(ctx.ttl);
    enableAll(ctx);
    hideAllButtons(ctx);

    const status = data.status;

    if (!status || status === "none") {
      setStatus(ctx, "No instance running.");
      show(ctx.btnLaunch);
      return;
    }

    if (status === "pending") {
      setLaunchPending(ctx, true);
      setStatus(ctx, "Starting... (this can take a few seconds)");
      show(ctx.btnLaunch);
      disableAll(ctx);
      setTimeout(() => refresh(ctx), POLL_MS);
      return;
    }

    if (status === "running") {
      setStatus(ctx, "Running", "text-success");

      if (data.endpoint) {
        if (data.endpoint.startsWith("tcp://")) {
          const parts = data.endpoint.slice(6).split(":");
          const host = parts[0], port = parts[1];
          ctx.endpoint.innerHTML =
            `Connect: <code class="text-info">nc ${esc(host)} ${esc(port)}</code>`;
        } else {
          ctx.endpoint.innerHTML =
            `Endpoint: <a href="${esc(data.endpoint)}" target="_blank" rel="noopener"
              class="text-info">${esc(data.endpoint)}</a>`;
        }
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
    show(ctx.btnLaunch);
    setLaunchPending(ctx, true);
    setStatus(ctx, "Starting... (this can take a few seconds)");
    // Force a repaint so the loading state renders before the POST starts.
    await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
    try {
      await api(ctx.cid, "POST");
    } catch (e) {
      setLaunchPending(ctx, false);
      enableAll(ctx);
      show(ctx.btnLaunch);
      showMsg(ctx, `Launch failed: ${e.message}`);
      setStatus(ctx, "No instance running.");
      return;
    }
    await refresh(ctx);
  }

  async function doRestart(ctx) {
    disableAll(ctx);
    setStatus(ctx, "Restarting…");
    try {
      await apiFetch(`/isolatex/instance/${ctx.cid}/restart`, "POST");
    } catch (e) {
      showMsg(ctx, `Restart failed: ${e.message}`);
    }
    await refresh(ctx);
  }

  async function doRenew(ctx) {
    disableAll(ctx);
    setStatus(ctx, "Renewing…");
    let persistMsg = null;
    let persistCls = "text-danger";
    try {
      const data = await apiFetch(`/isolatex/instance/${ctx.cid}/renew`, "POST");
      persistMsg = "Timer reset.";
      persistCls = "text-success";
    } catch (e) {
      persistMsg = `Renew failed: ${e.message}`;
    }
    await refresh(ctx);
    if (persistMsg) showMsg(ctx, persistMsg, persistCls);
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
    await refresh(ctx);
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

  function setLaunchPending(ctx, pending) {
    ctx.btnLaunch.textContent = pending ? "Starting..." : "Launch";
  }

  function disableAll(ctx) {
    [ctx.btnLaunch, ctx.btnRestart, ctx.btnRenew, ctx.btnStop].forEach((b) => {
      b.disabled = true;
    });
  }

  function enableAll(ctx) {
    [ctx.btnLaunch, ctx.btnRestart, ctx.btnRenew, ctx.btnStop].forEach((b) => {
      b.disabled = false;
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
    const opts = {
      method,
      credentials: "same-origin", // Include cookies
      headers: {
        "Content-Type": "application/json",
      },
    };

    // CTFd CSRF: for JSON requests it checks session nonce == CSRF-Token header
    const nonce = window.init?.csrfNonce;
    if (nonce) {
      opts.headers["CSRF-Token"] = nonce;
    } else {
      // Bypass CSRF entirely using Authorization header (no session needed)
      opts.headers["Authorization"] = "Token isolatex-bypass";
    }

    const resp = await fetch(url, opts);
    let data;
    try { data = await resp.json(); } catch { data = {}; }
    if (!resp.ok) {
      const err = new Error(data.error || `HTTP ${resp.status}: ${resp.statusText}`);
      err.status = resp.status;
      if (resp.status !== 404) console.error(`[IsolateX] API error: ${url}`, err, data);
      throw err;
    }
    return data;
  }

})();
