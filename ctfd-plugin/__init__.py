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
from CTFd.utils.decorators import admins_only
from CTFd.utils import get_config, set_config
from CTFd.plugins import register_plugin_assets_directory, bypass_csrf_protection, register_admin_plugin_menu_bar
from CTFd.models import Challenges
import httpx
import os
from pathlib import Path

blueprint = Blueprint("isolatex", __name__, template_folder="templates",
                      static_folder="assets", url_prefix="/isolatex")

# Path to assets directory
ASSETS_DIR = Path(__file__).parent / "assets"

ORCHESTRATOR_URL = os.environ.get("ISOLATEX_URL", "http://orchestrator:8080")
API_KEY = os.environ.get("ISOLATEX_API_KEY", "")


def _headers():
    return {"x-api-key": API_KEY, "content-type": "application/json"}


def _team_id() -> str:
    """Get unique identifier for current user/team.
    Priority: team (if in team mode) > user (individual) > admin (if not logged in)
    """
    team = get_current_team()
    if team:
        return f"team-{team.id}"

    user = get_current_user()
    if user:
        return f"user-{user.id}"

    # Fallback for unauthenticated access (admin testing)
    return "admin-default"


def _get_active_instance(challenge_id: str):
    tid = _team_id()
    return httpx.get(
        f"{ORCHESTRATOR_URL}/instances/team/{tid}/{challenge_id}",
        headers=_headers(),
        timeout=10.0,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@blueprint.route("/instance/<challenge_id>", methods=["GET"])
def get_instance(challenge_id: str):
    try:
        # Check if this challenge is registered for instancing
        chal_resp = httpx.get(
            f"{ORCHESTRATOR_URL}/challenges/{challenge_id}",
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
        return jsonify(resp.json())
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>", methods=["POST"])
@bypass_csrf_protection
def launch_instance(challenge_id: str):
    tid = _team_id()
    try:
        resp = httpx.post(
            f"{ORCHESTRATOR_URL}/instances",
            json={"team_id": tid, "challenge_id": challenge_id},
            headers=_headers(),
            timeout=30.0,
        )
        if resp.status_code == 409:
            return get_instance(challenge_id)
        resp.raise_for_status()
        return jsonify(resp.json()), 201
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>", methods=["DELETE"])
@bypass_csrf_protection
def stop_instance(challenge_id: str):
    try:
        inst_resp = _get_active_instance(challenge_id)
        if inst_resp.status_code == 404:
            return jsonify({"status": "none"}), 200
        inst_resp.raise_for_status()
        instance_id = inst_resp.json()["id"]
        resp = httpx.delete(
            f"{ORCHESTRATOR_URL}/instances/{instance_id}",
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return jsonify({"status": "stopped"}), 200
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>/restart", methods=["POST"])
@bypass_csrf_protection
def restart_instance(challenge_id: str):
    """Stop and relaunch. TTL resets to the full challenge default."""
    try:
        inst_resp = _get_active_instance(challenge_id)
        if inst_resp.status_code == 404:
            return jsonify({"error": "no active instance to restart"}), 404
        inst_resp.raise_for_status()
        instance_id = inst_resp.json()["id"]
        resp = httpx.post(
            f"{ORCHESTRATOR_URL}/instances/{instance_id}/restart",
            headers=_headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        return jsonify(resp.json()), 200
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>/renew", methods=["POST"])
@bypass_csrf_protection
def renew_instance(challenge_id: str):
    """Extend the TTL. Capped at 2 hours from the current time."""
    try:
        inst_resp = _get_active_instance(challenge_id)
        if inst_resp.status_code == 404:
            return jsonify({"error": "no active instance to renew"}), 404
        inst_resp.raise_for_status()
        instance_id = inst_resp.json()["id"]
        resp = httpx.post(
            f"{ORCHESTRATOR_URL}/instances/{instance_id}/renew",
            headers=_headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        return jsonify(resp.json()), 200
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
        resp = httpx.get(f"{ORCHESTRATOR_URL}/settings", headers=_headers(), timeout=5.0)
        resp.raise_for_status()
        default_ttl = resp.json().get("default_ttl_seconds", 1800)
    except Exception:
        default_ttl = int(get_config("isolatex_default_ttl_seconds") or 1800)

    return jsonify({
        "default_ttl_seconds": default_ttl,
        "default_cpu_count":   float(get_config("isolatex_default_cpu_count") or 1),
        "default_memory_mb":   int(get_config("isolatex_default_memory_mb") or 512),
    })


@blueprint.route("/admin/config", methods=["POST"])
@admins_only
@bypass_csrf_protection
def admin_save_config():
    data = request.get_json(force=True)
    default_ttl = data.get("default_ttl_seconds", 1800)
    cpu = data.get("default_cpu_count", 1)
    mem = data.get("default_memory_mb", 512)

    # Push TTL to orchestrator so it takes effect for new instances immediately
    try:
        httpx.patch(
            f"{ORCHESTRATOR_URL}/settings",
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
    """Return all CTFd challenges with their IsolateX registration status merged in."""
    try:
        # Fetch IsolateX-registered challenges
        ix_resp = httpx.get(f"{ORCHESTRATOR_URL}/challenges", headers=_headers(), timeout=10.0)
        ix_resp.raise_for_status()
        ix_by_id = {c["id"]: c for c in ix_resp.json()}
    except Exception:
        ix_by_id = {}

    ctfd_chals = Challenges.query.order_by(
        Challenges.category, Challenges.value, Challenges.id
    ).all()

    import re as _re

    def _strip_html(s):
        return _re.sub(r"<[^>]+>", "", s or "").strip()

    result = []
    for c in ctfd_chals:
        slug = c.name.lower().replace(" ", "-")
        # Match against slug, exact name, or any registered id that starts with the slug
        ix = ix_by_id.get(slug) or ix_by_id.get(c.name.lower())
        if not ix:
            # fallback: find any ix entry whose id the slug starts with or vice versa
            for k, v in ix_by_id.items():
                if k == slug or slug.startswith(k) or k.startswith(slug):
                    ix = v
                    break
        result.append({
            "ctfd_id":     c.id,
            "id":          ix["id"] if ix else slug,
            "name":        c.name,
            "category":    c.category or "",
            "points":      c.value,
            "description": _strip_html(c.description),
            "enabled":     ix is not None,
            "runtime":     ix["runtime"]    if ix else "docker",
            "image":       ix["image"]      if ix else "",
            "port":        ix["port"]       if ix else 8080,
            "cpu_count":   ix["cpu_count"]  if ix else 1,
            "memory_mb":   ix["memory_mb"]  if ix else 512,
            "ttl_seconds": ix["ttl_seconds"] if ix else None,
        })
    return jsonify(result)


@blueprint.route("/admin/challenges", methods=["GET"])
@admins_only
def admin_list_challenges():
    try:
        resp = httpx.get(f"{ORCHESTRATOR_URL}/challenges", headers=_headers(), timeout=10.0)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/admin/challenges/<challenge_id>", methods=["POST"])
@admins_only
@bypass_csrf_protection
def admin_register_challenge(challenge_id: str):
    """Register (or re-register) a challenge with the orchestrator."""
    data = request.get_json(force=True)
    try:
        resp = httpx.post(
            f"{ORCHESTRATOR_URL}/challenges",
            json=data,
            headers=_headers(),
            timeout=10.0,
        )
        if resp.status_code == 409:
            # Already registered — update instead
            upd = httpx.patch(
                f"{ORCHESTRATOR_URL}/challenges/{challenge_id}",
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
@bypass_csrf_protection
def admin_disable_challenge(challenge_id: str):
    """Remove a challenge from IsolateX (stops new instances; existing ones finish naturally)."""
    try:
        resp = httpx.delete(
            f"{ORCHESTRATOR_URL}/challenges/{challenge_id}",
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
@bypass_csrf_protection
def admin_update_challenge(challenge_id: str):
    data = request.get_json(force=True)
    try:
        resp = httpx.patch(
            f"{ORCHESTRATOR_URL}/challenges/{challenge_id}",
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
