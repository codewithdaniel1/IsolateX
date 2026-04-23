# IsolateX Architecture

## Big Picture

### What each part does

- **Player browser**: where competitors use the CTF website.
- **CTFd + IsolateX plugin**: the app UI (launch, stop, renew, restart).
- **Traefik (reverse proxy)**: the only public front door.
- **Orchestrator**: the manager that creates and tracks instances.
- **Workers**: services that actually start/stop challenge environments.
- **Challenge backend**: the isolated runtime for one team (container/pod/VM).

### Diagram

```
Player
  │
  ▼
Traefik (reverse proxy)
  │
  ├─ sends CTF site traffic to CTFd
  └─ sends challenge traffic to the team's running backend
       (only after access is checked)

CTFd + IsolateX plugin
  │
  ▼
Orchestrator (manager)
  │
  ▼
Workers (docker / kctf / kata)
  │
  ▼
Isolated team backend
```

### When a player clicks Launch

1. Player clicks **Launch** in CTFd.
2. CTFd plugin asks orchestrator to create an instance for that team.
3. Orchestrator selects a worker and tells it to start the backend.
4. Worker starts an isolated backend and reports where it is running.
5. Orchestrator updates routing info for Traefik.
6. Player opens the instance URL through Traefik.

### When a player opens an instance URL

1. Request reaches Traefik first.
2. Traefik asks CTFd if this logged-in user is allowed to access that instance.
3. If allowed, Traefik forwards traffic directly to that team’s backend.
4. If not allowed, access is denied.

### How authentication works (and does not work)

- Access is **not** based on player IP address.
- Access is based on the player's **CTFd login session** (cookie/session).
- CTFd resolves who the user/team is from that session.
- Traefik only forwards traffic if that session's team matches the team that owns the instance.
- A player cannot simply edit a request and change `team_id` to jump into another team's box, because team identity is derived server-side from the CTFd session, not trusted from browser input.
- Session lifetime is controlled by CTFd (`PERMANENT_SESSION_LIFETIME`), not by IsolateX routing logic.

If this protection fails, it is usually due to account/session compromise (for example stolen CTFd session cookie), not normal request tampering.

### One key idea

- **Orchestrator is for management**, not for serving live challenge traffic.
- Live challenge traffic is: **Player -> Traefik -> team backend**.

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
- Exposes a reverse-proxy auth endpoint: `GET /isolatex/authz` (session/team ownership check)
- Exposes admin routes: `GET/POST /isolatex/admin/config`, `GET /isolatex/admin/runtime-capabilities`, `GET/PATCH /isolatex/admin/challenges/<id>`
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
| `docker` | `adapters/docker.py` | Runs `docker run` on a per-instance private network (no host port publishing) |
| `kctf` | `adapters/kctf.py` | Creates a Kubernetes pod + ClusterIP service with nsjail + network policy |
| `kata-firecracker` | `adapters/kata.py` | Creates a K8s pod + ClusterIP service with `kata-firecracker` RuntimeClass |

Workers advertise their runtime type. The orchestrator only sends `docker` challenges to Docker workers, `kctf` challenges to kCTF workers, and `kata-firecracker` challenges to Kata workers.

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
6.  Worker returns { backend_host, backend_port } (internal target only)
7.  Orchestrator:
    a. Registers route subdomain via Traefik
    b. Attaches per-instance forward-auth middleware to enforce team ownership
    c. Updates Instance: status=running, endpoint=<url>
8.  isolatex.js polls GET /isolatex/instance/<challenge_id> every 5s
9.  Status=running → renders endpoint link + countdown timer
10. TTL reaper (every 30s) → destroys expired instances
```

## TTL flow

```
Launch   → expires_at = started_at + ttl_seconds

Renew    → expires_at = now + ttl_seconds
           (resets to full challenge TTL from the current time)

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
| Local dev (`BASE_DOMAIN=localhost`) | `http://<instance-prefix>.<challenge-id>.localhost` |
| Production | `https://<instance-prefix>.<challenge-id>.<base-domain>` |

Traefik polls `/traefik/config` every 5 seconds and updates its routing table dynamically. Challenge backends are internal-only (no direct host/node-port exposure) and are reached only through the reverse proxy.
