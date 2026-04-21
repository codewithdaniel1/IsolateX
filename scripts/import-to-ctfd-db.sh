#!/bin/bash
# Import challenges from orchestrator into CTFd database directly

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ORCHESTRATOR_URL="${1:-http://localhost:8080}"
ORCHESTRATOR_KEY="${2:-${API_KEY:-}}"
if [ -z "$ORCHESTRATOR_KEY" ] && [ -f "$ROOT_DIR/.env" ]; then
    ORCHESTRATOR_KEY="$(grep -E '^API_KEY=' "$ROOT_DIR/.env" | tail -1 | cut -d= -f2-)"
fi
if [ -z "$ORCHESTRATOR_KEY" ]; then
    echo "ERROR: API key required (arg2/API_KEY/$ROOT_DIR/.env)."
    exit 1
fi
DB_HOST="${3:-127.0.0.1}"
DB_PORT="${4:-3306}"
DB_USER="${5:-ctfd}"
DB_PASS="${6:-ctfd}"
DB_NAME="${7:-ctfd}"

echo "Fetching challenges from orchestrator..."
challenges_json=$(curl -fsS "$ORCHESTRATOR_URL/challenges" \
    -H "x-api-key: $ORCHESTRATOR_KEY")

challenge_count=$(printf "%s" "$challenges_json" | jq 'length')
if [ "$challenge_count" -eq 0 ]; then
    echo "No challenges found in orchestrator"
    exit 0
fi

echo "Found $challenge_count challenges"
echo "Importing into CTFd database (skip existing by name)..."
echo ""

created=0
skipped=0
failed=0

while IFS= read -r chal_json; do
    [ -n "$chal_json" ] || continue
    chal_id=$(printf "%s" "$chal_json" | jq -r '.id')
    chal_name=$(printf "%s" "$chal_json" | jq -r '.name')
    description="Launched via IsolateX <div data-isolatex-challenge=\"$chal_id\"></div>"

    chal_name_sql=$(printf "%s" "$chal_name" | sed "s/'/''/g")
    description_sql=$(printf "%s" "$description" | sed "s/'/''/g")

    existing_count=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" \
        -Nse "SELECT COUNT(*) FROM challenges WHERE name='${chal_name_sql}';" 2>/dev/null || true)

    if [ -z "$existing_count" ]; then
        echo "  ✗ Failed to check existing challenge: $chal_name"
        failed=$((failed + 1))
        continue
    fi

    if [ "$existing_count" -gt 0 ]; then
        echo "  - skip $chal_name (already exists in CTFd)"
        skipped=$((skipped + 1))
        continue
    fi

    if mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" \
        -e "INSERT INTO challenges (name, description, category, value, type, state) VALUES ('${chal_name_sql}', '${description_sql}', 'Web', 100, 'standard', 'visible');" \
        >/dev/null 2>&1; then
        echo "  ✓ create $chal_name"
        created=$((created + 1))
    else
        echo "  ✗ Failed to create: $chal_name"
        failed=$((failed + 1))
    fi
done < <(printf "%s" "$challenges_json" | jq -c '.[]')

echo ""
echo "Import complete. Created: $created, skipped existing: $skipped, failed: $failed"
echo "Challenges in CTFd:"
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" \
    -se "SELECT name FROM challenges ORDER BY id DESC LIMIT 10;" 2>/dev/null || echo "(Could not verify)"

if [ "$failed" -gt 0 ]; then
    exit 1
fi
