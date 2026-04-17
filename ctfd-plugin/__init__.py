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
from flask import Blueprint, jsonify
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_team, get_current_user
from CTFd.plugins import register_plugin_assets_directory
import httpx
import os

blueprint = Blueprint("isolatex", __name__, template_folder="templates",
                      static_folder="assets", url_prefix="/isolatex")

ORCHESTRATOR_URL = os.environ.get("ISOLATEX_URL", "http://orchestrator:8080")
API_KEY = os.environ.get("ISOLATEX_API_KEY", "")


def _headers():
    return {"x-api-key": API_KEY, "content-type": "application/json"}


def _team_id() -> str:
    team = get_current_team()
    if team:
        return f"team-{team.id}"
    user = get_current_user()
    return f"user-{user.id}"


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
@authed_only
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
@authed_only
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
@authed_only
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


def load(app):
    register_plugin_assets_directory(app, base_path="/plugins/isolatex/assets/")
    app.register_blueprint(blueprint)
    print("[IsolateX] plugin loaded")
