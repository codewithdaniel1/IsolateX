# IsolateX

**Per-team challenge instancing for CTFd.**

IsolateX gives every team their own isolated challenge environment — players click "Launch," get a private endpoint and countdown timer, and the instance auto-stops when time runs out. It works with Docker for local dev and Kubernetes-based runtimes for production.

---

## What players see

- **Launch** — starts a private instance
- **Restart** — kills and relaunches with a fresh TTL
- **Renew** — resets the countdown timer back to the full TTL duration from now
- **Stop** — destroys the instance early
- **Countdown timer** — live "Expires in 23m 14s" display

---

## Supported runtimes

| Runtime | Container tech | Isolation | Best for |
|---|---|---|---|
| `docker` | Docker (runc) | Basic | Web, crypto, reversing — local dev |
| `kctf` | Kubernetes pod + nsjail | Medium | Web, pwn with moderate risk |
| `kata-firecracker` | Kubernetes + Kata (Firecracker backend) | Strongest | Kernel pwn, AI code execution, RCE |

> **macOS / Windows:** Only `docker` runtime is available locally. `kctf` and `kata-firecracker` require a Linux host with KVM hardware virtualization (VT-x / AMD-V enabled in BIOS).

**Choosing a runtime:**
- Start with `docker` for local dev — no Kubernetes needed.
- Use `kctf` for most production challenges.
- Use `kata-firecracker` for anything where a player gets shell access or can trigger arbitrary code execution.

---

## Resource tiers

Set per-challenge in the admin panel (Plugins → IsolateX):

| Tier | CPU | Memory | Runtime | When to use |
|---|---|---|---|---|
| Tier 1 | 0.5 cores | 256 MB | Docker | Static web, trivial challenges |
| Tier 2 | 1 core | 512 MB | kCTF | Typical web / reversing |
| Tier 3 | 2 cores | 1 GB | kCTF | Pwn, heavier web |
| Tier 4 | 4 cores | 2 GB | Kata-FC | AI, compilation, kernel challenges |

---

## Quick start

```bash
git clone https://github.com/codewithdaniel1/IsolateX
cd IsolateX

# Docker only (local dev — works on macOS, Windows, Linux)
./setup.sh

# Docker + Kubernetes + kCTF  (Linux only)
./setup.sh --kctf

# + Kata + Firecracker  (Linux + KVM required)
./setup.sh --kata-fc

# Everything at once
./setup.sh --all
```

The script detects what you already have installed and **updates** it rather than reinstalling. On first run it also generates a `.env` file with random secrets.

After the script finishes:
1. Go to **http://localhost:8000** and complete the CTFd setup wizard
2. Go to **Admin → Plugins → IsolateX** to set TTL and resource tiers
3. Register your challenge images with the orchestrator (see [docs/setup.md](docs/setup.md))

---

## Requirements

| Requirement | Docker runtime | kCTF | Kata-FC |
|---|---|---|---|
| Docker Desktop / Docker Engine | ✅ | ✅ | ✅ |
| Linux host | | ✅ | ✅ |
| KVM (VT-x / AMD-V in BIOS) | | | ✅ |
| kubectl + k3s | | ✅ | ✅ |
| Kata Containers | | | ✅ |
| Firecracker | | | ✅ |

`setup.sh` installs all of these for you.

---

## Documentation

| Doc | Audience |
|---|---|
| [docs/setup.md](docs/setup.md) | **Start here** — automated setup, adding challenges, troubleshooting |
| [docs/architecture.md](docs/architecture.md) | How the pieces fit together |
| [docs/api-reference.md](docs/api-reference.md) | Orchestrator REST API |
| [docs/security-model.md](docs/security-model.md) | Isolation model and threat model |
| [docs/kctf-setup.md](docs/kctf-setup.md) | *(Operators)* Kubernetes / kCTF cluster setup details |
| [docs/kata-setup.md](docs/kata-setup.md) | *(Operators)* Kata + Firecracker setup details |

---

## Project layout

```
setup.sh              Automated install/update script (Docker, k3s, kCTF, Kata, Firecracker)

orchestrator/         FastAPI backend
  api/                REST endpoints: instances, challenges, workers
  core/               TTL reaper, worker scheduler, flag derivation, routing
  db/                 SQLAlchemy models

worker/               Worker agent (runs per host / per runtime)
  adapters/
    docker.py         Docker runtime
    kctf.py           Kubernetes + nsjail runtime
    kata.py           Kata + Firecracker runtime

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
- **Kata-FC isolation** — each pod runs inside its own Firecracker microVM with its own kernel

Full details → [docs/security-model.md](docs/security-model.md)
