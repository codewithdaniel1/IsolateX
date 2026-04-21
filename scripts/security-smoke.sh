#!/usr/bin/env bash
# Live security smoke test for a running IsolateX stack.
# Runs auth checks, flag-leak checks, lifecycle checks, and cleanup.
#
# Usage:
#   ./scripts/security-smoke.sh
#   API_KEY=... ./scripts/security-smoke.sh
#   ./scripts/security-smoke.sh --challenge-id sqli
#
# Optional env vars:
#   ORCH_URL   (default: http://localhost:8080)
#   CTFD_URL   (default: http://localhost:8000)
#   TEAM_ID    (default: smoke-team)

set -euo pipefail

ORCH_URL="${ORCH_URL:-http://localhost:8080}"
CTFD_URL="${CTFD_URL:-http://localhost:8000}"
TEAM_ID="${TEAM_ID:-smoke-team}"
CHALLENGE_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --challenge-id)
      CHALLENGE_ID="${2:-}"
      [ -n "$CHALLENGE_ID" ] || { echo "ERROR: --challenge-id requires a value"; exit 1; }
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1"
      exit 1
      ;;
  esac
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1"
    exit 1
  }
}

need_cmd curl
need_cmd jq

TMP_BODY="$(mktemp)"
TMP_ERR="$(mktemp)"
trap 'rm -f "$TMP_BODY" "$TMP_ERR"' EXIT

PASS=0
FAIL=0
WARN=0

pass() { PASS=$((PASS + 1)); printf '[PASS] %s\n' "$*"; }
fail() { FAIL=$((FAIL + 1)); printf '[FAIL] %s\n' "$*"; }
warn() { WARN=$((WARN + 1)); printf '[WARN] %s\n' "$*"; }
info() { printf '[INFO] %s\n' "$*"; }

http_code() {
  local method="$1"; shift
  local url="$1"; shift
  local code
  code="$(curl -sS -o "$TMP_BODY" -w '%{http_code}' -X "$method" "$url" "$@" 2>"$TMP_ERR")" || code="000"
  echo "$code"
}

load_api_key() {
  if [ -n "${API_KEY:-}" ]; then
    echo "$API_KEY"
    return
  fi

  if [ -f ".env" ]; then
    local key
    key="$(grep -E '^API_KEY=' .env | tail -1 | cut -d= -f2- || true)"
    if [ -n "$key" ]; then
      echo "$key"
      return
    fi
  fi

  if command -v docker >/dev/null 2>&1; then
    local key
    key="$(
      docker inspect isolatex-orchestrator-1 --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | sed -n 's/^API_KEY=//p' | head -1 || true
    )"
    if [ -n "$key" ]; then
      echo "$key"
      return
    fi
  fi

  echo ""
}

API_KEY_VALUE="$(load_api_key)"
if [ -z "$API_KEY_VALUE" ]; then
  echo "ERROR: could not resolve API key (env API_KEY, .env, or docker inspect)."
  exit 1
fi
info "Resolved API key (masked, length=${#API_KEY_VALUE})"

INSTANCE_ID=""
CREATED_CHALLENGE=0
CREATED_CHALLENGE_ID=""

cleanup() {
  if [ -n "$INSTANCE_ID" ]; then
    http_code DELETE "${ORCH_URL}/instances/${INSTANCE_ID}" -H "x-api-key: ${API_KEY_VALUE}" >/dev/null
  fi
  if [ "$CREATED_CHALLENGE" -eq 1 ] && [ -n "$CREATED_CHALLENGE_ID" ]; then
    http_code DELETE "${ORCH_URL}/challenges/${CREATED_CHALLENGE_ID}" -H "x-api-key: ${API_KEY_VALUE}" >/dev/null
  fi
}
trap cleanup EXIT

info "1) Health checks"
SC_ORCH="$(http_code GET "${ORCH_URL}/health")"
SC_CTFD="$(http_code GET "${CTFD_URL}/login")"
[ "$SC_ORCH" = "200" ] && pass "Orchestrator /health is reachable (200)" || fail "Orchestrator /health expected 200, got ${SC_ORCH}"
[ "$SC_CTFD" = "200" ] && pass "CTFd /login is reachable (200)" || fail "CTFd /login expected 200, got ${SC_CTFD}"

