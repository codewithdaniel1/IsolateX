"""
IsolateX CTFd Plugin
====================
Adds per-team on-demand challenge instances to stock CTFd.

Install:
  cp -r ctfd-plugin/ <CTFd>/CTFd/plugins/isolatex/

What it does:
  - Adds a Live Instance panel to any challenge tagged with isolatex:true
  - Players can Launch, Restart, Stop, and Renew their instance
  - Shows a live countdown timer (auto-stops when TTL expires)
  - TTL resets on Restart; Renew extends up to a 2-hour hard cap

Config (environment variables or CTFd admin → Plugins → IsolateX):
  ISOLATEX_URL      URL of the IsolateX orchestrator  e.g. http://orchestrator:8080
  ISOLATEX_API_KEY  Shared secret (generate: openssl rand -hex 32)
"""
from flask import Blueprint, jsonify, send_file, render_template, request
from CTFd.utils.user import get_current_team, get_current_user
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.utils import get_config, set_config
from CTFd.plugins import register_plugin_assets_directory, register_admin_plugin_menu_bar
from CTFd.models import Challenges
import httpx
import os
from pathlib import Path

blueprint = Blueprint("isolatex", __name__, template_folder="templates",
                      static_folder="assets", url_prefix="/isolatex")

# Path to assets directory
ASSETS_DIR = Path(__file__).parent / "assets"
PLUGIN_ENV_PATH = Path(__file__).parent / ".isolatex.env"


def _plugin_file_settings() -> dict:
    settings = {}
    try:
        if not PLUGIN_ENV_PATH.exists():
            return settings
        for raw in PLUGIN_ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        pass
    return settings


def _setting(config_key: str, env_key: str, default: str = "") -> str:
    from_config = get_config(config_key)
    if from_config:
        return str(from_config).strip()
    from_file = _plugin_file_settings().get(env_key)
    if from_file:
        return from_file
    return os.environ.get(env_key, default)


