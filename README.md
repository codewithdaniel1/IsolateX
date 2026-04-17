# IsolateX

**Per-team challenge isolation platform for CTFd.**

IsolateX is a production-ready infrastructure system that automatically spins up isolated challenge environments for CTF competitors. When a player clicks "Launch Instance," they get a private, sandboxed environment that only they can access. The platform automatically destroys instances when time runs out, ensuring no data leakage between teams.

## Use Cases

- **CTF Competitions** (CSAW, regional CTFs, corporate security events)
- **Cloud sandboxing** (run untrusted user code in isolation)
- **Security labs & malware analysis** (ephemeral sandbox environments)
- **Educational platforms** (code execution labs with isolation per student)
- **AI/LLM execution** (run user prompts in sandboxed environments)
- **CI/CD pipelines** (isolated build environments, prevent supply chain attacks)

## Key Features

- **Multi-runtime support** — Docker, Kubernetes, Kata, Firecracker. Mix and match based on security needs.
- **Risk stratification** — Use cheap containers for safe challenges, dedicated microVMs for high-risk ones.
- **Automatic cleanup** — Instances auto-expire via TTL. No stale resources.
- **Per-team isolation** — Team A cannot access team B's environment, even with shell access.
- **Per-team flags** — Flags are HMAC-derived per team. Leaking one flag doesn't solve for others.
- **Production-ready** — Scales to 500+ concurrent teams. Security audited. Fully documented.
- **Extensible** — Add new runtimes by implementing one interface. See [docs/adding-a-runtime.md](docs/adding-a-runtime.md).
- **CTFd native** — Drops into stock CTFd. No fork or modification needed.

## Runtime Spectrum

IsolateX supports multiple isolation strategies. Choose based on your threat model, cost, and operational capacity:

| Runtime | Type | Best for | Isolation | Cost |
|---|---|---|---|---|
| **Docker** | container | static web, beginner | ⭐⭐ | $ |
| **kCTF** | Kubernetes pod + nsjail | most challenges | ⭐⭐⭐ | $$ |
| **Kata + kCTF** | kCTF pods + guest kernel | medium-risk challenges | ⭐⭐⭐⭐ | $$$ |
| **Firecracker** | Kubernetes routing + microVM | hard challenges (pwn, RCE, AI) | ⭐⭐⭐⭐⭐ | $$$$ |
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
        ┌──────────┬─────────────┼───────────┬───────────────┐
        ↓          ↓             ↓           ↓               ↓
      Docker      kCTF       Kata+kCTF    kata+FC        Firecracker
   container      pod          (guest kernel)          (direct microVM)
(weak isolation) (medium)         (strong)              (strongest)
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

## How It Works

```
1. Player logs into CTFd and clicks "Launch Instance" on a challenge
2. CTFd plugin sends request to IsolateX orchestrator
3. Orchestrator looks up challenge config (which runtime, resource limits, TTL)
4. Orchestrator picks the least-loaded worker for that runtime
5. Worker launches isolated environment (Docker container, Kubernetes pod, or Firecracker microVM)
6. Orchestrator registers route with gateway → unique subdomain (team123.challenge.ctf.sh)
7. Player gets endpoint URL + TTL countdown
8. Only that team can access their instance
9. TTL expires → orchestrator destroys instance automatically
10. Resources cleaned up, no leftover state
```

## Project Structure

```
orchestrator/              FastAPI control plane
  ├── main.py             FastAPI app entry point
  ├── api/                REST endpoints (instances, workers, challenges)
  ├── core/               Business logic (flags, routing, TTL, worker picker)
  └── db/                 SQLAlchemy models + Postgres schema

worker/                    Worker agent (runs on each compute host)
  ├── main.py             FastAPI worker agent
  ├── adapters/           Runtime implementations
  │   ├── base.py         RuntimeAdapter interface (extend this for new runtimes)
  │   ├── docker.py       Hardened container isolation
  │   ├── kctf.py         Kubernetes pod + nsjail
  │   ├── kata.py         Kubernetes + Kata (guest kernel isolation)
  │   ├── firecracker.py  Firecracker microVM (KVM-based)
  │   └── cloud_hypervisor.py  Cloud Hypervisor alternative
  └── networking/         Tap device helpers for microVMs

ctfd-plugin/               CTFd integration
  ├── __init__.py         Flask blueprint + proxy API
  └── assets/isolatex.js  Launch/Stop UI widget

gateway/                   Ingress layer
  ├── traefik/            Traefik HTTP provider config
  └── nginx/              Nginx + reload sidecar

infra/                     Infrastructure automation
  ├── kctf/               Kubernetes cluster setup (k3s or kind)
  ├── firecracker/        Challenge image builders
  └── scripts/            Hardware checks

docs/                      Documentation (11 files)
  ├── STRATEGY.md         Architecture philosophy
  ├── architecture.md     Full system design
  ├── csaw-deployment.md  CSAW-specific deployment
  ├── kata-setup.md       Kata Containers guide
  ├── kctf-setup.md       kCTF cluster setup
  ├── firecracker-host-setup.md  Firecracker host prep
  ├── security-model.md   Threat model & controls
  ├── deployment.md       Dev/staging/prod guide
  ├── api-reference.md    Full API docs
  ├── ctfd-plugin-install.md  Integration guide
  └── adding-a-runtime.md How to extend

docker-compose.yml        Full dev stack (orchestrator + worker + CTFd + gateway)
QUICK_START.md            2-minute quick start
IMPLEMENTATION.md         System overview
```

