# IsolateX Architecture

## Overview

IsolateX is a per-team challenge isolation platform that plugs into CTFd.
When a competitor clicks "Launch Instance," IsolateX spins up a private,
isolated environment just for their team, gives them a unique URL, and
destroys it automatically when the TTL expires.

## ASCII Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Internet / Players                         │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Gateway (Traefik or Nginx)                       │
│  ctf.osiris.sh          → CTFd (scoreboard)                         │
│  ab12cd.web200.ctf...   → Player A's web200 instance                │
│  ef34gh.web200.ctf...   → Player B's web200 instance                │
│  TLS terminated here (Let's Encrypt)                                │
└──────────┬──────────────────────────────────┬───────────────────────┘
           │                                  │
           ▼                                  ▼
┌──────────────────┐                ┌─────────────────────────────────┐
│   CTFd           │  REST API      │   IsolateX Orchestrator         │
│   (stock)        │◄──────────────►│   (FastAPI / Python)            │
│                  │                │                                 │
│  Scoreboard      │  IsolateX      │  • POST /instances (launch)     │
│  Auth            │  plugin        │  • DELETE /instances/{id}       │
│  Challenges      │  injects       │  • TTL reaper (background)      │
│  Flags           │  Launch btn    │  • Worker picker (least-loaded) │
└──────────────────┘                │  • Per-team flag derivation     │
                                    │  • Route registration           │
                                    └──────────────┬──────────────────┘
                                                   │
                                    ┌──────────────┴──────────────────┐
                                    │        Worker Agents            │
                                    │  (one per host, one per runtime)│
                                    │                                 │
                          ┌─────────┴──────────────────────────────┐  │
                          │           POST /launch                 │  │
                          │           DELETE /destroy/{id}         │  │
                          │           GET /health                  │  │
                          │           POST /heartbeat              │  │
                          └─┬───────┬─────────┬──────────┬────────┬┘──┘
                            │       │         │          │        │
                     ┌──────▼─┐  ┌──▼────┐ ┌──▼────┐ ┌───▼───┐ ┌──▼──┐
                     │Docker  │  │ kCTF  │ │Kata + │ │Kata + │ │ Raw │
                     │        │  │ Pod   │ │  k8s  │ │ FC    │ │ FC  │
                     │ weak   │  │medium │ │strong │ │ very  │ │full │
                     │        │  │       │ │       │ │strong │ │     │
                     │        │  │       │ │       │ │       │ │     │
                     └────────┘  └───────┘ └───────┘ └───────┘ └─────┘
                (guest kernel)   (nsjail+     (nsjail+ (KVM     (KVM +
                                NetworkPol)    Firecracker)    direct)

┌─────────────────────────────────────────────────────────────────────┐
│                     Data Layer                                      │
│   Postgres — instance state, workers, challenges                    │
│   Redis    — session cache, lease tracking                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Security Boundaries

| Layer | Mechanism | What it prevents |
|---|---|---|
| Transport | TLS (Let's Encrypt) | Eavesdropping |
| Authentication | CTFd auth + team session | Unauthorized access |
| Instance isolation | Firecracker/kCTF/Docker | One team reaching another's runtime |
| Network isolation | Gateway routing + NetworkPolicy + Docker ICC=false | East-west traffic between instances |
| Compute limits | CPU/RAM caps per instance | Resource exhaustion DoS |
| Flag isolation | Per-team HMAC-derived flag | Sharing one flag to solve for others |
| Lifecycle | TTL auto-destroy + volume wipe | Stale instances leaking state |
| Worker separation | Worker can only talk to orchestrator, not between workers | Lateral movement |

## Request Flow

```
1. Player logs in to CTFd (CTFd handles all auth)
2. Player views a challenge with isolatex:true tag
3. IsolateX JS widget appears: "Launch Instance"
4. Player clicks Launch
5. CTFd plugin → POST /isolatex/instance/<challenge_id>
6. Plugin → POST orchestrator/instances {team_id, challenge_id}
7. Orchestrator:
   a. Checks no existing running instance for this team+challenge
   b. Looks up challenge config (runtime, image, limits)
   c. Picks least-loaded worker for that runtime
   d. Creates Instance record (status=pending)
   e. Fires background task to call worker
8. Worker agent receives POST /launch
9. Worker launches Firecracker/Docker/kCTF pod
10. Worker returns {port: NNNNN}
11. Orchestrator registers route with gateway
12. Orchestrator updates Instance: status=running, endpoint=https://...
13. CTFd plugin polls GET /isolatex/instance/<challenge_id> every 5s
14. Status becomes "running" → shows endpoint + TTL countdown to player
15. TTL expires → reaper calls worker DELETE /destroy/<id>
16. Worker tears down runtime, wipes volumes
17. Orchestrator marks instance destroyed, deregisters gateway route
```

## Component Map

```
IsolateX/
  orchestrator/        FastAPI control plane
    api/               HTTP endpoints
    core/              business logic (flags, routing, scheduler, worker-picker)
    db/                SQLAlchemy models + session

  worker/              FastAPI agent (runs on compute hosts)
    adapters/          Runtime implementations
      base.py          RuntimeAdapter interface (implement this for new runtimes)
      docker.py        Docker container adapter
      kctf.py          Kubernetes + nsjail adapter
      kata.py          Kubernetes + Kata (guest kernel) adapter
      firecracker.py   Firecracker microVM adapter (direct)
      cloud_hypervisor.py  Cloud Hypervisor adapter (direct)
      __init__.py      Registry — add new runtimes here
    networking/        tap device helpers (microVMs)

  ctfd-plugin/         CTFd plugin
    __init__.py        Flask blueprints + proxy calls to orchestrator
    assets/isolatex.js Launch/Stop UI widget

  gateway/
    traefik/           Traefik static + dynamic config
    nginx/             Nginx config + reload sidecar

  infra/
    kctf/              kCTF fresh cluster setup + manifests
    firecracker/       Kernel + rootfs build scripts
    scripts/           check-hardware.sh

  docs/                All documentation
    csaw-deployment.md CSAW event-specific deployment guide
    kata-setup.md      Kata Containers setup guide
```
