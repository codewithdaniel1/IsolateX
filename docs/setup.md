# IsolateX Setup Guide

---

## Part 0 — Plugging in to an existing CTFd (most common)

If you already have CTFd running with challenges, this is all you need:

```bash
git clone https://github.com/codewithdaniel1/IsolateX
cd IsolateX
./setup.sh --external-ctfd
```

`setup.sh --external-ctfd` starts only the IsolateX core services and then attempts to auto-install/configure the plugin in your existing CTFd.

Optional explicit targeting (recommended if multiple CTFd instances are running):
```bash
./setup.sh --external-ctfd --external-ctfd-container <ctfd-container-name>
# or
./setup.sh --external-ctfd --external-ctfd-path <path-to-CTFd>
```

Path expectations:
- Bundled mode (`./setup.sh` with no external flags): CTFd comes from this repo at `./ctfd`.
- External filesystem mode (`--external-ctfd-path`): pass the CTFd repo root path (the directory that contains `CTFd/`), and IsolateX installs the plugin to `CTFd/plugins/isolatex`.
- External container mode (`--external-ctfd-container`): IsolateX installs the plugin inside the container at `/opt/CTFd/CTFd/plugins/isolatex`.

Bundled mode details:
- The CTFd image built from `ctfd/Dockerfile` includes the IsolateX plugin by default.
- In local development, `docker-compose.yml` also bind-mounts `./ctfd-plugin` into CTFd so plugin edits apply immediately.

After setup, restart CTFd only if your environment requires it. You should see **IsolateX** in the admin navbar under Plugins.

**Enabling instancing on your challenges:**
1. Run `scripts/import-challenges.sh [path-to-challenge-root]` to import challenges and upload any downloadable files listed in `challenge.json` (existing CTFd challenge names are skipped and not overwritten). If no path is passed, it defaults to `./challenges`. Challenges are registered with IsolateX only when `challenge.json` includes `isolatex` metadata (for example `isolatex: { "image": "myctf/web1:latest", "port": 80 }`).
2. Go to **Admin → Plugins → IsolateX** — only challenges registered with the orchestrator appear here
3. Adjust the runtime tier per challenge if needed and click **Save**
4. Players immediately see the Launch/Stop/Renew panel on registered challenges; all other challenges are completely unaffected

If your CTFd admin login is not `admin` / `admin`, export `CTFD_USER` and `CTFD_PASS` first so the file-upload step can log in to CTFd. When that is unavailable, the script falls back to syncing files directly into the local Docker Compose CTFd instance.

After setup/import, run a live security smoke test:
```bash
./scripts/security-smoke.sh
```

---

## Part 1 — Fresh install (auto-detected runtimes)

The `setup.sh` script installs and configures everything. Safe to re-run — existing tools are updated, not reinstalled.

```bash
git clone https://github.com/codewithdaniel1/IsolateX
cd IsolateX
./setup.sh
```

`./setup.sh` auto-detects host capabilities and installs all supported layers:

| Host capability | Tools installed | Runtimes unlocked |
|---|---|---|
| Any host | Docker, Docker Compose | `docker` |
| Linux host | + kubectl, k3s, kCTF namespace + NetworkPolicy | `docker`, `kctf` |
| Linux + KVM (`/dev/kvm`) | + Kata Containers, Firecracker, `kata-firecracker` RuntimeClass | + `kata-firecracker` |

> **macOS / Windows:** Only `docker` runtime works locally. `kctf` requires a **Linux host**. `kata-firecracker` requires **Linux + KVM hardware virtualization** (VT-x for Intel, AMD-V for AMD — enable in BIOS). For production, use a Linux server or cloud VM (AWS, GCP, DigitalOcean, Hetzner).
> If a runtime is disabled in the IsolateX admin page, that toggle cannot be enabled from the page itself. Fix host prerequisites and rerun `./setup.sh`.

After the script finishes:
1. Go to **http://localhost:8000** and complete the CTFd setup wizard
2. Go to **Admin → Plugins → IsolateX** to enable instancing per challenge

On first run, `setup.sh` generates a `.env` file with random secrets. Keep this file — it contains your `API_KEY` and `FLAG_HMAC_SECRET`.

---

## Manual setup — Part 2: Docker only (local dev, step by step)

Everything runs in Docker Compose: orchestrator, a Docker worker, CTFd, Postgres, Redis, and Traefik.

### Step 1 — Start the stack

```bash
git clone https://github.com/codewithdaniel1/IsolateX
cd IsolateX

# Create secrets for compose (or run ./setup.sh once to auto-generate .env)
cat > .env <<EOF
API_KEY=$(openssl rand -hex 32)
FLAG_HMAC_SECRET=$(openssl rand -hex 32)
SECRET_KEY=$(openssl rand -hex 32)
CTFD_SECRET_KEY=$(openssl rand -hex 32)
EOF

docker compose up -d
```

