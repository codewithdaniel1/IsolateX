#!/bin/bash
# Import all recruit-chals into CTFd and register instanced ones with the orchestrator.
# Reads challenge.json for metadata. Skips challenges already in CTFd by name.
#
# Usage:
#   ./scripts/import-recruit-chals.sh [path-to-recruit-chals]

set -euo pipefail

RECRUIT_DIR="${1:-/Users/danielpeng/Downloads/recruit-chals}"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:8080}"
API_KEY="${API_KEY:-dev-api-key-change-in-prod}"

# Challenges that need a live instance (have a port + Docker image)
INSTANCED_CHALLENGES=(
  "php" "pwntools" "Assembly" "Docker" "overflow"
  "cmdinj" "cookies" "holes" "lfi" "view_source" "SQLi"
  "BlindAsABat" "Template Programming"
  "AES CBC" "AES ECB"
  "POR" "UAF" "No Free Shells" "Pivot" "Simply Smashing" "stacking" "unsafe-linking"
  "MasterChallenge" "Postage" "checker" "go" "rubiksCube"
)

is_instanced() {
  local name="$1"
  for i in "${INSTANCED_CHALLENGES[@]}"; do
    [ "$i" = "$name" ] && return 0
  done
  return 1
}

echo "Importing challenges from $RECRUIT_DIR into CTFd..."
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

python3 - "$RECRUIT_DIR" "$ORCHESTRATOR_URL" "$API_KEY" "$SCRIPT_DIR" <<'PYEOF'
import json, os, glob, sys, subprocess, re

base      = sys.argv[1]
orch_url  = sys.argv[2]
api_key   = sys.argv[3]
script_dir = sys.argv[4]

INSTANCED = {
    "php", "pwntools", "Assembly", "Docker", "overflow",
    "cmdinj", "cookies", "holes", "lfi", "view_source", "SQLi",
    "BlindAsABat", "Template Programming",
    "AES CBC", "AES ECB",
    "POR", "UAF", "No Free Shells", "Pivot", "Simply Smashing", "stacking", "unsafe-linking",
    "MasterChallenge", "Postage", "checker", "go", "rubiksCube",
}

challenges = []
for path in sorted(glob.glob(f"{base}/**/challenge.json", recursive=True)):
    if "undeployed" in path:
        continue
    try:
        d = json.load(open(path))
        name = d.get("name", "").strip()
        if not name:
            continue
        challenges.append({
            "name":        name,
            "category":    d.get("category", "Misc"),
            "description": d.get("description", "").strip(),
            "value":       d.get("value", 100) or 100,
            "port":        d.get("internal_port", 80) or 80,
            "slug":        re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
        })
    except Exception as e:
        print(f"  WARN: could not parse {path}: {e}")

# Get existing CTFd challenge names to avoid duplicates
result = subprocess.run(
    ["docker", "compose", "exec", "-T", "ctfd-db",
     "mysql", "-uctfd", "-pctfd", "ctfd", "-sNe",
     "SELECT name FROM challenges;"],
    capture_output=True, text=True, cwd=script_dir
)
existing = set(result.stdout.strip().splitlines())

# Get existing orchestrator challenges
import urllib.request
req = urllib.request.Request(
    f"{orch_url}/challenges",
    headers={"x-api-key": api_key}
)
try:
    with urllib.request.urlopen(req, timeout=5) as r:
        ix_existing = {c["id"] for c in json.load(r)}
except Exception:
    ix_existing = set()

imported = 0
skipped  = 0
orch_registered = 0

for c in challenges:
    name = c["name"]
    if name in existing:
        print(f"  skip  {name} (already in CTFd)")
        skipped += 1
        continue

    # Escape for SQL
    safe_name = name.replace("'", "''")
    safe_desc = c["description"].replace("'", "''").replace("\\", "\\\\")
    safe_cat  = c["category"].replace("'", "''")
    val       = c["value"]

    sql = (
        f"INSERT INTO challenges (name, description, category, value, type, state, logic) "
        f"VALUES ('{safe_name}', '{safe_desc}', '{safe_cat}', {val}, 'standard', 'visible', 'any');"
    )
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "ctfd-db",
         "mysql", "-uctfd", "-pctfd", "ctfd", "-e", sql],
        capture_output=True, text=True,
        cwd=script_dir
    )
    if result.returncode != 0:
        print(f"  ERROR {name}: {result.stderr.strip()}")
        continue

    imported += 1
    print(f"  added {name} ({c['category']}, {val} pts)")

    # Register instanced challenges with the orchestrator
    if name in INSTANCED and c["slug"] not in ix_existing:
        image = f"recruit-{c['category'].lower()}-{c['slug']}"
        payload = json.dumps({
            "id":         c["slug"],
            "name":       name,
            "runtime":    "docker",
            "image":      image,
            "port":       c["port"],
            "cpu_count":  1,
            "memory_mb":  512,
            "ttl_seconds": 7200,
        }).encode()
        req2 = urllib.request.Request(
            f"{orch_url}/challenges",
            data=payload,
            headers={"x-api-key": api_key, "content-type": "application/json"},
            method="POST"
        )
        try:
            urllib.request.urlopen(req2, timeout=5)
            orch_registered += 1
            print(f"         └─ registered with IsolateX (image: {image}, port: {c['port']})")
        except Exception as e:
            print(f"         └─ WARNING: could not register with IsolateX: {e}")

print("")
print(f"Done. {imported} added, {skipped} skipped, {orch_registered} registered with IsolateX.")
PYEOF