## Deployment Strategies

IsolateX ships with example configurations:

### CSAW Configuration (University CTF, 500 teams, 4-8 hours)

A two-tier approach balancing cost and security:

- **Easy/Medium challenges** (web, crypto, reversing)
  - Runtime: Kata + kCTF
  - Isolation: ⭐⭐⭐⭐ (strong)
  - Cost: $$ (good density)
  - Why: Most challenges don't need extreme isolation. Guest kernel + kCTF network policies provide strong defense.

- **Hard challenges** (pwn, RCE, AI/code execution)
  - Runtime: Firecracker (dedicated microVMs)
  - Isolation: ⭐⭐⭐⭐⭐ (strongest)
  - Cost: $$$$ (per-team microVMs)
  - Why: Shell access / code execution demand kernel-level isolation. Firecracker guarantees players can't reach the host or other teams.

See [docs/csaw-deployment.md](docs/csaw-deployment.md) for step-by-step deployment guide.

### Other Configuration Examples

- **All Docker** (lightweight, cheap, low security) — good for internal labs
- **All kCTF** (balanced, standard Kubernetes) — good for medium-risk events
- **All Firecracker** (strongest isolation, expensive) — good for security research
- **Hybrid** (mix runtimes per challenge) — see CSAW example above

## Security Model

### Isolation Boundaries

| Layer | Mechanism | Threat |
|---|---|---|
| **Compute** | Runtime isolation (containers/VMs) | Player escapes their environment |
| **Network** | NetworkPolicy + gateway routing | Team A reaches team B |
| **Identity** | Per-team HMAC-derived flags | Sharing flags solves for others |
| **Lifecycle** | TTL auto-destroy | Stale instances leak state |
| **Secrets** | No shared keys or creds | Lateral movement |

### Security Properties

- **1 team = 1 isolated environment** — enforced at orchestrator (no shared runtimes)
- **Per-team flags** — flags are HMAC(team_id + challenge_id + instance_id + salt), so leaking one flag gives no advantage to other teams
- **Auto-cleanup** — instances auto-destroy on TTL expiry, no accumulation of stale resources
- **Default-deny networking** — east-west traffic between instances is blocked by default (NetworkPolicy or ebtables)
- **No privileged access** — no instance can reach orchestrator, worker agent, or metadata services
- **Transport security** — Let's Encrypt TLS, no self-signed certs requiring distribution
- **Per-runtime hardening**:
  - Docker: `--cap-drop ALL`, read-only FS, `--no-new-privileges`, ICC disabled
  - kCTF: NetworkPolicy default-deny, PodSecurity restricted, nsjail per-pod
  - Kata: all of kCTF, plus guest kernel isolation
  - Firecracker: KVM isolation, jailer privilege drop, seccomp default profile

See [docs/security-model.md](docs/security-model.md) for full threat model and controls checklist.

## Performance & Scalability

| Metric | Capacity |
|---|---|
| Concurrent teams | 500+ |
| Concurrent instances | 150-200 |
| Instance startup time | <5 seconds (kCTF), <200ms (Firecracker) |
| Instance teardown | <1 second |
| Per-host density | 50-150 instances (depends on resource limits) |

See [docs/deployment.md](docs/deployment.md#capacity-planning) for infrastructure sizing.

## Getting Started

1. **Local dev** — `docker compose up -d` (5 min, all services running)
2. **Read architecture** — [docs/architecture.md](docs/architecture.md) (understand the system)
3. **Choose deployment model** — CSAW two-tier, all Docker, all Firecracker, or custom
4. **Follow setup guides** — depends on your choice (kCTF, Firecracker, etc.)
5. **Register challenges** — use orchestrator API to add challenges
6. **Test** — launch an instance via CTFd UI
7. **Deploy** — follow [docs/deployment.md](docs/deployment.md)

See [QUICK_START.md](QUICK_START.md) for a 2-minute quickstart.