def _bool_setting(config_key: str, env_key: str):
    raw = _setting(config_key, env_key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _orchestrator_url() -> str:
    return _setting("isolatex_url", "ISOLATEX_URL", "http://orchestrator:8080").rstrip("/")


def _api_key() -> str:
    return _setting("isolatex_api_key", "ISOLATEX_API_KEY", "")


def _orch(path: str) -> str:
    return f"{_orchestrator_url()}{path}"


def _headers():
    return {"x-api-key": _api_key(), "content-type": "application/json"}


def _sanitize_instance_payload(payload: dict) -> dict:
    """Never forward sensitive instance fields to the browser."""
    if not isinstance(payload, dict):
        return {}
    redacted = dict(payload)
    redacted.pop("flag", None)
    return redacted


def _runtime_capabilities() -> dict:
    """
    Runtime availability for admin UI.
    Priority: explicit plugin config/file values -> infer from registered workers.
    """
    caps = {
        "docker": {"enabled": True, "reason": ""},
        "kctf": {
            "enabled": _bool_setting("isolatex_cap_kctf_enabled", "ISOLATEX_CAP_KCTF_ENABLED"),
            "reason": _setting("isolatex_cap_kctf_reason", "ISOLATEX_CAP_KCTF_REASON", ""),
        },
        "kata-firecracker": {
            "enabled": _bool_setting(
                "isolatex_cap_kata_firecracker_enabled",
                "ISOLATEX_CAP_KATA_FIRECRACKER_ENABLED",
            ),
            "reason": _setting(
                "isolatex_cap_kata_firecracker_reason",
                "ISOLATEX_CAP_KATA_FIRECRACKER_REASON",
                "",
            ),
        },
    }

    # Fallback inference from worker runtimes when explicit capability is unset.
    try:
        workers = httpx.get(_orch("/workers"), headers=_headers(), timeout=5.0).json()
        runtimes = {w.get("runtime") for w in workers if w.get("active", True)}
    except Exception:
        runtimes = set()

    if caps["kctf"]["enabled"] is None:
        caps["kctf"]["enabled"] = "kctf" in runtimes
        if not caps["kctf"]["enabled"] and not caps["kctf"]["reason"]:
            caps["kctf"]["reason"] = (
                "kCTF is not available: no kctf worker is registered. "
                "This cannot be enabled from the IsolateX page. "
                "Use a Linux host and rerun ./setup.sh."
            )

    if caps["kata-firecracker"]["enabled"] is None:
        caps["kata-firecracker"]["enabled"] = "kata-firecracker" in runtimes
        if not caps["kata-firecracker"]["enabled"] and not caps["kata-firecracker"]["reason"]:
            caps["kata-firecracker"]["reason"] = (
                "kata-firecracker is not available: no kata-firecracker worker is registered. "
                "This cannot be enabled from the IsolateX page. "
                "Use a Linux host with KVM enabled and rerun ./setup.sh."
            )

    # Normalize reasons when enabled.
    for runtime in ("kctf", "kata-firecracker"):
        if caps[runtime]["enabled"]:
            caps[runtime]["reason"] = ""

    return caps


def _team_id() -> str:
    """Get unique identifier for current user/team.
    Priority: team (if in team mode) > user (individual mode).
    """
    team = get_current_team()
    if team:
        return f"team-{team.id}"

    user = get_current_user()
    if user:
        return f"user-{user.id}"

    raise PermissionError("authentication required")


def _get_active_instance(challenge_id: str):
    tid = _team_id()
    return httpx.get(
        _orch(f"/instances/team/{tid}/{challenge_id}"),
        headers=_headers(),
        timeout=10.0,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@blueprint.route("/instance/<challenge_id>", methods=["GET"])
@authed_only
def get_instance(challenge_id: str):
    try:
        # Check if this challenge is registered for instancing
        chal_resp = httpx.get(
            _orch(f"/challenges/{challenge_id}"),
            headers=_headers(),
            timeout=5.0,
        )
        if chal_resp.status_code == 404:
            # Not an instanced challenge — tell the JS to hide the panel
            return jsonify({"status": "not_instanced"}), 404

        resp = _get_active_instance(challenge_id)
        if resp.status_code == 404:
            return jsonify({"status": "none"}), 200
        resp.raise_for_status()
        return jsonify(_sanitize_instance_payload(resp.json()))
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>", methods=["POST"])
@authed_only
def launch_instance(challenge_id: str):
    tid = _team_id()
    try:
        resp = httpx.post(
            _orch("/instances"),
            json={"team_id": tid, "challenge_id": challenge_id},
            headers=_headers(),
            timeout=30.0,
        )
        if resp.status_code == 409:
            return get_instance(challenge_id)
        resp.raise_for_status()
        return jsonify(_sanitize_instance_payload(resp.json())), 201
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>", methods=["DELETE"])
@authed_only
def stop_instance(challenge_id: str):
    try:
        inst_resp = _get_active_instance(challenge_id)
        if inst_resp.status_code == 404:
            return jsonify({"status": "none"}), 200
        inst_resp.raise_for_status()
        instance_id = inst_resp.json()["id"]
        resp = httpx.delete(
            _orch(f"/instances/{instance_id}"),
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return jsonify({"status": "stopped"}), 200
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>/restart", methods=["POST"])
@authed_only
def restart_instance(challenge_id: str):
    """Stop and relaunch. TTL resets to the full challenge default."""
    try:
        inst_resp = _get_active_instance(challenge_id)
        if inst_resp.status_code == 404:
            return jsonify({"error": "no active instance to restart"}), 404
        inst_resp.raise_for_status()
        instance_id = inst_resp.json()["id"]
        resp = httpx.post(
            _orch(f"/instances/{instance_id}/restart"),
            headers=_headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        return jsonify(_sanitize_instance_payload(resp.json())), 200
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>/renew", methods=["POST"])
@authed_only
def renew_instance(challenge_id: str):
    """Extend the TTL. Capped at 2 hours from the current time."""
    try:
        inst_resp = _get_active_instance(challenge_id)
        if inst_resp.status_code == 404:
            return jsonify({"error": "no active instance to renew"}), 404
        inst_resp.raise_for_status()
        instance_id = inst_resp.json()["id"]
        resp = httpx.post(
            _orch(f"/instances/{instance_id}/renew"),
            headers=_headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        return jsonify(resp.json()), 200
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Admin UI
# ---------------------------------------------------------------------------

@blueprint.route("/admin")
@admins_only
def admin_page():
    return render_template("admin.html")


@blueprint.route("/admin/config", methods=["GET"])
@admins_only
def admin_get_config():
    # Fetch TTL from orchestrator (single source of truth)
    try:
        resp = httpx.get(_orch("/settings"), headers=_headers(), timeout=5.0)
        resp.raise_for_status()
        default_ttl = resp.json().get("default_ttl_seconds", 1800)
    except Exception:
        default_ttl = int(get_config("isolatex_default_ttl_seconds") or 1800)

    return jsonify({
        "isolatex_url": _orchestrator_url(),
        "isolatex_api_key_set": bool(_api_key()),
        "default_ttl_seconds": default_ttl,
        "default_cpu_count":   float(get_config("isolatex_default_cpu_count") or 1),
        "default_memory_mb":   int(get_config("isolatex_default_memory_mb") or 512),
    })


@blueprint.route("/admin/runtime-capabilities", methods=["GET"])
@admins_only
def admin_runtime_capabilities():
    return jsonify(_runtime_capabilities())


@blueprint.route("/admin/config", methods=["POST"])
@admins_only
def admin_save_config():
    data = request.get_json(force=True)
    default_ttl = data.get("default_ttl_seconds", 1800)
    cpu = data.get("default_cpu_count", 1)
    mem = data.get("default_memory_mb", 512)
    isolatex_url = (data.get("isolatex_url") or "").strip()
    isolatex_api_key = (data.get("isolatex_api_key") or "").strip()

    if isolatex_url:
        set_config("isolatex_url", isolatex_url.rstrip("/"))
    if isolatex_api_key:
        set_config("isolatex_api_key", isolatex_api_key)

    # Push TTL to orchestrator so it takes effect for new instances immediately
    try:
        httpx.patch(
            _orch("/settings"),
            json={"default_ttl_seconds": default_ttl},
            headers=_headers(),
            timeout=5.0,
        ).raise_for_status()
    except Exception as e:
        return jsonify({"error": f"Failed to update orchestrator: {e}"}), 500

    # Store CPU/memory defaults locally (no orchestrator equivalent)
    set_config("isolatex_default_ttl_seconds", default_ttl)
    set_config("isolatex_default_cpu_count", cpu)
    set_config("isolatex_default_memory_mb", mem)
    return jsonify({"status": "ok"})


@blueprint.route("/admin/ctfd-challenges", methods=["GET"])
@admins_only
def admin_list_ctfd_challenges():
    """Return only challenges registered with IsolateX, enriched with CTFd metadata."""
    try:
        ix_resp = httpx.get(_orch("/challenges"), headers=_headers(), timeout=10.0)
        ix_resp.raise_for_status()
        ix_challenges = ix_resp.json()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not ix_challenges:
        return jsonify([])

    ctfd_chals = Challenges.query.order_by(
        Challenges.category, Challenges.value, Challenges.id
    ).all()

    import re as _re

    def _strip_html(s):
        return _re.sub(r"<[^>]+>", "", s or "").strip()

    # Build a lookup from slug/name → CTFd challenge
    ctfd_by_slug = {}
    for c in ctfd_chals:
        slug = _re.sub(r"[^a-z0-9]+", "-", c.name.lower()).strip("-")
        ctfd_by_slug[slug] = c
        ctfd_by_slug[c.name.lower()] = c

    result = []
    for ix in ix_challenges:
        cid = ix["id"]
        # Find matching CTFd challenge
        ctfd = ctfd_by_slug.get(cid)
        if not ctfd:
            # fuzzy: find any CTFd slug that ix id starts with or vice versa
            for k, v in ctfd_by_slug.items():
                if k == cid or cid.startswith(k) or k.startswith(cid):
                    ctfd = v
                    break

        result.append({
            "id":          cid,
            "name":        ctfd.name        if ctfd else ix.get("name", cid),
            "category":    (ctfd.category   if ctfd else "") or "",
            "points":      ctfd.value       if ctfd else None,
            "description": _strip_html(ctfd.description) if ctfd else "",
            "runtime":     ix["runtime"],
            "image":       ix.get("image", ""),
            "port":        ix.get("port", 8080),
            "cpu_count":   ix.get("cpu_count", 1),
            "memory_mb":   ix.get("memory_mb", 512),
            "ttl_seconds": ix.get("ttl_seconds"),
        })

    result.sort(key=lambda r: (r["category"], r["points"] or 0, r["name"]))
    return jsonify(result)


@blueprint.route("/admin/challenges", methods=["GET"])
@admins_only
def admin_list_challenges():
    try:
        resp = httpx.get(_orch("/challenges"), headers=_headers(), timeout=10.0)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _detect_protocol(image: str) -> str:
    """Ask the orchestrator to detect protocol from the Docker image."""
    try:
        resp = httpx.get(
            _orch("/challenges/detect-protocol"),
            params={"image": image},
            headers=_headers(),
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json().get("protocol", "http")
    except Exception:
        pass
    return "http"


@blueprint.route("/admin/challenges/<challenge_id>", methods=["POST"])
@admins_only
def admin_register_challenge(challenge_id: str):
    """Register (or re-register) a challenge with the orchestrator."""
    data = request.get_json(force=True)
    runtime = (data.get("runtime") or "docker").strip()
    caps = _runtime_capabilities()
    if runtime in caps and not caps[runtime]["enabled"]:
        return jsonify({"error": caps[runtime]["reason"] or f"{runtime} is disabled on this host"}), 400

    # Auto-detect protocol from image if not explicitly set
    if not data.get("protocol") and data.get("image"):
        data["protocol"] = _detect_protocol(data["image"])
    try:
        resp = httpx.post(
            _orch("/challenges"),
            json=data,
            headers=_headers(),
            timeout=10.0,
        )
        if resp.status_code == 409:
            # Already registered — update instead
            upd = httpx.patch(
                _orch(f"/challenges/{challenge_id}"),
                json=data,
                headers=_headers(),
                timeout=10.0,
            )
            upd.raise_for_status()
            return jsonify(upd.json()), 200
        resp.raise_for_status()
        return jsonify(resp.json()), 201
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/admin/challenges/<challenge_id>/disable", methods=["POST"])
@admins_only
def admin_disable_challenge(challenge_id: str):
    """Remove a challenge from IsolateX (stops new instances; existing ones finish naturally)."""
    try:
        resp = httpx.delete(
            _orch(f"/challenges/{challenge_id}"),
            headers=_headers(),
            timeout=10.0,
        )
        if resp.status_code == 404:
            return jsonify({"status": "not_registered"}), 200
        resp.raise_for_status()
        return jsonify({"status": "disabled"}), 200
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/admin/challenges/<challenge_id>", methods=["PATCH"])
@admins_only
def admin_update_challenge(challenge_id: str):
    data = request.get_json(force=True)
    runtime = (data.get("runtime") or "").strip()
    if runtime:
        caps = _runtime_capabilities()
        if runtime in caps and not caps[runtime]["enabled"]:
            return jsonify({"error": caps[runtime]["reason"] or f"{runtime} is disabled on this host"}), 400

    try:
        resp = httpx.patch(
            _orch(f"/challenges/{challenge_id}"),
            json=data,
            headers=_headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/assets/<path:filename>")
def serve_assets(filename):
    """Serve static assets (JS, CSS, etc)."""
    try:
        return send_file(ASSETS_DIR / filename, mimetype="application/javascript" if filename.endswith(".js") else "text/css")
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404


def load(app):
    register_plugin_assets_directory(app, base_path="/plugins/isolatex/assets/")
    register_admin_plugin_menu_bar("IsolateX", "/isolatex/admin")
    app.register_blueprint(blueprint)

    import time as _time
    _JS_VER = str(int(_time.time()))

    # Inject script into every HTML response
    @app.after_request
    def inject_isolatex_script(response):
        if response.content_type and "text/html" in response.content_type:
            data = response.get_data(as_text=True)
            script = f'<script src="/isolatex/assets/isolatex.js?v={_JS_VER}" async></script>'
            # Insert before closing body tag
            if '</body>' in data:
                data = data.replace('</body>', f'{script}</body>')
                response.set_data(data)
        return response

    print("[IsolateX] plugin loaded")
