# IsolateX Architecture

## Overview

```
┌─────────────────────────────────────────────────┐
│                 CTFd (stock)                    │
│  IsolateX plugin injects the instance panel     │
│  Admin UI: Plugins → IsolateX                   │
└─────────────────────┬───────────────────────────┘
                      │ REST (x-api-key)
                      ▼
┌─────────────────────────────────────────────────┐
│         IsolateX Orchestrator (FastAPI)         │
│                                                 │
│  /instances      Launch, stop, restart, renew   │
│  /challenges     Register & configure           │
│  /workers        Worker registry + heartbeat    │
│                                                 │
│  TTL reaper      Auto-destroy on expiry (30s)   │
│  Worker picker   Least-loaded scheduler         │
│  Flag derivation HMAC per team+challenge        │
│  Router          Traefik route registration     │
└──────────┬────────────────┬─────────────────────┘
           │                │
     ┌─────▼──────┐  ┌──────▼──────────────────┐
     │   Docker   │  │  Kubernetes workers      │
     │   worker   │  │  kctf / kata-fc          │
     └─────┬──────┘  └──────┬──────────────────┘
           │                │
    Docker container    K8s pod (nsjail / Kata VM)
```

## Components

### CTFd plugin (`ctfd-plugin/`)

A Flask blueprint mounted into CTFd. It:
- Injects `isolatex.js` into every CTFd HTML page via an `after_request` hook
- Exposes routes that the player's browser calls: `GET/POST/DELETE /isolatex/instance/<challenge_id>` and `/restart`, `/renew`
- Exposes admin routes: `GET/POST /isolatex/admin/config`, `GET/PATCH /isolatex/admin/challenges/<id>`
- Proxies all calls to the orchestrator using a shared API key

The player UI (`isolatex.js`) is a vanilla JS IIFE — no framework. It uses `MutationObserver` to detect when CTFd dynamically renders a challenge modal, then renders the instance panel inside it.

### Orchestrator (`orchestrator/`)

A FastAPI application. It owns:
- **Instance lifecycle** — creates, tracks, and destroys instances
- **Worker registry** — workers self-register and send heartbeats every 30s; the orchestrator picks the least-loaded healthy worker for each launch
- **Challenge registry** — stores image, port, runtime, resource limits, TTL per challenge
- **Flag derivation** — `HMAC-SHA256(secret, team_id:challenge_id:instance_id:salt)`
- **TTL reaper** — background task that runs every 30s and destroys expired instances
- **Routing** — registers/deregisters Traefik routes when instances start/stop

### Workers (`worker/`)

A FastAPI agent that runs on each host. The orchestrator calls `/launch` and `/destroy` on the worker. The worker translates these into runtime-specific operations.

| Worker adapter | File | What it does |
|---|---|---|
| `docker` | `adapters/docker.py` | Runs `docker run` with resource limits and cap-drop |
| `kctf` | `adapters/kctf.py` | Creates a Kubernetes pod with nsjail + network policy |
| `kata-firecracker` | `adapters/kata.py` | Creates a K8s pod with `kata-firecracker` RuntimeClass (Kata + Firecracker) |

Workers advertise their runtime type. The orchestrator only sends `docker` challenges to Docker workers, `kata` challenges to Kata workers, etc.

---

## Request flow — Launch

```
1.  Player clicks Launch in CTFd
2.  isolatex.js → POST /isolatex/instance/<challenge_id>   (CTFd plugin)
3.  Plugin → POST http://orchestrator:8080/instances       (x-api-key)
4.  Orchestrator:
    a. Rejects if team already has a running instance (409)
    b. Looks up challenge record (image, port, runtime, limits, ttl)
    c. Picks least-loaded healthy worker for that runtime
    d. Creates Instance row: status=pending, expires_at=now+ttl
    e. Returns 201 immediately (background task handles the rest)
5.  Worker receives POST /launch → runs container / creates pod
6.  Worker returns { port: <host_port> }
7.  Orchestrator:
    a. Registers route subdomain via Traefik (or uses localhost:<port> for local dev)
    b. Updates Instance: status=running, endpoint=<url>
8.  isolatex.js polls GET /isolatex/instance/<challenge_id> every 5s
9.  Status=running → renders endpoint link + countdown timer
10. TTL reaper (every 30s) → destroys expired instances
```

## TTL flow

```
Launch   → expires_at = started_at + ttl_seconds

Renew    → expires_at = min(now + ttl_seconds, started_at + ttl_seconds)
           (resets to original duration from now, cannot exceed original cap)

Restart  → old instance destroyed
           new instance: expires_at = now + ttl_seconds (full TTL reset)

Reaper   → every 30s: finds instances where expires_at ≤ now
           → calls worker DELETE /destroy/{id}
           → marks instance destroyed, deregisters gateway route
```

## Data layer

| Store | Used for |
|---|---|
| **Postgres** | Instances, challenges, workers (persistent state) |
| **Redis** | CTFd session cache (used by CTFd, not orchestrator directly) |

## Endpoint format

| Environment | Format |
|---|---|
| Local dev (`BASE_DOMAIN=localhost`) | `http://localhost:<host_port>` |
| Production | `https://<instance-prefix>.<challenge-id>.<base-domain>` |

Traefik polls `/traefik/config` every 5 seconds and updates its routing table dynamically. For local dev, Traefik is not used — the worker binds a host port directly and the endpoint is `http://localhost:<port>`.
