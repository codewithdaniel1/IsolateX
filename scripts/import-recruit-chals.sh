#!/bin/bash
# Import Recruit CTF challenges into IsolateX

set -euo pipefail

RECRUIT_DIR="${1:?Usage: $0 <path-to-recruit-chals>}"
ORCHESTRATOR_URL="${2:-http://localhost:8080}"
API_KEY="${3:-dev-api-key-change-in-prod}"

if [ ! -d "$RECRUIT_DIR" ]; then
    echo "Error: $RECRUIT_DIR not found"
    exit 1
fi

echo "Importing challenges from $RECRUIT_DIR..."
echo ""

# All recruit challenges use docker runtime
runtime="docker"

# For each category directory
for category_dir in "$RECRUIT_DIR"/{web,crypto,intro,rev,pwn}; do
    [ -d "$category_dir" ] || continue

    category=$(basename "$category_dir" | sed 's/.*/\U&/')

    echo "▸ Category: $category (runtime: $runtime)"

    # For each challenge in the category
    for chal_dir in "$category_dir"/*; do
        [ -d "$chal_dir" ] || continue
        [ -f "$chal_dir/challenge.json" ] || continue

        chal_name=$(basename "$chal_dir")
        chal_json="$chal_dir/challenge.json"
        dockerfile="$chal_dir/Dockerfile"

        # Extract challenge metadata
        id=$(jq -r '.name // empty' "$chal_json")
        name=$(jq -r '.name // empty' "$chal_json")
        port=$(jq -r '.internal_port // 80' "$chal_json")

        [ -z "$id" ] && continue

        # Build Docker image
        image_name="recruit-$(echo "$category" | tr '[:upper:]' '[:lower:]')-$id"
        echo "  Building $image_name..."

        if docker build -q -t "$image_name" "$chal_dir" 2>/dev/null; then
            # Register with orchestrator
            echo "  Registering $id with IsolateX..."

            curl -s -X POST "$ORCHESTRATOR_URL/challenges" \
                -H "x-api-key: $API_KEY" \
                -H "content-type: application/json" \
                -d "{
                    \"id\": \"$id\",
                    \"name\": \"$name\",
                    \"runtime\": \"$runtime\",
                    \"image\": \"$image_name\",
                    \"port\": $port,
                    \"cpu_count\": 1,
                    \"memory_mb\": 512
                }" > /dev/null

            echo "  ✓ $id"
        else
            echo "  ✗ Failed to build $image_name"
        fi
    done

    echo ""
done

echo "Import complete!"
echo ""
echo "Registered challenges:"
curl -s "$ORCHESTRATOR_URL/challenges" \
    -H "x-api-key: $API_KEY" | jq -r '.[] | "\(.id) - \(.name) (\(.runtime))"'
