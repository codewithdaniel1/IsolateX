#!/bin/bash
# Import challenges from orchestrator into CTFd database directly

set -euo pipefail

ORCHESTRATOR_URL="${1:-http://localhost:8080}"
ORCHESTRATOR_KEY="${2:-dev-api-key-change-in-prod}"
DB_HOST="${3:-127.0.0.1}"
DB_PORT="${4:-3306}"
DB_USER="${5:-ctfd}"
DB_PASS="${6:-ctfd}"
DB_NAME="${7:-ctfd}"

echo "Fetching challenges from orchestrator..."

# Create temporary SQL file
sql_file=$(mktemp)
trap "rm -f $sql_file" EXIT

{
    echo "USE \`$DB_NAME\`;"
    echo "SET FOREIGN_KEY_CHECKS=0;"

    curl -s "$ORCHESTRATOR_URL/challenges" \
        -H "x-api-key: $ORCHESTRATOR_KEY" | jq -r '.[] |
        @sh "INSERT INTO challenges (name, description, category, value, type, state) VALUES (\(.name | @csv), \(\"Launched via IsolateX <div data-isolatex-challenge=\\\"\(.id)\\\"></div>\" | @csv), \"Web\", 100, \"standard\", \"visible\");"' | \
        sed "s/'//g"

    echo "SET FOREIGN_KEY_CHECKS=1;"
} > "$sql_file"

echo "Importing into CTFd database..."
echo ""

# Execute SQL
if mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" < "$sql_file" 2>/dev/null; then
    echo "✓ Challenges imported successfully"
    echo ""
    echo "Challenges in CTFd:"
    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" \
        -se "SELECT name FROM challenges ORDER BY id DESC LIMIT 10;" 2>/dev/null || echo "(Could not verify)"
else
    echo "✗ Failed to import challenges"
    exit 1
fi
