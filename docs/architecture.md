# IsolateX Architecture

## Overview

IsolateX is a thin connector between CTFd and Kubernetes. It does not replace Kubernetes — Kubernetes is the orchestrator. IsolateX handles the CTFd-facing API, per-team instance mapping, TTL enforcement, flag derivation, and gateway routing.

## Stack

```
┌──────────────────────────────────────────────────────┐
│                    CTFd (stock)                      │
│   IsolateX plugin injects the instance panel         │
└──────────────────────┬───────────────────────────────┘
                       │ REST (x-api-key)
                       ▼
┌──────────────────────────────────────────────────────┐
│              IsolateX Orchestrator (FastAPI)          │
│                                                      │
│  POST /instances          Launch instance            │
│  GET  /instances/team/... Check status               │
│  DELETE /instances/{id}   Stop instance              │
│  POST /instances/{id}/restart  Restart (TTL reset)   │
│  POST /instances/{id}/renew    Extend TTL            │
│                                                      │
│  TTL reaper (background)  Auto-destroy on expiry     │
│  Worker picker            Least-loaded scheduler     │
│  Flag derivation          HMAC per team+challenge    │
└──────────────────────┬───────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────────────┐
    │  Docker  │ │   kCTF   │ │  Kata / Kata+FC  │
    │  worker  │ │  worker  │ │     worker       │
    └──────────┘ └──────────┘ └──────────────────┘
          │            │                │
          ▼            ▼                ▼
    Container     K8s pod +       K8s pod +
                   nsjail        Kata VM
                                (QEMU or Firecracker
                                 as Kata backend)
```

## Runtime model

All four runtimes are Kubernetes-native. Workers are FastAPI agents that receive `/launch` and `/destroy` calls from the orchestrator and translate them into Kubernetes API calls.

```
docker          → containerd → runc → container
kctf            → containerd → runc → container + nsjail
kata            → containerd → Kata runtime → QEMU/CHV → guest VM → container
kata-firecracker → containerd → Kata runtime → Firecracker → guest VM → container
```

For `kata` and `kata-firecracker`, Kata Containers creates a lightweight VM per pod. The VM has its own kernel. The hypervisor (QEMU vs Firecracker) is a Kata configuration detail — Kubernetes just sees a pod with a RuntimeClass.

## TTL flow

```
Instance created → expires_at = now + ttl_seconds
                                (challenge override or global 30-min default)

Player clicks Renew → expires_at += ttl_seconds
                      (capped: expires_at ≤ now + 2h)

Player clicks Restart → old instance destroyed
                        new instance created, expires_at = now + ttl_seconds

TTL reaper (every 30s) → finds instances where expires_at ≤ now
                          calls worker DELETE /destroy/{id}
                          marks instance destroyed
                          deregisters gateway route
```

## Request flow (launch)

```
1. Player clicks Launch in CTFd
2. CTFd plugin → POST /isolatex/instance/<challenge_id>
3. Plugin → POST orchestrator/instances {team_id, challenge_id}
4. Orchestrator:
   a. Checks no existing running instance for this team+challenge
   b. Looks up challenge (runtime, image, resource limits, ttl_seconds)
   c. Picks least-loaded worker for that runtime
   d. Creates Instance record (status=pending, expires_at set)
   e. Fires background task → POST worker/launch
5. Worker launches pod (Docker / kCTF / Kata)
6. Worker returns {port}
7. Orchestrator registers route with Traefik
8. Orchestrator updates Instance: status=running, endpoint=https://...
9. CTFd plugin polls GET /isolatex/instance/<challenge_id> every 5s
10. Status = running → shows endpoint + countdown timer
11. TTL expires → reaper destroys instance, deregisters route
```

## Data layer

- **Postgres** — instance state, workers, challenges
- **Redis** — session cache, rate limiting (optional)

## Gateway

Traefik polls the orchestrator's `/traefik/config` endpoint every 5 seconds and updates routes dynamically. Each instance gets a unique subdomain:

```
<instance-id-prefix>.<challenge-id>.<base-domain>
e.g. ab12cd34.web100.ctf.osiris.sh
```
