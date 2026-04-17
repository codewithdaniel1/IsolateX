# IsolateX

Per-team challenge isolation platform for CTFd.
Built for OSIRIS / CSAW-style CTF events.

## What it does

When a competitor clicks "Launch Instance," IsolateX spins up a private, isolated
environment just for their team, gives them a unique URL, enforces a TTL, and
destroys it automatically when time runs out.

## Runtime Spectrum

IsolateX supports multiple isolation strategies. Choose based on your threat model, cost, and operational capacity:

| Runtime | Type | Best for | Isolation | Cost |
|---|---|---|---|---|
| **Docker** | container | static web, beginner | ⭐⭐ | $ |
| **kCTF** | Kubernetes pod + nsjail | most challenges | ⭐⭐⭐ | $$ |
| **Kata + kCTF** | Kubernetes + guest kernel | medium-risk challenges | ⭐⭐⭐⭐ | $$$ |
| **Kata + Firecracker** | Kubernetes routing + microVM | hard challenges (pwn, RCE, AI) | ⭐⭐⭐⭐⭐ | $$$$ |
| **Raw Firecracker** | microVM (KVM, direct) | extreme isolation, full control | ⭐⭐⭐⭐⭐ | $$$$$ |

Adding a new runtime takes one file. See [docs/adding-a-runtime.md](docs/adding-a-runtime.md).

## Supported gateways

- **Traefik** (recommended) — HTTP provider, zero-downtime route updates
- **Nginx** — file-based config + reload sidecar

## Architecture

```
Players → Gateway (Traefik/Nginx, TLS) 
                            → CTFd
                            → IsolateX Orchestrator
                            ↓ (policy-driven routing)
        ┌──────────┬────────┼─────────┬──────────┐
        ↓          ↓        ↓         ↓          ↓
      Docker      kCTF    Kata+k8s  Kata+FC   Firecracker
   container      pod     (guest kernel)    (direct microVM)
(weak isolation) (medium)  (strong)        (strongest)
```

Full diagram: [docs/architecture.md](docs/architecture.md)

## Quick start

```bash
# Check what your host supports
./infra/scripts/check-hardware.sh

# Start the full dev stack (Docker worker, orchestrator, CTFd, Traefik)
docker compose up -d

# Register a test challenge
curl -X POST http://localhost:8080/challenges \
  -H "x-api-key: dev-api-key-change-in-prod" \
  -H "content-type: application/json" \
  -d '{"id":"test","name":"Test","runtime":"docker","image":"nginx:alpine","port":80}'

# Install the CTFd plugin
# (already mounted via docker-compose.yml — no extra step needed in dev)
```

CTFd: http://localhost:8000
Orchestrator API: http://localhost:8080/docs

## Documentation

**Start here:**
- [docs/architecture.md](docs/architecture.md) — Full architecture + ASCII diagram + request flow

**Event deployment:**
- [docs/csaw-deployment.md](docs/csaw-deployment.md) — **CSAW 2026 deployment guide** (Kata + kCTF + Kata + Firecracker)

**Setup guides:**
- [docs/kctf-setup.md](docs/kctf-setup.md) — Fresh kCTF / Kubernetes cluster setup
- [docs/kata-setup.md](docs/kata-setup.md) — Kata Containers configuration for guest kernel isolation
- [docs/firecracker-host-setup.md](docs/firecracker-host-setup.md) — Host prep for Firecracker workers

**Operations:**
- [docs/deployment.md](docs/deployment.md) — Dev → staging → production deployment guide
- [docs/security-model.md](docs/security-model.md) — Threat model, isolation boundaries, controls checklist
- [docs/api-reference.md](docs/api-reference.md) — Full orchestrator API reference

**Extensibility:**
- [docs/adding-a-runtime.md](docs/adding-a-runtime.md) — How to add any new runtime (gVisor, QEMU, etc.)

## Repo structure

```
orchestrator/     FastAPI control plane (instances, workers, challenges, TTL reaper)
worker/           Worker agent + runtime adapters
  adapters/       firecracker.py, cloud_hypervisor.py, kctf.py, docker.py
ctfd-plugin/      CTFd plugin (Flask blueprint + JS widget)
gateway/          Traefik and Nginx configs
infra/
  kctf/           Kubernetes manifests + cluster setup script
  firecracker/    Kernel + rootfs build scripts
  scripts/        check-hardware.sh
docs/             All documentation
docker-compose.yml   Full dev stack
```

## CSAW 2026 Configuration

IsolateX powers OSIRIS's CSAW CTF event with a two-tier approach:

- **Easy/Medium challenges** (web, crypto, rev) → Kata + kCTF
  - Cost-efficient, strong isolation via guest kernel, standard Kubernetes lifecycle
- **Hard challenges** (pwn, RCE, AI/code execution) → Kata + Firecracker
  - Dedicated microVMs, kernel-level isolation, strongest blast radius containment

This balances security, cost, and operational complexity for a time-limited university CTF event.

## Key security properties

- 1 team = 1 isolated environment (enforced at orchestrator layer)
- Per-team HMAC-derived flags (leaking one flag helps no one else)
- Auto-destroy on TTL expiry (no stale instances)
- Default-deny east-west network traffic between instances
- No instance can reach the orchestrator or worker agent
- Let's Encrypt TLS — no self-signed certs, no cert distribution to players
- Docker: hardened (--cap-drop ALL, read-only, no-new-privileges, ICC disabled)
- kCTF: NetworkPolicy + PodSecurity restricted + nsjail sandboxing
- Kata + kCTF: same as above, plus guest kernel isolation
- Kata + Firecracker: KVM isolation + per-team microVM + jailer + seccomp
- Raw Firecracker: strongest — KVM isolation + jailer + seccomp + full VM control
