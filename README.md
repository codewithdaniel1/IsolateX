# IsolateX

**Per-team challenge instancing for CTFd.**

IsolateX is a CTFd plugin + backend service that gives every team their own isolated challenge environment. Players click "Launch," get a private endpoint, and the instance auto-expires when the timer runs out.

It connects CTFd to Kubernetes-based runtimes ranging from standard containers to Kata Containers with Firecracker — no raw VM management required.

---

## How it works

```
Player clicks "Launch" in CTFd
        ↓
CTFd plugin → IsolateX backend
        ↓
Backend picks runtime + schedules on Kubernetes
        ↓
Player gets: endpoint URL + countdown timer
        ↓
Timer hits zero → instance auto-destroyed
```

---

## What players see

- **Launch** — starts a private instance
- **Restart** — kills and relaunches (TTL resets to full)
- **Renew** — extends the timer (up to a 2-hour hard cap)
- **Stop** — destroys instance early
- **Countdown** — live "Expires in 23m 14s" timer

---

## Supported runtimes

| Runtime | What it is | Isolation |
|---|---|---|
| `docker` | Standard container | ⭐⭐ |
| `kctf` | Kubernetes pod + nsjail | ⭐⭐⭐ |
| `kata` | kCTF + Kata (guest kernel via QEMU) | ⭐⭐⭐⭐ |
| `kata-firecracker` | kCTF + Kata (guest kernel via Firecracker backend) | ⭐⭐⭐⭐+ |

All four are Kubernetes-native. `kata` and `kata-firecracker` both use Kata Containers — the only difference is which hypervisor Kata uses under the hood. Both give each workload its own kernel.

Choose based on the challenge risk level:
- Web, crypto, reversing → `kctf` or `kata`
- Pwn, RCE, AI code execution → `kata-firecracker`

---

## TTL (auto-stop timer)

- **Global default:** 30 minutes
- **Per-challenge override:** set `ttl_seconds` when registering a challenge
- **Renew:** players can extend their timer, but never past **2 hours** from the current time
- **Restart:** resets TTL to the full challenge default

---

## Quick start (local dev)

```bash
# 1. Clone and start the full stack
git clone https://github.com/osiris/isolatex
cd isolatex
docker compose up -d

# 2. Register a test challenge
curl -X POST http://localhost:8080/challenges \
  -H "x-api-key: dev-api-key-change-in-prod" \
  -H "content-type: application/json" \
  -d '{
    "id": "test-web",
    "name": "Test Web",
    "runtime": "docker",
    "image": "nginx:alpine",
    "port": 80
  }'

# 3. Open CTFd
open http://localhost:8000
```

CTFd already has the IsolateX plugin mounted via `docker-compose.yml`.

---

## Documentation

- [docs/setup.md](docs/setup.md) — full setup guide (local → production)
- [docs/kctf-setup.md](docs/kctf-setup.md) — Kubernetes / kCTF cluster setup
- [docs/kata-setup.md](docs/kata-setup.md) — Kata Containers setup (both runtimes)
- [docs/architecture.md](docs/architecture.md) — how it all fits together
- [docs/api-reference.md](docs/api-reference.md) — orchestrator API reference
- [docs/security-model.md](docs/security-model.md) — isolation model and threat model

---

## Project layout

```
orchestrator/       FastAPI backend (the IsolateX service)
  api/              REST endpoints: instances, workers, challenges
  core/             Flags, routing, TTL reaper, worker picker
  db/               SQLAlchemy models (Instance, Challenge, Worker)

worker/             Worker agent — runs on each Kubernetes node
  adapters/         Runtime implementations
    docker.py       Standard container adapter
    kctf.py         Kubernetes pod + nsjail adapter
    kata.py         Kata adapter (handles both kata and kata-firecracker)

ctfd-plugin/        CTFd integration
  __init__.py       Flask blueprint (Launch / Stop / Restart / Renew routes)
  assets/
    isolatex.js     UI panel with countdown timer

gateway/            Ingress
  traefik/          Traefik HTTP provider config (recommended)
  nginx/            Nginx + reload sidecar (alternative)

infra/
  kctf/             Cluster setup scripts and manifests
  scripts/          Hardware capability checker

docs/               Documentation
```

---

## Security model (short version)

- **1 team = 1 instance** — enforced at the orchestrator
- **Per-team flags** — HMAC(team\_id + challenge\_id + instance\_id + salt), sharing one flag helps nobody
- **Auto-cleanup** — TTL reaper runs every 30s, kills expired instances
- **Network isolation** — Kubernetes NetworkPolicy default-deny between pods
- **Kata isolation** — each pod runs inside its own VM with its own kernel

Full details: [docs/security-model.md](docs/security-model.md)