info "2) Auth-negative checks"
SC_WORKERS_NOAUTH="$(http_code GET "${ORCH_URL}/workers")"
SC_WORKERS_BAD="$(http_code GET "${ORCH_URL}/workers" -H 'x-api-key: wrong-key')"
SC_WORKERS_OK="$(http_code GET "${ORCH_URL}/workers" -H "x-api-key: ${API_KEY_VALUE}")"
[[ "$SC_WORKERS_NOAUTH" =~ ^(401|422)$ ]] && pass "/workers blocks missing API key (${SC_WORKERS_NOAUTH})" || fail "/workers should block missing API key (got ${SC_WORKERS_NOAUTH})"
[ "$SC_WORKERS_BAD" = "403" ] && pass "/workers blocks bad API key (403)" || fail "/workers should return 403 for bad key (got ${SC_WORKERS_BAD})"
[ "$SC_WORKERS_OK" = "200" ] && pass "/workers accepts valid API key (200)" || fail "/workers should return 200 with valid key (got ${SC_WORKERS_OK})"

SC_TRAEFIK_NOAUTH="$(http_code GET "${ORCH_URL}/traefik/config")"
SC_TRAEFIK_BAD="$(http_code GET "${ORCH_URL}/traefik/config" -H 'x-api-key: wrong-key')"
SC_TRAEFIK_OK="$(http_code GET "${ORCH_URL}/traefik/config" -H "x-api-key: ${API_KEY_VALUE}")"
[[ "$SC_TRAEFIK_NOAUTH" =~ ^(401|422)$ ]] && pass "/traefik/config blocks missing API key (${SC_TRAEFIK_NOAUTH})" || fail "/traefik/config should block missing API key (got ${SC_TRAEFIK_NOAUTH})"
[ "$SC_TRAEFIK_BAD" = "403" ] && pass "/traefik/config blocks bad API key (403)" || fail "/traefik/config should return 403 for bad key (got ${SC_TRAEFIK_BAD})"
[ "$SC_TRAEFIK_OK" = "200" ] && pass "/traefik/config accepts valid API key (200)" || fail "/traefik/config should return 200 with valid key (got ${SC_TRAEFIK_OK})"

info "3) Worker host exposure probe"
SC_WORKER_HEALTH="$(http_code GET 'http://localhost:9090/health')"
if [ "$SC_WORKER_HEALTH" = "000" ]; then
  pass "Worker API is not exposed on host :9090"
else
  fail "Worker API should not be exposed on host :9090 (got ${SC_WORKER_HEALTH})"
fi

info "4) CTFd auth gate check for IsolateX plugin route"
SC_PLUGIN="$(http_code GET "${CTFD_URL}/isolatex/instance/smoke-check")"
[[ "$SC_PLUGIN" =~ ^(302|401)$ ]] && pass "CTFd plugin route requires auth (${SC_PLUGIN})" || fail "CTFd plugin route should require auth (got ${SC_PLUGIN})"

info "5) Lifecycle + flag-leak checks"
SC_CHALS="$(http_code GET "${ORCH_URL}/challenges" -H "x-api-key: ${API_KEY_VALUE}")"
if [ "$SC_CHALS" != "200" ]; then
  fail "Failed listing challenges (${SC_CHALS})"
