# IsolateX

**Per-team challenge instancing for CTFd.**

IsolateX gives every team their own isolated challenge environment — players click "Launch," get a private endpoint and countdown timer, and the instance auto-stops when time runs out. It works with Docker for local dev and Kubernetes-based runtimes for production.

---

## What players see

- **Launch** — starts a private instance
- **Restart** — kills and relaunches with a fresh TTL
- **Renew** — resets the timer back to the original duration (cannot exceed the original TTL from launch)
- **Stop** — destroys the instance early
- **Countdown timer** — live "Expires in 23m 14s" display

---

## Supported runtimes

| Runtime | Container tech | Isolation | Best for |
|---|---|---|---|
| `docker` | Docker (runc) | Basic | Web, crypto, reversing — local dev |
| `kctf` | Kubernetes pod + nsjail | Medium | Web, pwn with moderate risk |
| `kata` | Kubernetes + Kata (QEMU backend) | Strong | Pwn, RCE challenges |
| `kata-firecracker` | Kubernetes + Kata (Firecracker backend) | Strongest | Kernel pwn, AI code execution |

**Choosing a runtime:**
- Start with `docker` for local dev — no Kubernetes needed.
- Use `kctf` for most production challenges.
- Use `kata` or `kata-firecracker` for anything where a player gets shell access or can trigger arbitrary code execution.

---

## Resource tiers

Set per-challenge in the admin panel (Plugins → IsolateX):

| Tier | CPU | Memory | When to use |
|---|---|---|---|
| Tier 1 | 0.5 cores | 256 MB | Static web, trivial challenges |
| Tier 2 | 1 core | 512 MB | Typical web / reversing |
| Tier 3 | 2 cores | 1 GB | Pwn, heavier web |
| Tier 4 | 4 cores | 2 GB | AI, compilation, heavy compute |

---

## Quick start (local dev, 5 minutes)

```bash
git clone https://github.com/osiris/isolatex
cd isolatex
docker compose up -d
```

Then go to [http://localhost:8000](http://localhost:8000) to set up CTFd.

Full walkthrough → [docs/setup.md](docs/setup.md)

---

## Documentation

| Doc | Audience |
|---|---|
| [docs/setup.md](docs/setup.md) | **Start here** — local dev → production, adding challenges |
| [docs/architecture.md](docs/architecture.md) | How the pieces fit together |
| [docs/api-reference.md](docs/api-reference.md) | Orchestrator REST API |
| [docs/security-model.md](docs/security-model.md) | Isolation model and threat model |
| [docs/kctf-setup.md](docs/kctf-setup.md) | *(Operators)* Kubernetes / kCTF cluster setup |
| [docs/kata-setup.md](docs/kata-setup.md) | *(Operators)* Kata Containers setup |

---

## Project layout

```
orchestrator/         FastAPI backend
  api/                REST endpoints: instances, challenges, workers
  core/               TTL reaper, worker scheduler, flag derivation, routing
  db/                 SQLAlchemy models

worker/               Worker agent (runs per host / per runtime)
  adapters/
    docker.py         Docker runtime
    kctf.py           Kubernetes + nsjail runtime
    kata.py           Kata Containers runtime (kata + kata-firecracker)

ctfd-plugin/          CTFd integration
  __init__.py         Flask blueprint + admin UI routes
  assets/isolatex.js  Player-facing panel (Launch/Stop/Restart/Renew + timer)
  templates/
    admin.html        Admin settings page (Plugins → IsolateX)

gateway/
  traefik/            Traefik HTTP provider config
  nginx/              Nginx alternative

docs/                 Documentation
```

---

## Security model (short version)

- **1 team = 1 instance** — enforced at the orchestrator (409 on duplicate)
- **Per-team flags** — HMAC(secret + team\_id + challenge\_id + instance\_id + salt); sharing a flag helps nobody
- **Auto-cleanup** — TTL reaper runs every 30s, destroys expired instances
- **Network isolation** — containers on an isolated bridge with ICC disabled; Kubernetes NetworkPolicy default-deny in production
- **Kata isolation** — each pod runs inside its own VM with its own kernel

Full details → [docs/security-model.md](docs/security-model.md)
