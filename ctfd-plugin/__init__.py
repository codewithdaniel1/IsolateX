"""
IsolateX CTFd Plugin
====================
Adds per-team on-demand challenge instances to stock CTFd.

Install:
  cp -r ctfd-plugin/ <CTFd>/CTFd/plugins/isolatex/

The plugin:
- Adds a "Launch Instance" / "Stop Instance" button to challenge pages
  for any challenge tagged with isolatex:true
- Calls the IsolateX orchestrator API on behalf of the authenticated team
- Shows the team their unique endpoint and TTL countdown
- Polls instance status every 5 seconds until running

Config (set in CTFd admin panel → Plugins → IsolateX):
  ISOLATEX_URL      URL of the orchestrator  e.g. http://orchestrator:8080
  ISOLATEX_API_KEY  Shared secret            (generate with: openssl rand -hex 32)
"""
from flask import Blueprint, jsonify, request, session
from CTFd.models import db, Challenges
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_team, get_current_user
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
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
            # Already running — fetch and return existing
            return get_instance(challenge_id)
        resp.raise_for_status()
        return jsonify(resp.json()), 201
    except httpx.HTTPStatusError as e:
        return jsonify({"error": e.response.text}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<challenge_id>", methods=["GET"])
@authed_only
def get_instance(challenge_id: str):
    tid = _team_id()
    try:
        resp = httpx.get(
            f"{ORCHESTRATOR_URL}/instances/team/{tid}/{challenge_id}",
            headers=_headers(),
            timeout=10.0,
        )
        if resp.status_code == 404:
            return jsonify({"status": "none"}), 200
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint.route("/instance/<instance_id>/stop", methods=["DELETE"])
@authed_only
def stop_instance(instance_id: str):
    try:
        resp = httpx.delete(
            f"{ORCHESTRATOR_URL}/instances/{instance_id}",
            headers=_headers(),
            timeout=15.0,
        )
        return jsonify({"status": "stopped"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def load(app):
    register_plugin_assets_directory(app, base_path="/plugins/isolatex/assets/")
    app.register_blueprint(blueprint)
    print("[IsolateX] plugin loaded")
