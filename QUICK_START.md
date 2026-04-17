# IsolateX Quick Start

## TL;DR

```bash
# Local dev (5 min)
docker compose up -d
curl http://localhost:8080/health

# CSAW deployment (follow csaw-deployment.md)
./infra/kctf/setup-cluster.sh         # setup kCTF cluster
./infra/scripts/check-hardware.sh     # check Firecracker hosts
# Follow docs/csaw-deployment.md step-by-step
```

---

## Architecture at a glance

```
CTFd scoreboard
  ↓ (player clicks "Launch Instance")
IsolateX plugin
  ↓ (REST API call)
Orchestrator (FastAPI)
  ├─ kata+kCTF tier (easy/medium)
  └─ kata+FC / FC tier (hard)
```

---

## For CSAW

**Two-tier setup:**

| Tier | Runtime | Challenges | Isolation |
|---|---|---|---|
| Easy/Medium | Kata + kCTF | web, crypto, rev | ⭐⭐⭐⭐ |
| Hard | Kata + FC / FC | pwn, RCE, AI | ⭐⭐⭐⭐⭐ |

See `docs/csaw-deployment.md` for the full playbook.

---

## Documentation

| Doc | Purpose |
|---|---|
| `IMPLEMENTATION.md` | What was built and why |
| `docs/STRATEGY.md` | Architecture philosophy |
| `docs/csaw-deployment.md` | **CSAW deployment (step-by-step)** |
| `docs/architecture.md` | Full system diagram |
| `docs/security-model.md` | Threat model |

---

## Key files

```
orchestrator/main.py              ← REST API
worker/adapters/                  ← runtime implementations
  ├── kata.py                     ← Kata Containers (NEW)
  ├── firecracker.py              ← Firecracker microVMs
  ├── kctf.py                     ← Kubernetes pods
  └── docker.py                   ← containers
gateway/                          ← Traefik + Nginx
ctfd-plugin/                      ← CTFd integration
infra/                            ← setup scripts
```

---

## One command to start everything

```bash
cd /Users/danielpeng/Downloads/IsolateX
docker compose up -d
```

Then:
- CTFd: http://localhost:8000
- Orchestrator API: http://localhost:8080/docs
- Traefik: http://localhost:80

---

## When you're ready for CSAW

Follow `docs/csaw-deployment.md` (it's a checklist).

Good luck! 🚀
