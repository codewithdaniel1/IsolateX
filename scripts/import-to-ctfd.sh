#!/bin/bash
# Import challenges from orchestrator into CTFd

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ORCHESTRATOR_URL="${1:-http://localhost:8080}"
CTFD_URL="${2:-http://localhost:8000}"
ORCHESTRATOR_KEY="${3:-${API_KEY:-}}"
if [ -z "$ORCHESTRATOR_KEY" ] && [ -f "$ROOT_DIR/.env" ]; then
    ORCHESTRATOR_KEY="$(grep -E '^API_KEY=' "$ROOT_DIR/.env" | tail -1 | cut -d= -f2-)"
fi
if [ -z "$ORCHESTRATOR_KEY" ]; then
    echo "ERROR: API key required (arg3/API_KEY/$ROOT_DIR/.env)."
    exit 1
fi

echo "Fetching challenges from orchestrator..."
challenges=$(curl -s "$ORCHESTRATOR_URL/challenges" \
  -H "x-api-key: $ORCHESTRATOR_KEY" | jq -c '.[]')

if [ -z "$challenges" ]; then
    echo "No challenges found in orchestrator"
    exit 1
fi

# First, try to get a valid session/token from CTFd
echo "Authenticating with CTFd..."

# Get CSRF token
csrf_token=$(curl -s -c /tmp/ctfd_cookies.txt "$CTFD_URL/login" | grep -oP 'name="csrf_token" value="\K[^"]+' || echo "")

if [ -z "$csrf_token" ]; then
    echo "Warning: Could not get CSRF token, trying without it..."
fi

# Try to get admin token via API (this requires admin to already be set up)
admin_token=$(curl -s "$CTFD_URL/api/v1/teams" 2>&1 | grep -oP '"access_token":"\K[^"]+' || echo "")

if [ -z "$admin_token" ]; then
    echo "Error: Could not authenticate with CTFd. Make sure admin is set up."
    echo "Visit http://localhost:8000 and complete the setup first."
    exit 1
fi

echo "Creating challenges in CTFd..."
echo ""

# Load existing challenge names so imports are idempotent.
existing_names=$(curl -s "$CTFD_URL/api/v1/challenges" \
    -H "Authorization: Bearer $admin_token" \
    -H "Content-Type: application/json" | jq -r '.data[]?.name')

created=0
skipped=0
failed=0

# Import each challenge
while IFS= read -r chal_json; do
    [ -n "$chal_json" ] || continue
    chal_id=$(echo "$chal_json" | jq -r '.id')
    chal_name=$(echo "$chal_json" | jq -r '.name')
    chal_runtime=$(echo "$chal_json" | jq -r '.runtime')

    if grep -Fqx -- "$chal_name" <<< "$existing_names"; then
        echo "Skipping: $chal_name (already exists in CTFd)"
        skipped=$((skipped + 1))
        continue
    fi

    # Map runtime to category
    case "$chal_runtime" in
        docker) category="Web" ;;
        kctf) category="Crypto" ;;
        kata) category="Pwn" ;;
        kata-firecracker) category="Pwn" ;;
        *) category="Misc" ;;
    esac

    echo "Creating: $chal_name ($category)"

    # Create challenge via CTFd API
    response=$(curl -s -X POST "$CTFD_URL/api/v1/challenges" \
        -H "Authorization: Bearer $admin_token" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"$chal_name\",
            \"description\": \"Launched via IsolateX. <div data-isolatex-challenge=\\\"$chal_id\\\"></div>\",
            \"category\": \"$category\",
            \"value\": 100,
            \"type\": \"standard\",
            \"state\": \"visible\"
        }")

    chal_db_id=$(echo "$response" | jq -r '.data.id // empty')

    if [ -n "$chal_db_id" ]; then
        echo "  ✓ Created (ID: $chal_db_id)"
        created=$((created + 1))
        existing_names="${existing_names}"$'\n'"${chal_name}"
    else
        echo "  ✗ Failed: $(echo "$response" | jq -r '.errors // .message // "Unknown error"')"
        failed=$((failed + 1))
    fi
done < <(printf "%s\n" "$challenges")

echo ""
echo "Import complete!"
echo "Created: $created, skipped existing: $skipped, failed: $failed"
echo "Visit http://localhost:8000/challenges to see the challenges"