else
  if [ -z "$CHALLENGE_ID" ]; then
    CHALLENGE_ID="$(jq -r '.[0].id // empty' "$TMP_BODY")"
  fi

  if [ -z "$CHALLENGE_ID" ]; then
    CHALLENGE_ID="smoke-$(date +%s)"
    CREATE_PAYLOAD="$(jq -nc --arg id "$CHALLENGE_ID" '{id:$id,name:"Smoke Challenge",runtime:"docker",image:"nginx:alpine",port:80,cpu_count:1,memory_mb:256,ttl_seconds:600}')"
    SC_CREATE="$(http_code POST "${ORCH_URL}/challenges" -H "x-api-key: ${API_KEY_VALUE}" -H 'content-type: application/json' -d "$CREATE_PAYLOAD")"
    if [[ "$SC_CREATE" =~ ^(200|201)$ ]]; then
      pass "Created temporary challenge ${CHALLENGE_ID} for smoke run"
      CREATED_CHALLENGE=1
      CREATED_CHALLENGE_ID="$CHALLENGE_ID"
    else
      fail "Failed to create temporary challenge (${SC_CREATE})"
    fi
  fi

  info "Using challenge id: ${CHALLENGE_ID}"
  LAUNCH_PAYLOAD="$(jq -nc --arg tid "$TEAM_ID" --arg cid "$CHALLENGE_ID" '{team_id:$tid,challenge_id:$cid}')"
  SC_LAUNCH="$(http_code POST "${ORCH_URL}/instances" -H "x-api-key: ${API_KEY_VALUE}" -H 'content-type: application/json' -d "$LAUNCH_PAYLOAD")"

  if [ "$SC_LAUNCH" = "409" ]; then
    SC_EXISTING="$(http_code GET "${ORCH_URL}/instances/team/${TEAM_ID}/${CHALLENGE_ID}" -H "x-api-key: ${API_KEY_VALUE}")"
    if [ "$SC_EXISTING" = "200" ]; then
      INSTANCE_ID="$(jq -r '.id // empty' "$TMP_BODY")"
      warn "Instance already existed for ${TEAM_ID}/${CHALLENGE_ID}; reusing ${INSTANCE_ID}"
      HAS_FLAG_EXISTING="$(jq -r 'has("flag")' "$TMP_BODY")"
      [ "$HAS_FLAG_EXISTING" = "false" ] && pass "Existing team lookup does not expose flag" || fail "Existing team lookup leaked flag field"
    else
      fail "Launch returned 409 and team lookup failed (${SC_EXISTING})"
    fi
  elif [ "$SC_LAUNCH" = "201" ]; then
    INSTANCE_ID="$(jq -r '.id // empty' "$TMP_BODY")"
    HAS_FLAG_LAUNCH="$(jq -r 'has("flag")' "$TMP_BODY")"
    [ -n "$INSTANCE_ID" ] && pass "Launched instance ${INSTANCE_ID}" || fail "Launch response missing instance id"
    [ "$HAS_FLAG_LAUNCH" = "false" ] && pass "Launch response does not expose flag" || fail "Launch response leaked flag field"
  else
    fail "Launch failed (${SC_LAUNCH})"
  fi

  if [ -n "$INSTANCE_ID" ]; then
    SC_GET="$(http_code GET "${ORCH_URL}/instances/${INSTANCE_ID}" -H "x-api-key: ${API_KEY_VALUE}")"
    HAS_FLAG_GET="$(jq -r 'has("flag")' "$TMP_BODY" 2>/dev/null || echo "unknown")"
    [ "$SC_GET" = "200" ] && pass "Fetched instance by id" || fail "GET /instances/{id} failed (${SC_GET})"
    [ "$HAS_FLAG_GET" = "false" ] && pass "Instance read does not expose flag" || fail "Instance read leaked flag field"

    SC_TEAM="$(http_code GET "${ORCH_URL}/instances/team/${TEAM_ID}/${CHALLENGE_ID}" -H "x-api-key: ${API_KEY_VALUE}")"
    HAS_FLAG_TEAM="$(jq -r 'has("flag")' "$TMP_BODY" 2>/dev/null || echo "unknown")"
    [ "$SC_TEAM" = "200" ] && pass "Fetched instance by team/challenge" || fail "Team instance lookup failed (${SC_TEAM})"
    [ "$HAS_FLAG_TEAM" = "false" ] && pass "Team lookup does not expose flag" || fail "Team lookup leaked flag field"

    SC_STOP="$(http_code DELETE "${ORCH_URL}/instances/${INSTANCE_ID}" -H "x-api-key: ${API_KEY_VALUE}")"
    if [[ "$SC_STOP" =~ ^(200|204)$ ]]; then
      pass "Stopped instance ${INSTANCE_ID}"
      INSTANCE_ID=""
    else
      fail "Failed to stop instance ${INSTANCE_ID} (${SC_STOP})"
    fi
  fi
fi

info "6) CORS header sanity"
if curl -sSI "${ORCH_URL}/health" | grep -qi '^Access-Control-Allow-Origin:[[:space:]]*\*$'; then
  fail "Wildcard CORS header found on orchestrator health endpoint"
else
  pass "No wildcard CORS header on orchestrator health endpoint"
fi

info "7) Quick secret-pattern log probe"
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q '^isolatex-orchestrator-1$'; then
  LOG_SAMPLE="$( (docker logs --tail 300 isolatex-orchestrator-1 2>&1; docker logs --tail 300 isolatex-worker-docker-1 2>&1) || true )"
  if printf '%s' "$LOG_SAMPLE" | grep -Eiq '(API_KEY=|FLAG_HMAC_SECRET=|ISOLATEX_API_KEY=)'; then
    fail "Potential secret-like env token found in recent logs"
  else
    pass "No obvious env-secret patterns in recent orchestrator/worker logs"
  fi
else
  warn "Docker containers not detectable from this shell; skipped log probe"
fi

echo ""
echo "Security smoke summary: PASS=${PASS} WARN=${WARN} FAIL=${FAIL}"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
