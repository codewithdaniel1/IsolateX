#!/usr/bin/env python3
"""Import challenges from orchestrator into CTFd database"""

import sys
import subprocess
import json
import requests
from urllib.parse import urljoin

def main():
    orchestrator_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    orchestrator_key = sys.argv[2] if len(sys.argv) > 2 else "dev-api-key-change-in-prod"
    db_host = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
    db_port = sys.argv[4] if len(sys.argv) > 4 else "3306"
    db_user = sys.argv[5] if len(sys.argv) > 5 else "ctfd"
    db_pass = sys.argv[6] if len(sys.argv) > 6 else "ctfd"
    db_name = sys.argv[7] if len(sys.argv) > 7 else "ctfd"

    print("Fetching challenges from orchestrator...")

    # Get challenges from orchestrator
    response = requests.get(
        f"{orchestrator_url}/challenges",
        headers={"x-api-key": orchestrator_key}
    )
    challenges = response.json()

    if not challenges:
        print("No challenges found")
        return 1

    print(f"Found {len(challenges)} challenges")
    print("Importing into CTFd database...\n")

    # Build SQL statements
    sql_statements = []
    sql_statements.append("SET FOREIGN_KEY_CHECKS=0;")

    for chal in challenges:
        chal_id = chal["id"]
        chal_name = chal["name"]
        description = f'Launched via IsolateX <div data-isolatex-challenge="{chal_id}"></div>'

        # Escape quotes for SQL
        description = description.replace('"', '\\"')
        chal_name = chal_name.replace("'", "''")
        description = description.replace("'", "''")

        sql = f"""INSERT INTO challenges (name, description, category, value, type, state)
                  VALUES ('{chal_name}', '{description}', 'Web', 100, 'standard', 'visible');"""
        sql_statements.append(sql)
        print(f"  ✓ {chal_name}")

    sql_statements.append("SET FOREIGN_KEY_CHECKS=1;")

    # Execute SQL
    sql_script = "\n".join(sql_statements)

    try:
        proc = subprocess.run(
            ["mysql", "-h", db_host, "-P", db_port, "-u", db_user, f"-p{db_pass}", db_name],
            input=sql_script.encode(),
            capture_output=True,
            timeout=10
        )

        if proc.returncode == 0:
            print("\n✓ Challenges imported successfully")
            print("\nChallenges in CTFd:")

            # Verify
            proc = subprocess.run(
                ["mysql", "-h", db_host, "-P", db_port, "-u", db_user, f"-p{db_pass}", db_name, "-se",
                 "SELECT name FROM challenges ORDER BY id DESC LIMIT 10;"],
                capture_output=True,
                timeout=10
            )
            if proc.returncode == 0:
                for line in proc.stdout.decode().strip().split("\n"):
                    if line:
                        print(f"  - {line}")
            return 0
        else:
            print(f"✗ Failed: {proc.stderr.decode()}")
            return 1

    except FileNotFoundError:
        print("✗ mysql command not found. Install MySQL client:")
        print("  brew install mysql-client")
        return 1
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