Services after startup:
- **CTFd**: http://localhost:8000
- **Orchestrator API**: http://localhost:8080/docs

### Step 2 — Set up CTFd

1. Go to http://localhost:8000 and complete the CTFd setup wizard (name, admin account).
2. The IsolateX plugin is already installed — you will see **IsolateX** in the admin navbar under Plugins.

### Step 3 — Add your challenges to CTFd

In CTFd (Admin → Challenges → New Challenge), create a challenge as usual.
The description can be anything — IsolateX automatically injects the instance panel; no special markup needed.

### Step 4 — Register challenges and check the admin UI

Register challenges with the orchestrator (the import script handles this automatically):

```bash
./scripts/import-challenges.sh
```

The same script also attaches downloadable files for any challenge whose `challenge.json` includes a `files` array. Use `files: []` for challenges that should not expose downloads. If you ever need to re-sync attachments later, run `python3 scripts/upload-challenge-files.py`.
For IsolateX registration, add `isolatex` metadata to each instanced challenge's `challenge.json` (for example `isolatex: { "image": "myctf/web1:latest", "port": 80 }`).

Then go to **CTFd Admin → Plugins → IsolateX**:

1. Only challenges registered with the orchestrator appear — no toggling needed
2. Adjust the runtime or resource tier per challenge if needed and click **Save**
3. Players immediately see the Launch/Stop/Renew panel on registered challenges

Challenges not registered with the orchestrator are unaffected — no panel is shown to players.

### Step 5 — Build and load your challenge images

Your challenge Docker image must be accessible to the worker. For local dev:

```bash
# Build your challenge image
docker build -t my-challenge:latest ./challenges/my-challenge/

# The worker container shares the host Docker socket, so the image is immediately available
```

Changes to TTL and resources take effect on the next launched instance. Running instances are not affected.

### Step 6 — Test it

1. Log in as a player (or in a private/incognito window).
2. Open an instancing-enabled challenge.
3. The **Live Instance** panel appears automatically.
4. Click **Launch** — the instance starts, you get an endpoint URL and countdown timer.
5. Click the link — it opens your challenge in a new tab.
6. Test **Restart**, **Renew**, and **Stop**.
7. Open a challenge that does **not** have instancing enabled — confirm no panel is shown.

---

## Part 3 — Challenge image requirements

### Challenge image requirements

Your challenge Docker image must:
1. Run as a non-root user where possible
2. Listen on a single port (the `port` field in the orchestrator registration)
3. Accept the flag via the `ISOLATEX_FLAG` environment variable (IsolateX injects this automatically)

Example minimal Dockerfile for a Flask web challenge:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd -m ctf && chown -R ctf:ctf /app
USER ctf
ENV PORT=8080
EXPOSE 8080
CMD ["python", "app.py"]
```

In your app, read the flag from the environment:
```python
import os
FLAG = os.environ.get("ISOLATEX_FLAG", "flag{placeholder}")
```

### Choosing a runtime

| Challenge type | Recommended runtime |
|---|---|
| Static web (no shell) | `docker` |
| Web with server-side code | `docker` or `kctf` |
| Reversing, crypto | `docker` or `kctf` |
| Binary exploitation (pwn) | `kata-firecracker` |
| RCE / arbitrary code execution | `kata-firecracker` |
| Kernel challenges | `kata-firecracker` |

### Choosing resource tiers

| Tier | CPU | Memory | Use case |
|---|---|---|---|
| 1 | 1 core | 512 MB | Static sites, typical web / reversing |
| 2 | 2 cores | 1 GB | Pwn, heavier services |
| 3 | 4 cores | 2 GB | AI, compilation, heavy compute |

You can set these per-challenge in **Admin → Plugins → IsolateX**.

### Bulk registering via API (optional)

The admin UI is the easiest way to enable challenges. For scripted or CI/CD workflows you can also call the orchestrator API directly:

```bash
#!/bin/bash
API_KEY="$(grep '^API_KEY=' .env | cut -d= -f2-)"
ORCH="http://localhost:8080"

register() {
  local id=$1 name=$2 image=$3 port=$4 runtime=${5:-docker}
  curl -s -X POST "$ORCH/challenges" \
    -H "x-api-key: $API_KEY" \
    -H "content-type: application/json" \
    -d "{\"id\":\"$id\",\"name\":\"$name\",\"runtime\":\"$runtime\",\"image\":\"$image\",\"port\":$port}"
}

