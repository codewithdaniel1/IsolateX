#!/usr/bin/env python3
"""
Upload downloadable challenge files to CTFd.

The script discovers challenge attachments from each challenge's `challenge.json`
`files` field and uploads any missing files to the matching CTFd challenge by
name. Safe to re-run.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests


CTFD_URL = os.environ.get("CTFD_URL", "http://127.0.0.1:8000")
CTFD_USER = os.environ.get("CTFD_USER", "admin")
CTFD_PASS = os.environ.get("CTFD_PASS", "admin")
CHALS_DIR = Path(
    os.environ.get(
        "CHALS_DIR",
        os.path.join(os.path.dirname(__file__), "../../recruit-chals"),
    )
).resolve()


def _login() -> requests.Session:
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
    return session


def discover_challenge_files(root: Path) -> dict[str, list[Path]]:
    files_by_name: dict[str, list[Path]] = {}
    for challenge_json in sorted(root.rglob("challenge.json")):
        if "undeployed" in challenge_json.parts:
            continue

        try:
            data = json.loads(challenge_json.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] could not parse {challenge_json}: {exc}")
            continue

        name = (data.get("name") or "").strip()
        rel_files = data.get("files") or []
        if not name or not isinstance(rel_files, list) or not rel_files:
            continue

        challenge_dir = challenge_json.parent
        resolved_paths = []
        for rel_path in rel_files:
            if not rel_path:
                continue
            resolved_paths.append((challenge_dir / rel_path).resolve())

        if resolved_paths:
            files_by_name[name] = resolved_paths

    return files_by_name


def get_challenges(session: requests.Session) -> dict[str, int]:
    challenge_ids: dict[str, int] = {}
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

        for challenge in data:
            challenge_ids[challenge["name"]] = challenge["id"]

        if len(data) < 100:
            break
        page += 1

    return challenge_ids


def get_existing_files(session: requests.Session, challenge_id: int) -> set[str]:
    resp = session.get(f"{CTFD_URL}/api/v1/challenges/{challenge_id}/files", timeout=15)
    if not resp.ok:
        return set()
    return {os.path.basename(file_info["location"]) for file_info in resp.json().get("data", [])}


def upload_file(session: requests.Session, challenge_id: int, filepath: Path) -> str:
    filename = filepath.name
    with filepath.open("rb") as file_handle:
        resp = session.post(
            f"{CTFD_URL}/api/v1/files",
            data={"challenge_id": challenge_id, "type": "challenge"},
            files={"file": (filename, file_handle)},
            timeout=30,
        )
    resp.raise_for_status()

    data = resp.json().get("data", {})
    if isinstance(data, list):
        data = data[0] if data else {}
    location = data.get("location", "")
    print(f"  uploaded {filename} -> {location}")
    return location


def main() -> int:
    if not CHALS_DIR.exists():
        print(f"[ERROR] challenge directory not found: {CHALS_DIR}")
        return 1

    session = _login()
    challenges = get_challenges(session)
    challenge_files = discover_challenge_files(CHALS_DIR)

    print(f"Found {len(challenges)} challenges in CTFd")
    print(f"Discovered downloadable files for {len(challenge_files)} challenges\n")

    uploaded = 0
    skipped = 0
    missing = 0

    for name, filepaths in challenge_files.items():
        challenge_id = challenges.get(name)
        if not challenge_id:
            print(f"[SKIP] '{name}' not found in CTFd")
            skipped += 1
            continue

        existing_names = get_existing_files(session, challenge_id)
        print(f"[{name}] (id={challenge_id})")

        for filepath in filepaths:
            filename = filepath.name
            if not filepath.exists():
                print(f"  MISSING: {filepath}")
                missing += 1
                continue
            if filename in existing_names:
                print(f"  already uploaded: {filename}")
                continue

            upload_file(session, challenge_id, filepath)
            uploaded += 1

    print("\nDone.")
    print(f"Uploaded: {uploaded}, missing: {missing}, skipped challenges: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
