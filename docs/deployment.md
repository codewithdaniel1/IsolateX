# Deployment Guide

## Quick reference

| Use case | Guidance |
|---|---|
| **CSAW event** | See [csaw-deployment.md](csaw-deployment.md) |
| **Local dev** | Docker Compose (this doc, "Local dev" section) |
| **Production** | Kubernetes + choose runtime (this doc, "Production" section) |

---

## Local dev (fastest path)

Requires: Docker, Docker Compose

```bash
cd IsolateX

# Generate secrets
API_KEY=$(openssl rand -hex 32)
FLAG_SECRET=$(openssl rand -hex 32)
SECRET_KEY=$(openssl rand -hex 32)

# Write .env for orchestrator
cat > orchestrator/.env <<EOF
DATABASE_URL=postgresql+asyncpg://isolatex:isolatex@postgres:5432/isolatex
REDIS_URL=redis://redis:6379/0
SECRET_KEY=$SECRET_KEY
API_KEY=$API_KEY
FLAG_HMAC_SECRET=$FLAG_SECRET
GATEWAY_TYPE=traefik
BASE_DOMAIN=localhost
TLS_ENABLED=false
EOF

# Start everything
docker compose up -d

# Verify
curl http://localhost:8080/health      # orchestrator
curl http://localhost:8000             # CTFd
curl http://localhost:9090/health      # docker worker
```

CTFd setup wizard runs at http://localhost:8000 on first launch.

---

## Register a test challenge

```bash
API_KEY="dev-api-key-change-in-prod"   # matches docker-compose.yml default

curl -X POST http://localhost:8080/challenges \
  -H "x-api-key: $API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "id": "example-web",
    "name": "Example Web Challenge",
    "runtime": "docker",
    "image": "nginx:alpine",
    "port": 80,
    "memory_mb": 128,
    "ttl_seconds": 1800
  }'
```

---

## Production deployment

### Prerequisites

- 1+ orchestrator nodes (can be small — 2 vCPU / 2 GB RAM is enough)
- 1+ Postgres instance
- 1+ Redis instance
- 1+ gateway node (Traefik or Nginx)
- 1+ compute nodes per runtime type you want to support

### Production secrets

Never use the dev defaults. Generate all secrets before deploying:

```bash
openssl rand -hex 32   # API_KEY
openssl rand -hex 32   # FLAG_HMAC_SECRET
openssl rand -hex 32   # SECRET_KEY
```

Store in a secrets manager (Vault, AWS Secrets Manager, k8s Secrets).

### Orchestrator

```bash
docker run -d \
  --name isolatex-orchestrator \
  --env-file /etc/isolatex/orchestrator.env \
  -p 8080:8080 \
  ghcr.io/osiris/isolatex-orchestrator:latest
```

### Worker — Docker runtime

```bash
docker run -d \
  --name isolatex-worker-docker \
  -e RUNTIME=docker \
  -e ORCHESTRATOR_URL=http://orchestrator:8080 \
  -e ORCHESTRATOR_API_KEY=$API_KEY \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -p 9090:9090 \
  ghcr.io/osiris/isolatex-worker:latest
```

### Worker — Firecracker runtime

See `docs/firecracker-host-setup.md` for host preparation first.

```bash
RUNTIME=firecracker \
FIRECRACKER_BIN=/usr/local/bin/firecracker \
JAILER_BIN=/usr/local/bin/jailer \
FIRECRACKER_RUN_DIR=/run/isolatex/firecracker \
FIRECRACKER_UID=10000 \
FIRECRACKER_GID=10000 \
TAP_BRIDGE=isolatex0 \
ORCHESTRATOR_URL=http://orchestrator:8080 \
ORCHESTRATOR_API_KEY=$API_KEY \
uvicorn worker.main:app --host 0.0.0.0 --port 9090
```

### Worker — kCTF runtime

Run kCTF cluster setup first:

```bash
./infra/kctf/setup-cluster.sh          # k3s (production)
./infra/kctf/setup-cluster.sh --kind   # kind (local dev)
```

Then:

```bash
RUNTIME=kctf \
KUBECONFIG=/etc/rancher/k3s/k3s.yaml \
KCTF_NAMESPACE=kctf \
ORCHESTRATOR_URL=http://orchestrator:8080 \
ORCHESTRATOR_API_KEY=$API_KEY \
uvicorn worker.main:app --host 0.0.0.0 --port 9090
```

---

## Choosing a runtime per challenge

| Challenge type | Recommended spectrum tier | Code mapping |
|---|---|---|
| Static web / beginner | Docker | `docker` |
| Web exploitation | kCTF | `kctf` |
| Medium-risk web / crypto | Kata + kCTF | `kata` |
| Pwn / binary / RCE | Kata + FC / FC | `firecracker` |
| Malware / sandbox escape | FC | `firecracker` |
| Network challenges | kCTF or Kata + kCTF | `kctf` or `kata` |
| AI / code execution | Kata + FC / FC | `firecracker` |

The platform spectrum is `docker -> kCTF -> kata+kCTF -> kata+FC -> FC`.
The actual runtime strings in challenge config remain `docker`, `kctf`, `kata`, and `firecracker`.

---

## Monitoring

The orchestrator exposes Prometheus metrics at `/metrics`.

Key metrics to watch:
- Number of running instances per worker
- TTL reaper run time
- Worker heartbeat age
- Instance launch/destroy error rate

Suggested Grafana dashboard: import `infra/grafana-dashboard.json` (coming soon).

---

## Scaling for large events (2000+ users)

1. Add more compute nodes and register additional workers — the orchestrator automatically distributes load.
2. Scale the orchestrator horizontally behind a load balancer (it is stateless except for DB + Redis).
3. For Firecracker: each host can typically support 50–150 concurrent microVMs depending on challenge resource limits.
4. Use per-challenge resource profiles (small/medium/large) to tune density.
5. Pre-warm workers by launching dummy instances before the event starts.
