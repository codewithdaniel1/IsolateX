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
        resp = _get_active_instance(challenge_id)
        if resp.status_code == 404:
            return jsonify({"status": "none"}), 200
        resp.raise_for_status()
        return jsonify(resp.json())
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
    return jsonify({
        "default_ttl_seconds": int(get_config("isolatex_default_ttl_seconds") or 1800),
        "max_ttl_seconds":     int(get_config("isolatex_max_ttl_seconds") or 7200),
        "default_cpu_count":   float(get_config("isolatex_default_cpu_count") or 1),
        "default_memory_mb":   int(get_config("isolatex_default_memory_mb") or 512),
    })


@blueprint.route("/admin/config", methods=["POST"])
@admins_only
@bypass_csrf_protection
def admin_save_config():
    data = request.get_json(force=True)
    set_config("isolatex_default_ttl_seconds", data.get("default_ttl_seconds", 1800))
    set_config("isolatex_max_ttl_seconds",     data.get("max_ttl_seconds", 7200))
    set_config("isolatex_default_cpu_count",   data.get("default_cpu_count", 1))
    set_config("isolatex_default_memory_mb",   data.get("default_memory_mb", 512))
    # Push defaults to orchestrator env is not needed — orchestrator reads its own env.
    # Per-challenge overrides are the canonical way to override per-challenge.
    return jsonify({"status": "ok"})


@blueprint.route("/admin/challenges", methods=["GET"])
@admins_only
def admin_list_challenges():
    try:
        resp = httpx.get(f"{ORCHESTRATOR_URL}/challenges", headers=_headers(), timeout=10.0)
        resp.raise_for_status()
        return jsonify(resp.json())
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

    # Inject script into every HTML response
    @app.after_request
    def inject_isolatex_script(response):
        if response.content_type and "text/html" in response.content_type:
            data = response.get_data(as_text=True)
            script = '<script src="/isolatex/assets/isolatex.js" async></script>'
            # Insert before closing body tag
            if '</body>' in data:
                data = data.replace('</body>', f'{script}</body>')
                response.set_data(data)
        return response

    print("[IsolateX] plugin loaded")
