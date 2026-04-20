#!/usr/bin/env python3
"""
Upload downloadable challenge files to CTFd.

Primary detection comes from each challenge's `challenge.json` `files` field.
If a challenge explicitly sets `"files": []`, that means "no downloads" and the
script will not guess. Safe to re-run.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests


CTFD_URL = os.environ.get("CTFD_URL", "http://127.0.0.1:8000")
CTFD_USER = os.environ.get("CTFD_USER", "admin")
CTFD_PASS = os.environ.get("CTFD_PASS", "admin")
CTFD_DB_USER = os.environ.get("CTFD_DB_USER", "ctfd")
CTFD_DB_PASS = os.environ.get("CTFD_DB_PASS", "ctfd")
CTFD_DB_NAME = os.environ.get("CTFD_DB_NAME", "ctfd")
CTFD_UPLOAD_FOLDER = os.environ.get("CTFD_UPLOAD_FOLDER", "/var/uploads")
CTFD_COMPOSE_SERVICE = os.environ.get("CTFD_COMPOSE_SERVICE", "ctfd")
CTFD_DB_COMPOSE_SERVICE = os.environ.get("CTFD_DB_COMPOSE_SERVICE", "ctfd-db")
CHALS_DIR = Path(
    os.environ.get(
        "CHALS_DIR",
        os.path.join(os.path.dirname(__file__), "../../recruit-chals"),
    )
).resolve()

KNOWN_DOWNLOAD_DIRS = {
    "share",
    "dist",
    "downloads",
    "download",
    "files",
    "attachments",
    "artifacts",
    "release",
    "releases",
    "challenge-files",
}

LIKELY_ARCHIVE_EXTENSIONS = {
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".xz",
    ".7z",
    ".rar",
}

LIKELY_DOWNLOAD_EXTENSIONS = LIKELY_ARCHIVE_EXTENSIONS | {
    ".pcap",
    ".pcapng",
    ".cap",
    ".bin",
    ".img",
    ".iso",
    ".pem",
    ".der",
    ".crt",
    ".cer",
}

SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".py",
    ".js",
    ".ts",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
}

IGNORED_FILENAMES = {
    "challenge.json",
    "dockerfile",
    "readme",
    "license",
    "flag",
    "start.sh",
    "build.sh",
    "solver.py",
    "solver.sh",
    "solver",
    "requirements.txt",
    "supervisord.conf",
    "docker-compose.yml",
    "docker-compose.yaml",
}


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

    if resp.url.rstrip("/").endswith("/login") or "incorrect" in resp.text.lower():
        raise RuntimeError(
            "CTFd login failed. Set CTFD_USER and CTFD_PASS to an admin account before syncing files."
        )

    return session


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _is_ignored_file(path: Path) -> bool:
    lower_name = path.name.lower()
    if lower_name in IGNORED_FILENAMES:
        return True
    if lower_name.startswith("flag") or lower_name.startswith("solver"):
        return True
    return lower_name.startswith(".")


def _likely_root_binary(path: Path, challenge_dir: Path, challenge_name: str) -> bool:
    if not path.is_file() or _is_ignored_file(path):
        return False
    if path.suffix:
        return False

    normalized = {
        _normalize_name(challenge_name),
        _normalize_name(challenge_dir.name),
    }
    return _normalize_name(path.name) in normalized


def _maybe_single_source_file(challenge_dir: Path) -> list[Path]:
    candidates = [
        path for path in challenge_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS and not _is_ignored_file(path)
    ]
    if len(candidates) == 1:
        return candidates
    return []


def detect_downloadable_files(challenge_dir: Path, challenge_name: str, metadata: dict) -> tuple[list[Path], str]:
    if "files" in metadata:
        rel_files = metadata.get("files")
        if isinstance(rel_files, list) and rel_files:
            explicit = [
                (challenge_dir / rel_path).resolve()
                for rel_path in rel_files
                if rel_path
            ]
            return _dedupe_paths(explicit), "challenge.json files"
        return [], ""

    heuristic_paths: list[Path] = []

    for child in sorted(challenge_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.lower() in KNOWN_DOWNLOAD_DIRS:
            heuristic_paths.extend(sorted(path.resolve() for path in child.rglob("*") if path.is_file()))

    for child in sorted(challenge_dir.iterdir()):
        if not child.is_file() or _is_ignored_file(child):
            continue
        if child.suffix.lower() in LIKELY_DOWNLOAD_EXTENSIONS:
            heuristic_paths.append(child.resolve())
            continue
        if _likely_root_binary(child, challenge_dir, challenge_name):
            heuristic_paths.append(child.resolve())

    if not heuristic_paths:
        heuristic_paths.extend(path.resolve() for path in _maybe_single_source_file(challenge_dir))

    heuristic_paths = _dedupe_paths(heuristic_paths)
    if heuristic_paths:
        return heuristic_paths, "heuristic fallback"

    return [], ""


def discover_challenge_files(root: Path) -> tuple[dict[str, list[Path]], dict[str, str]]:
    files_by_name: dict[str, list[Path]] = {}
    detection_by_name: dict[str, str] = {}
    for challenge_json in sorted(root.rglob("challenge.json")):
        if "undeployed" in challenge_json.parts:
            continue

        try:
            data = json.loads(challenge_json.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] could not parse {challenge_json}: {exc}")
            continue

        name = (data.get("name") or "").strip()
        if not name:
            continue

        challenge_dir = challenge_json.parent
        resolved_paths, detection_reason = detect_downloadable_files(challenge_dir, name, data)

        if resolved_paths:
            files_by_name[name] = resolved_paths
            detection_by_name[name] = detection_reason

    return files_by_name, detection_by_name


def get_challenges(session: Optional[requests.Session] = None) -> dict[str, int]:
    challenge_ids: dict[str, int] = {}
    page = 1

    while True:
        getter = session.get if session else requests.get
        resp = getter(
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
    resp = session.get(f"{CTFD_URL}/api/v1/challenges/{challenge_id}", timeout=15)
    if not resp.ok:
        return set()
    payload = resp.json().get("data", {})
    return {
        os.path.basename(file_info["location"])
        for file_info in payload.get("files", [])
        if file_info.get("location")
    }


def get_existing_files_public(challenge_id: int) -> set[str]:
    resp = requests.get(f"{CTFD_URL}/api/v1/challenges/{challenge_id}", timeout=15)
    if not resp.ok:
        return set()
    payload = resp.json().get("data", {})
    return {
        os.path.basename(file_info["location"])
        for file_info in payload.get("files", [])
        if file_info.get("location")
    }


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


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return cleaned or "download"


def _compose_exec(service: str, command: str, *, stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", service, "sh", "-lc", command],
        input=stdin,
        capture_output=True,
        check=True,
    )


def _insert_file_row(location: str, challenge_id: int, sha1sum: str) -> None:
    sql = (
        "INSERT INTO files (type, location, challenge_id, sha1sum) "
        f"VALUES ('challenge', '{location}', {challenge_id}, '{sha1sum}');"
    )
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            CTFD_DB_COMPOSE_SERVICE,
            "mysql",
            f"-u{CTFD_DB_USER}",
            f"-p{CTFD_DB_PASS}",
            CTFD_DB_NAME,
            "-e",
            sql,
        ],
        capture_output=True,
        check=True,
    )


def sync_file_via_compose(challenge_id: int, filepath: Path) -> str:
    upload_dir = secrets.token_hex(16)
    filename = _sanitize_filename(filepath.name)
    location = f"{upload_dir}/{filename}"
    container_path = f"{CTFD_UPLOAD_FOLDER}/{location}"

    data = filepath.read_bytes()
    _compose_exec(
        CTFD_COMPOSE_SERVICE,
        f"mkdir -p {shlex.quote(f'{CTFD_UPLOAD_FOLDER}/{upload_dir}')} && cat > {shlex.quote(container_path)}",
        stdin=data,
    )

    import hashlib

    sha1sum = hashlib.sha1(data).hexdigest()
    _insert_file_row(location, challenge_id, sha1sum)
    print(f"  synced {filename} -> {location} (via docker compose)")
    return location


def main() -> int:
    if not CHALS_DIR.exists():
        print(f"[ERROR] challenge directory not found: {CHALS_DIR}")
        return 1

    session = None
    try:
        session = _login()
        use_compose = False
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
        print("[WARN] Falling back to direct Docker Compose sync for local CTFd.")
        use_compose = True

    challenges = get_challenges(session)
    challenge_files, detection_by_name = discover_challenge_files(CHALS_DIR)

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

        existing_names = get_existing_files_public(challenge_id)
        detection_reason = detection_by_name.get(name, "detected")
        print(f"[{name}] (id={challenge_id}, via {detection_reason})")

        for filepath in filepaths:
            filename = filepath.name
            if not filepath.exists():
                print(f"  MISSING: {filepath}")
                missing += 1
                continue
            if filename in existing_names:
                print(f"  already uploaded: {filename}")
                continue

            if use_compose:
                sync_file_via_compose(challenge_id, filepath)
            else:
                upload_file(session, challenge_id, filepath)
            uploaded += 1

    print("\nDone.")
    print(f"Uploaded: {uploaded}, missing: {missing}, skipped challenges: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
