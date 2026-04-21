#!/usr/bin/env bash
# Build bundled CTFd image with fallback support.
# Tries CTFD_BASE_IMAGE first (defaults to ctfd/ctfd:latest). If it fails,
# tries fallback candidates from CTFD_FALLBACK_IMAGES, or auto-discovers
# older semver tags from Docker Hub when CTFD_BASE_IMAGE uses :latest.
#
# Env:
#   CTFD_BASE_IMAGE       default: ctfd/ctfd:latest
#   CTFD_FALLBACK_IMAGES  optional CSV list, e.g. "ctfd/ctfd:3.8.2,ctfd/ctfd:3.8.1"
#   CTFD_AUTO_FALLBACK    1 (default) to auto-discover fallback tags, 0 to disable

set -euo pipefail

info() { echo "[IsolateX][CTFd] $*"; }
warn() { echo "[IsolateX][CTFd][WARN] $*" >&2; }

PREFERRED_IMAGE="${CTFD_BASE_IMAGE:-ctfd/ctfd:latest}"
FALLBACK_IMAGES_RAW="${CTFD_FALLBACK_IMAGES:-}"
AUTO_FALLBACK="${CTFD_AUTO_FALLBACK:-1}"

REPO="${PREFERRED_IMAGE%:*}"
if [ "$REPO" = "$PREFERRED_IMAGE" ]; then
  REPO="$PREFERRED_IMAGE"
  PREFERRED_IMAGE="${PREFERRED_IMAGE}:latest"
fi

CANDIDATES=""

append_unique() {
  local candidate="$1"
  [ -n "$candidate" ] || return 0
  case "
$CANDIDATES
" in
    *"
$candidate
"*) ;;
    *)
      if [ -z "$CANDIDATES" ]; then
        CANDIDATES="$candidate"
      else
        CANDIDATES="${CANDIDATES}
${candidate}"
      fi
      ;;
  esac
}

append_csv_candidates() {
  local csv="$1"
  local rest="$csv"
  local item
  while [ -n "$rest" ]; do
    item="${rest%%,*}"
    if [ "$rest" = "$item" ]; then
      rest=""
    else
      rest="${rest#*,}"
    fi
    item="$(printf '%s' "$item" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    append_unique "$item"
  done
}

discover_auto_fallbacks() {
  python3 - "$REPO" <<'PY'
import json
import re
import sys
import urllib.request
from urllib.error import URLError, HTTPError

repo = sys.argv[1]
tags = []
url = f"https://registry.hub.docker.com/v2/repositories/{repo}/tags?page_size=100"

for _ in range(3):
    if not url:
        break
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            payload = json.load(r)
    except (URLError, HTTPError, TimeoutError):
        break
    except Exception:
        break
    tags.extend(item.get("name", "") for item in payload.get("results", []))
    url = payload.get("next")

semver = []
for tag in tags:
    if re.fullmatch(r"\d+\.\d+\.\d+", tag):
        semver.append(tag)

semver = sorted(set(semver), key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)

for tag in semver[:5]:
    print(f"{repo}:{tag}")
PY
}

append_unique "$PREFERRED_IMAGE"

if [ -n "$FALLBACK_IMAGES_RAW" ]; then
  append_csv_candidates "$FALLBACK_IMAGES_RAW"
elif [ "$AUTO_FALLBACK" = "1" ] && [ "${PREFERRED_IMAGE##*:}" = "latest" ] && command -v python3 >/dev/null 2>&1; then
  append_unique "${REPO}:stable"
  AUTO_IMAGES="$(discover_auto_fallbacks || true)"
  while IFS= read -r auto_image; do
    append_unique "$auto_image"
  done <<< "$AUTO_IMAGES"
fi

info "CTFd base image candidates:"
while IFS= read -r image; do
  [ -n "$image" ] || continue
  echo "  - $image"
done <<< "$CANDIDATES"

SELECTED_IMAGE=""
while IFS= read -r image; do
  [ -n "$image" ] || continue
  info "Trying CTFd base image: $image"
  docker pull "$image" >/dev/null 2>&1 || warn "Could not pre-pull $image; trying build anyway."
  if CTFD_BASE_IMAGE="$image" docker compose build ctfd; then
    SELECTED_IMAGE="$image"
    break
  fi
  warn "Build failed for $image"
done <<< "$CANDIDATES"

if [ -z "$SELECTED_IMAGE" ]; then
  warn "All CTFd base image candidates failed to build."
  exit 1
fi

info "Selected CTFd base image: $SELECTED_IMAGE"
