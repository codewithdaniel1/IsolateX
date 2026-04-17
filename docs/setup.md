# IsolateX Setup Guide

This guide takes you from zero to a working IsolateX deployment.

---

## Prerequisites

Before you start, decide which runtimes you need:

| Runtime | Requires |
|---|---|
| `docker` | Docker on the worker host |
| `kctf` | Kubernetes cluster |
| `kata` | Kubernetes + Kata Containers installed |
| `kata-firecracker` | Kubernetes + Kata Containers configured with Firecracker backend |

For local dev, `docker` runtime works out of the box with Docker Compose.
For production, you need a Kubernetes cluster. See [kctf-setup.md](kctf-setup.md).

---

## Local dev (5 minutes)

Everything runs in Docker Compose: orchestrator, a Docker worker, CTFd, Postgres, Redis, Traefik.

```bash
git clone https://github.com/osiris/isolatex
cd isolatex
docker compose up -d
```

Services:
- CTFd: http://localhost:8000
- Orchestrator API: http://localhost:8080/docs

The CTFd plugin is already mounted. No extra install step needed.

### Register a test challenge

```bash
curl -X POST http://localhost:8080/challenges \
  -H "x-api-key: dev-api-key-change-in-prod" \
  -H "content-type: application/json" \
  -d '{
    "id": "web-easy",
    "name": "Easy Web",
    "runtime": "docker",
    "image": "nginx:alpine",
    "port": 80
  }'
```

### Launch an instance (test)

```bash
curl -X POST http://localhost:8080/instances \
  -H "x-api-key: dev-api-key-change-in-prod" \
  -H "content-type: application/json" \
  -d '{"team_id": "team-1", "challenge_id": "web-easy"}'
```

---

## Production deployment

### 1. Set environment variables

Copy `.env.example` to `.env` and fill in:

```bash
# Required — generate these before deploying
API_KEY=<openssl rand -hex 32>
FLAG_HMAC_SECRET=<openssl rand -hex 32>

# Database
DATABASE_URL=postgresql+asyncpg://isolatex:<password>@postgres:5432/isolatex

# Redis
REDIS_URL=redis://redis:6379/0

# Gateway
BASE_DOMAIN=ctf.yourdomain.com
TLS_ENABLED=true

# TTL defaults
DEFAULT_TTL_SECONDS=1800   # 30 min global default
MAX_TTL_SECONDS=7200       # 2 hour hard cap on renew

# CTFd integration
CTFD_URL=http://ctfd:8000
```

**Never use the default dev API key in production.**

### 2. Deploy the orchestrator

The orchestrator is stateless — you can run 2 replicas safely.

```bash
kubectl create namespace isolatex

kubectl create secret generic orchestrator-secrets \
  --namespace isolatex \
  --from-literal=database-url="$DATABASE_URL" \
  --from-literal=redis-url="$REDIS_URL" \
  --from-literal=api-key="$API_KEY" \
  --from-literal=flag-secret="$FLAG_HMAC_SECRET"

kubectl apply -f infra/kctf/manifests/
```

### 3. Deploy workers

Each worker runs on the compute hosts and talks to the Kubernetes API.

**kctf / kata / kata-firecracker worker:**
```bash
RUNTIME=kata \
KUBECONFIG=/etc/rancher/k3s/k3s.yaml \
KCTF_NAMESPACE=kctf \
ORCHESTRATOR_URL=http://orchestrator.isolatex:8080 \
ORCHESTRATOR_API_KEY=$API_KEY \
uvicorn worker.main:app --host 0.0.0.0 --port 9090
```

**docker worker:**
```bash
RUNTIME=docker \
ORCHESTRATOR_URL=http://orchestrator.isolatex:8080 \
ORCHESTRATOR_API_KEY=$API_KEY \
uvicorn worker.main:app --host 0.0.0.0 --port 9090
```

### 4. Install the CTFd plugin

```bash
cp -r ctfd-plugin/ <CTFd>/CTFd/plugins/isolatex/
```

Set these environment variables in your CTFd deployment:
```
ISOLATEX_URL=http://orchestrator:8080
ISOLATEX_API_KEY=<same API_KEY as above>
```

Restart CTFd. The plugin loads automatically.

### 5. Deploy the gateway

```bash
kubectl apply -f gateway/traefik/
```

Edit `gateway/traefik/dynamic.yml` to set your domain.

### 6. Register challenges

```bash
# kctf challenge (medium isolation)
curl -X POST http://orchestrator:8080/challenges \
  -H "x-api-key: $API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "id": "web100",
    "name": "Web 100",
    "runtime": "kctf",
    "image": "ghcr.io/osiris/web100:latest",
    "port": 8080,
    "memory_mb": 256,
    "cpu_count": 1,
    "ttl_seconds": 3600
  }'

# kata-firecracker challenge (strongest isolation, e.g. pwn)
curl -X POST http://orchestrator:8080/challenges \
  -H "x-api-key: $API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "id": "pwn100",
    "name": "Pwn 100",
    "runtime": "kata-firecracker",
    "image": "ghcr.io/osiris/pwn100:latest",
    "port": 8888,
    "memory_mb": 512,
    "cpu_count": 2,
    "ttl_seconds": 7200
  }'
```

`ttl_seconds` is optional. If omitted, the global default (30 min) is used.

---

## Adding IsolateX to a challenge in CTFd

In the challenge description, add:

```html
<div data-isolatex-challenge="{{ challenge.id }}"></div>
```

IsolateX renders the Launch / Stop / Restart / Renew panel automatically.

---

## Verify everything is working

```bash
# Check worker health
curl http://worker:9090/health

# List registered workers
curl http://orchestrator:8080/workers -H "x-api-key: $API_KEY"

# Check orchestrator logs
kubectl logs -n isolatex -f deployment/orchestrator
```

---

## Troubleshooting

**Instance stuck in "pending"**
- Check worker logs: `curl http://worker:9090/health`
- Check orchestrator logs for launch errors
- Make sure the challenge image is accessible from the worker

**"No available worker for this runtime"**
- The worker for that runtime may not be registered or may be unhealthy
- Check: `curl http://orchestrator:8080/workers -H "x-api-key: $API_KEY"`

**Kata pods won't start**
- Make sure the RuntimeClass exists: `kubectl get runtimeclass`
- See [kata-setup.md](kata-setup.md)

**CTFd plugin not showing**
- Make sure the plugin folder is in `CTFd/plugins/isolatex/`
- Check that `ISOLATEX_URL` and `ISOLATEX_API_KEY` are set
- Check CTFd logs for plugin load errors

**Timer not showing in CTFd**
- Make sure `isolatex.js` is loaded (check browser console)
- Make sure the challenge description has the `data-isolatex-challenge` div