register "cmdinj"     "Command Injection"  "myctf-cmdinj:latest"    80
register "sqlinj"     "SQL Injection"      "myctf-sqlinj:latest"    80
register "bof"        "Buffer Overflow"    "myctf-bof:latest"      8888 kata-firecracker
```

---

## Part 4 — Production deployment

### 1. Generate secrets

```bash
API_KEY=$(openssl rand -hex 32)
FLAG_HMAC_SECRET=$(openssl rand -hex 32)
echo "API_KEY=$API_KEY"
echo "FLAG_HMAC_SECRET=$FLAG_HMAC_SECRET"
```

**Never use the default dev keys in production.**

### 2. Set environment variables

In `docker-compose.yml` or your deployment config, set:

```bash
# Orchestrator
API_KEY=<generated above>
FLAG_HMAC_SECRET=<generated above>
DATABASE_URL=postgresql+asyncpg://isolatex:<password>@postgres:5432/isolatex
REDIS_URL=redis://redis:6379/0
BASE_DOMAIN=ctf.yourdomain.com
TLS_ENABLED=true
DEFAULT_TTL_SECONDS=1800    # 30 min default, override per-challenge in admin UI

# CTFd plugin
ISOLATEX_URL=http://orchestrator:8080
ISOLATEX_API_KEY=<same API_KEY>
```

### 3. Deploy the orchestrator

```bash
kubectl create namespace isolatex

kubectl create secret generic orchestrator-secrets \
  --namespace isolatex \
  --from-literal=api-key="$API_KEY" \
  --from-literal=flag-secret="$FLAG_HMAC_SECRET" \
  --from-literal=database-url="$DATABASE_URL" \
  --from-literal=redis-url="$REDIS_URL"

kubectl apply -f infra/kctf/manifests/
```

### 4. Deploy workers

For Kubernetes-based runtimes, workers run as pods on cluster nodes. See [kctf-setup.md](kctf-setup.md) for cluster setup and [kata-setup.md](kata-setup.md) for Kata + Firecracker setup.

For Docker runtime (no Kubernetes needed):
```bash
RUNTIME=docker \
ORCHESTRATOR_URL=http://orchestrator:8080 \
ORCHESTRATOR_API_KEY=$API_KEY \
WORKER_ADVERTISE_ADDRESS=<worker-host-ip> \
uvicorn main:app --host 0.0.0.0 --port 9090
```

### 5. Install the CTFd plugin

```bash
cp -r ctfd-plugin/ <CTFd>/CTFd/plugins/isolatex/
pip install httpx

cat > <CTFd>/CTFd/plugins/isolatex/.isolatex.env <<EOF
ISOLATEX_URL=http://orchestrator:8080
ISOLATEX_API_KEY=<API_KEY>
EOF
```

Restart CTFd. You will see **[IsolateX] plugin loaded** in the CTFd logs.

### 6. Configure Traefik

Traefik is bundled in `docker-compose.yml` and starts automatically. For production, edit `gateway/traefik/traefik.yml` with your domain and TLS email, then:

```bash
kubectl apply -f gateway/traefik/
```

Each instance gets a subdomain: `<instance-prefix>.<challenge-id>.<base-domain>`  
e.g. `ab12cd34.web100.ctf.yourdomain.com`

For local dev, the endpoint is `http://localhost:<port>` directly.

---

## Troubleshooting

**Instance stuck in "pending"**
- Check worker logs — the image may not be reachable from the worker
- Check orchestrator logs for launch errors
- Make sure the worker is registered: `GET /workers`

**"No available worker for this runtime"**
- The worker for that runtime is not registered or is unhealthy
- Check: `curl http://localhost:8080/workers -H "x-api-key: $API_KEY"`

**Link does not work (connection refused)**
- For Docker runtime: make sure the `isolatex_challenges` network is not set to `internal: true`
- Check that the container is actually running: `docker ps --filter "name=isolatex_"`
- Exec into the container and check the app is listening: `docker exec <name> curl localhost:<port>`

**Live Instance panel not showing**
- The IsolateX plugin is mounted and CTFd restarted? Check CTFd logs for `[IsolateX] plugin loaded`
- The challenge ID must be registered in the orchestrator — IDs are case-sensitive
- Open browser devtools → Console for JS errors

**Buttons (Restart/Renew/Stop) not working**
- Open browser devtools → Network tab → click the button → check the response
- Make sure you are logged in to CTFd (the plugin uses your session)

**Renew extends longer than expected**
- Renew resets `expires_at` to `now + ttl_seconds` for the challenge. If players keep renewing, the instance lifetime can keep extending.

**CTFd plugin not loading**
- Make sure `httpx` is installed in the CTFd container: `pip install httpx`
- Check that `ISOLATEX_URL` and `ISOLATEX_API_KEY` environment variables are set
