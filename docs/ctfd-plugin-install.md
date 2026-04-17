# CTFd Plugin Installation

## Install

```bash
# From the IsolateX repo root
cp -r ctfd-plugin/ <path-to-CTFd>/CTFd/plugins/isolatex/

# Or if using Docker Compose (already wired in docker-compose.yml):
# The plugin directory is volume-mounted into CTFd automatically.
```

## Configure

Set these environment variables on the CTFd container:

| Variable | Description | Example |
|---|---|---|
| `ISOLATEX_URL` | Orchestrator URL | `http://orchestrator:8080` |
| `ISOLATEX_API_KEY` | Shared API key | `your-secret-key` |

## Add the widget to a challenge

In CTFd admin → Challenges → (your challenge) → Description, add:

```html
<div data-isolatex-challenge data-challenge-id="web300">
  <!-- IsolateX will render the Launch Instance button here -->
</div>
```

The `data-challenge-id` must match the challenge ID registered with the orchestrator.

## How it works

The plugin adds two things to CTFd:
1. A Flask blueprint at `/isolatex/*` that proxies to the orchestrator API
2. A JavaScript widget (`isolatex.js`) that renders the Launch/Stop UI and polls for instance status

The plugin does NOT handle auth — it uses CTFd's existing session.
The orchestrator derives team ID from the CTFd team or user ID.

## Registering a challenge with the orchestrator

Before a challenge can be launched, it must exist in the orchestrator:

```bash
curl -X POST http://orchestrator:8080/challenges \
  -H "x-api-key: $API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "id": "web300",
    "name": "Web 300",
    "runtime": "docker",
    "image": "ghcr.io/osiris/web300:latest",
    "cpu_count": 1,
    "memory_mb": 512,
    "port": 8080,
    "ttl_seconds": 3600
  }'
```

The `id` here must match the `data-challenge-id` in the CTFd description.
