#!/bin/bash
# Import challenges from orchestrator into CTFd

set -euo pipefail

ORCHESTRATOR_URL="${1:-http://localhost:8080}"
CTFD_URL="${2:-http://localhost:8000}"
ORCHESTRATOR_KEY="${3:-dev-api-key-change-in-prod}"

echo "Fetching challenges from orchestrator..."
challenges=$(curl -s "$ORCHESTRATOR_URL/challenges" \
  -H "x-api-key: $ORCHESTRATOR_KEY" | jq -r '.[]')

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

# Import each challenge
echo "$challenges" | while IFS= read -r chal_json; do
    chal_id=$(echo "$chal_json" | jq -r '.id')
    chal_name=$(echo "$chal_json" | jq -r '.name')
    chal_runtime=$(echo "$chal_json" | jq -r '.runtime')

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
    else
        echo "  ✗ Failed: $(echo "$response" | jq -r '.errors // .message // "Unknown error"')"
    fi
done

echo ""
echo "Import complete!"
echo "Visit http://localhost:8000/challenges to see the challenges"
