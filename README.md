# IsolateX

Per-team challenge isolation platform for CTFd.
Built for OSIRIS / CSAW-style CTF events.

## What it does

When a competitor clicks "Launch Instance," IsolateX spins up a private, isolated
environment just for their team, gives them a unique URL, enforces a TTL, and
destroys it automatically when time runs out.

## Supported runtimes

| Runtime | Type | Best for |
|---|---|---|
| **Firecracker** | microVM (KVM) | pwn, binary, RCE, malware sandbox |
| **Cloud Hypervisor** | microVM (KVM) | same as Firecracker |
| **kCTF** | Kubernetes pod + nsjail | network challenges, flexible workloads |
| **Docker** | container | web challenges, easy/beginner, local dev |

Adding a new runtime takes one file. See [docs/adding-a-runtime.md](docs/adding-a-runtime.md).

## Supported gateways

- **Traefik** (recommended) — HTTP provider, zero-downtime route updates
- **Nginx** — file-based config + reload sidecar

## Architecture

```
Players → Gateway (Traefik/Nginx, TLS) → CTFd
                                       → IsolateX Orchestrator
                                              ↓
                                       Worker Agents
                                    ┌──────┬──────┬──────┐
                                    │  FC  │ kCTF │ Docker
                                    │ microVM│ Pod │ container
                                    └──────┴──────┴──────┘
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

| Doc | What it covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Full architecture + ASCII diagram + request flow |
| [docs/security-model.md](docs/security-model.md) | Threat model, isolation boundaries, controls checklist |
| [docs/adding-a-runtime.md](docs/adding-a-runtime.md) | How to add any new runtime (gVisor, Kata, QEMU, etc.) |
| [docs/firecracker-host-setup.md](docs/firecracker-host-setup.md) | Host prep for Firecracker workers |
| [docs/kctf-setup.md](docs/kctf-setup.md) | Fresh kCTF / Kubernetes cluster setup |
| [docs/ctfd-plugin-install.md](docs/ctfd-plugin-install.md) | CTFd plugin installation and challenge registration |
| [docs/api-reference.md](docs/api-reference.md) | Full orchestrator API reference |
| [docs/deployment.md](docs/deployment.md) | Dev → staging → production deployment guide |

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

## Key security properties

- 1 team = 1 isolated environment (enforced at orchestrator layer)
- Per-team HMAC-derived flags (leaking one flag helps no one else)
- Auto-destroy on TTL expiry (no stale instances)
- Default-deny east-west network traffic between instances
- No instance can reach the orchestrator or worker agent
- Let's Encrypt TLS — no self-signed certs, no cert distribution to players
- Firecracker: KVM isolation + jailer + seccomp (strongest boundary)
- kCTF: NetworkPolicy + PodSecurity restricted + LimitRange
- Docker: hardened (--cap-drop ALL, read-only, no-new-privileges, ICC disabled)
