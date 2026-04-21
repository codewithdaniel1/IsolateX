#!/usr/bin/env python3
"""
Generic CTFd + IsolateX importer for any challenge set.

Features:
- Imports CTFd challenges from challenge.json files (skips existing by name)
- Optionally registers instanced challenges with IsolateX orchestrator via
  challenge.json "isolatex" metadata
- Optionally syncs downloadable files through upload-challenge-files.py

Usage:
  python3 scripts/import-challenges.py [challenge-root]

Environment:
  CTFD_URL            default: http://127.0.0.1:8000
  CTFD_USER           default: admin
  CTFD_PASS           default: admin
  ORCHESTRATOR_URL    default: http://localhost:8080
  API_KEY             IsolateX API key (or from repo .env)
  SKIP_FILE_UPLOAD    1 to skip file sync
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHALLENGE_ROOT = (ROOT / "challenges").resolve()

CTFD_URL = os.environ.get("CTFD_URL", "http://127.0.0.1:8000").rstrip("/")
CTFD_USER = os.environ.get("CTFD_USER", "admin")
CTFD_PASS = os.environ.get("CTFD_PASS", "admin")
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8080").rstrip("/")


@dataclass
class LocalChallenge:
    name: str
    category: str
    description: str
    value: int
    slug: str
    isolatex: Optional[dict[str, Any]]


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def load_api_key() -> str:
    from_env = os.environ.get("API_KEY", "").strip()
    if from_env:
        return from_env

    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def login_ctfd() -> requests.Session:
    session = requests.Session()
    page = session.get(f"{CTFD_URL}/login", timeout=15)
    page.raise_for_status()

    nonce = re.search(r'name="nonce".*?value="([^"]+)"', page.text)
    if not nonce:
        nonce = re.search(r'nonce.*?value="([^"]+)"', page.text)

    resp = session.post(
        f"{CTFD_URL}/login",
        data={
            "name": CTFD_USER,
            "password": CTFD_PASS,
            "nonce": nonce.group(1) if nonce else "",
        },
        timeout=15,
        allow_redirects=True,
    )
    resp.raise_for_status()
    if resp.url.rstrip("/").endswith("/login") or "incorrect" in resp.text.lower():
        raise RuntimeError(
            "CTFd login failed. Set CTFD_USER and CTFD_PASS to an admin account."
        )
    return session


def parse_isolatex_config(data: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
    raw = data.get("isolatex")
    if raw is None:
        return None

    if isinstance(raw, bool):
        if not raw:
            return None
        cfg: dict[str, Any] = {}
    elif isinstance(raw, dict):
        if raw.get("enabled") is False:
            return None
        cfg = dict(raw)
    else:
        print(f"  WARN: invalid isolatex config type for '{name}', skipping IsolateX registration")
        return None

    challenge_id = str(
        cfg.get("id")
        or data.get("id")
        or slugify(name)
    ).strip()
    runtime = str(cfg.get("runtime") or data.get("runtime") or "docker").strip()
    image = str(cfg.get("image") or data.get("image") or data.get("docker_image") or "").strip()
    port = int(cfg.get("port") or data.get("internal_port") or data.get("port") or 80)
    cpu_count = int(cfg.get("cpu_count") or data.get("cpu_count") or 1)
    memory_mb = int(cfg.get("memory_mb") or data.get("memory_mb") or 512)
    ttl_seconds = int(cfg.get("ttl_seconds") or data.get("ttl_seconds") or 7200)
    extra_config = cfg.get("extra_config") or data.get("extra_config")

    if not image:
        print(f"  WARN: isolatex enabled for '{name}' but no image specified; skipping IsolateX registration")
        return None
    if not challenge_id:
        print(f"  WARN: isolatex enabled for '{name}' but no valid id/slug could be derived")
        return None

    payload: dict[str, Any] = {
        "id": challenge_id,
        "name": name,
        "runtime": runtime,
        "image": image,
        "port": port,
        "cpu_count": cpu_count,
        "memory_mb": memory_mb,
        "ttl_seconds": ttl_seconds,
    }
    if extra_config is not None:
        payload["extra_config"] = extra_config
    return payload


def discover_challenges(root: Path) -> list[LocalChallenge]:
    items: list[LocalChallenge] = []
    for challenge_json in sorted(root.rglob("challenge.json")):
        if "undeployed" in challenge_json.parts:
            continue
        try:
            data = json.loads(challenge_json.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  WARN: could not parse {challenge_json}: {exc}")
            continue

        name = str(data.get("name", "")).strip()
        if not name:
            continue

        description = str(data.get("description", "")).strip()
        category = str(data.get("category", "Misc")).strip() or "Misc"
        try:
            value = int(data.get("value") or 100)
        except Exception:
            value = 100

        slug = str(data.get("id") or slugify(name)).strip()
        isolatex_cfg = parse_isolatex_config(data, name)
        if isolatex_cfg and 'data-isolatex-challenge="' not in description:
            description = (
                f"{description}\n\n<div data-isolatex-challenge=\"{isolatex_cfg['id']}\"></div>"
            ).strip()

        items.append(
            LocalChallenge(
                name=name,
                category=category,
                description=description,
                value=value,
                slug=slug,
                isolatex=isolatex_cfg,
            )
        )
    return items


def get_existing_ctfd_names(session: requests.Session) -> set[str]:
    names: set[str] = set()
    page = 1
    while True:
        resp = session.get(
            f"{CTFD_URL}/api/v1/challenges",
            params={"page": page, "per_page": 100},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            break
        for chal in data:
            name = str(chal.get("name", "")).strip()
            if name:
                names.add(name)
        if len(data) < 100:
            break
        page += 1
    return names


def create_ctfd_challenge(session: requests.Session, challenge: LocalChallenge) -> tuple[bool, str]:
    payload = {
        "name": challenge.name,
        "description": challenge.description,
        "category": challenge.category,
        "value": challenge.value,
        "type": "standard",
        "state": "visible",
    }
    resp = session.post(f"{CTFD_URL}/api/v1/challenges", json=payload, timeout=20)
    if not resp.ok:
        try:
            msg = resp.json().get("errors") or resp.json().get("message") or resp.text
        except Exception:
            msg = resp.text
        return False, str(msg)
    try:
        challenge_id = str(resp.json().get("data", {}).get("id", ""))
    except Exception:
        challenge_id = ""
    return True, challenge_id


def get_orchestrator_existing_ids(api_key: str) -> set[str]:
    if not api_key:
        return set()
    try:
        resp = requests.get(
            f"{ORCHESTRATOR_URL}/challenges",
            headers={"x-api-key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        return {str(ch.get("id")) for ch in resp.json() if ch.get("id")}
    except Exception as exc:
        print(f"  WARN: could not list orchestrator challenges: {exc}")
        return set()


def register_isolatex_challenge(api_key: str, payload: dict[str, Any]) -> tuple[bool, str]:
    if not api_key:
        return False, "missing API_KEY for IsolateX orchestrator"
    try:
        resp = requests.post(
            f"{ORCHESTRATOR_URL}/challenges",
            headers={"x-api-key": api_key, "content-type": "application/json"},
            data=json.dumps(payload),
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, ""
        if resp.status_code == 409:
            return True, "already exists"
        try:
            return False, str(resp.json())
        except Exception:
            return False, resp.text
    except Exception as exc:
        return False, str(exc)


def sync_downloadable_files(challenge_root: Path) -> bool:
    if os.environ.get("SKIP_FILE_UPLOAD", "0") == "1":
        print("\nSkipping challenge file upload because SKIP_FILE_UPLOAD=1.")
        return True

    print("\nSyncing downloadable challenge files into CTFd...")
    env = os.environ.copy()
    env["CHALS_DIR"] = str(challenge_root)
    runner = ROOT / "scripts" / "upload-challenge-files.py"
    proc = subprocess.run([sys.executable, str(runner)], env=env)
    if proc.returncode == 0:
        return True
    print(
        "WARNING: challenge file upload did not complete.\n"
        "Set CTFD_URL / CTFD_USER / CTFD_PASS if needed, then rerun:\n"
        f"  CHALS_DIR=\"{challenge_root}\" python3 scripts/upload-challenge-files.py"
    )
    return False


def main() -> int:
    challenge_root = Path(
        sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CHALS_DIR", str(DEFAULT_CHALLENGE_ROOT))
    ).resolve()
    if not challenge_root.exists():
        print(
            f"ERROR: challenge root does not exist: {challenge_root}\n"
            "Pass a path argument, e.g.:\n"
            "  ./scripts/import-challenges.sh /path/to/your-challenges"
        )
        return 1

    print(f"Importing challenges from: {challenge_root}")
    local_challenges = discover_challenges(challenge_root)
    if not local_challenges:
        print("No challenge.json files found.")
        return 1

    session = login_ctfd()
    existing_ctfd = get_existing_ctfd_names(session)
    print(f"Found {len(existing_ctfd)} existing CTFd challenges")

    api_key = load_api_key()
    existing_isolatex = get_orchestrator_existing_ids(api_key) if api_key else set()
    if not api_key:
        print("WARN: API_KEY not found; IsolateX challenge registration will be skipped.")

    created = 0
    skipped = 0
    failed = 0
    registered = 0
    reg_skipped = 0

    for chal in local_challenges:
        if chal.name in existing_ctfd:
            print(f"  - skip {chal.name} (already exists in CTFd)")
            skipped += 1
        else:
            ok, info = create_ctfd_challenge(session, chal)
            if ok:
                created += 1
                existing_ctfd.add(chal.name)
                print(f"  ✓ create {chal.name}")
            else:
                failed += 1
                print(f"  ✗ fail {chal.name}: {info}")

        if chal.isolatex:
            ix_id = str(chal.isolatex["id"])
            if ix_id in existing_isolatex:
                reg_skipped += 1
                print(f"      └─ skip IsolateX register ({ix_id} already exists)")
            else:
                ok, info = register_isolatex_challenge(api_key, chal.isolatex)
                if ok:
                    registered += 1
                    existing_isolatex.add(ix_id)
                    detail = f" ({info})" if info else ""
                    print(f"      └─ registered with IsolateX: {ix_id}{detail}")
                else:
                    print(f"      └─ WARNING IsolateX register failed ({ix_id}): {info}")

    print(
        "\nImport summary:\n"
        f"  CTFd created: {created}\n"
        f"  CTFd skipped existing: {skipped}\n"
        f"  CTFd failed: {failed}\n"
        f"  IsolateX registered: {registered}\n"
        f"  IsolateX skipped existing: {reg_skipped}"
    )

    sync_downloadable_files(challenge_root)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
