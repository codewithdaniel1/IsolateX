<img src="assets/isolatex-wordmark.svg" alt="IsolateX" width="260" align="left" />
<br clear="left" />

**A CTFd plug-in for per-team challenge instancing.**

IsolateX gives every team their own isolated challenge environment — players click "Launch," get a private endpoint and countdown timer, and the instance auto-stops when time runs out. It works with Docker for local dev and Kubernetes-based runtimes for production.

---

## What players see

On challenges with instancing enabled:
- **Launch** — starts a private instance
- **Restart** — kills and relaunches with a fresh TTL
- **Renew** — resets the countdown timer back to the full TTL duration from now
- **Stop** — destroys the instance early
- **Countdown timer** — live "Expires in 23m 14s" display

On challenges without instancing enabled: nothing — the plugin is completely invisible.

---

## Supported runtimes

| Runtime | Container tech | Isolation | Best for |
|---|---|---|---|
| `docker` | Docker | Basic | Web, crypto, reversing — local dev |
| `kctf` | Kubernetes pod + nsjail | Medium | Web, pwn with moderate risk |
| `kata-firecracker` | Kubernetes + Kata (Firecracker backend) | Strongest | Kernel pwn, AI code execution, RCE |

> **macOS / Windows:** Only `docker` runtime is available locally. `kctf` requires a Linux host. `kata-firecracker` requires Linux + KVM hardware virtualization (VT-x / AMD-V enabled in BIOS).

**Choosing a runtime:**
- Start with `docker` for local dev — no Kubernetes needed.
- Use `kctf` for most production challenges.
- Use `kata-firecracker` for anything where a player gets shell access or can trigger arbitrary code execution.

---

## Resource tiers

Set per-challenge in the admin panel (Plugins → IsolateX):

| Tier | CPU | Memory | Runtime | When to use |
|---|---|---|---|---|
| Tier 1 | 1 core | 512 MB | Docker | Static web, trivial challenges |
| Tier 2 | 2 cores | 1 GB | kCTF | Typical web / reversing / pwn |
| Tier 3 | 4 cores | 2 GB | Kata-FC | AI, compilation, kernel challenges |

---

## Quick start

### Integration modes

- **Bundled mode (`./setup.sh`)**: uses the first-party CTFd-IsolateX image from this repo (`ctfd/Dockerfile`) with the plugin pre-baked.
- **External mode (`./setup.sh --external-ctfd`)**: installs/configures the IsolateX plugin in your existing CTFd deployment.

### Already have CTFd running? (most common case)

```bash
git clone https://github.com/codewithdaniel1/IsolateX
cd IsolateX
./setup.sh --external-ctfd
```

The setup script will:
- start IsolateX core services (`postgres`, `redis`, `orchestrator`, `worker-docker`)
- auto-detect a running external CTFd container when possible and install/configure the plugin
- write plugin connection settings automatically (`ISOLATEX_URL`, `ISOLATEX_API_KEY`)

If auto-detection is ambiguous, pin it explicitly:
```bash
./setup.sh --external-ctfd --external-ctfd-container my-ctfd
# or
./setup.sh --external-ctfd --external-ctfd-path /path/to/CTFd
```

Path expectations:
- Bundled mode (`./setup.sh` with no external flags): CTFd comes from this repo at `./ctfd`.
- External filesystem mode (`--external-ctfd-path`): pass the CTFd repo root path (the directory that contains `CTFd/`), and IsolateX installs the plugin to `CTFd/plugins/isolatex`.
- External container mode (`--external-ctfd-container`): IsolateX installs the plugin inside the container at `/opt/CTFd/CTFd/plugins/isolatex`.

Then:
1. Run `./scripts/import-recruit-chals.sh` to import challenges, auto-register instanced ones with the orchestrator, and upload any downloadable files declared in `challenge.json` (existing CTFd challenge names are skipped and not overwritten)
2. Go to **Admin → Plugins → IsolateX** — only registered (instanced) challenges appear
3. Adjust runtime or tier per challenge if needed and click **Save**
4. Done — players see the Launch button on registered challenges; all others are unaffected

If your CTFd admin credentials are not the default `admin` / `admin`, set `CTFD_USER` and `CTFD_PASS` before running the import script so downloadable challenge files can be attached automatically. If the script cannot log in, it falls back to syncing files directly into the local Docker Compose CTFd instance.

Run a live post-deploy security smoke test any time:
```bash
./scripts/security-smoke.sh
```

### Starting from scratch

```bash
git clone https://github.com/codewithdaniel1/IsolateX
cd IsolateX
./setup.sh
```

The script auto-detects your host and installs all supported components:
- macOS/Windows: Docker runtime stack
- Linux: Docker + kCTF
- Linux with KVM (`/dev/kvm`): Docker + kCTF + kata-firecracker

If a runtime appears disabled in the IsolateX admin page, that toggle cannot be enabled from the page itself. Fix host prerequisites (Linux/KVM) and rerun `./setup.sh`.

It is safe to re-run; existing tools are updated instead of reinstalled. On first run it generates a `.env` file with random secrets.

After the script finishes:
1. Go to **http://localhost:8000** and complete the CTFd setup wizard
2. Go to **Admin → Plugins → IsolateX** to enable instancing per challenge

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
