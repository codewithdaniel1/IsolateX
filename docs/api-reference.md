# Orchestrator API Reference

All requests require the header `x-api-key: <your-api-key>`.

Base URL: `http://orchestrator:8080`

---

## Instances

### POST /instances
Launch a new challenge instance for a team.

**Request**
```json
{
  "team_id": "team-42",
  "challenge_id": "web300"
}
```

**Response 201**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "team_id": "team-42",
  "challenge_id": "web300",
  "runtime": "firecracker",
  "status": "pending",
  "endpoint": null,
  "expires_at": "2026-04-17T03:00:00Z",
  "created_at": "2026-04-17T02:00:00Z"
}
```

**409** — Instance already running for this team+challenge (return existing)
**404** — Challenge not found
**503** — No available worker for this runtime

---

### GET /instances/{instance_id}
Get instance by ID.

**Response 200** — same shape as POST response, with `endpoint` populated once running

---

### GET /instances/team/{team_id}/{challenge_id}
Get the active instance for a team + challenge.

**404** — No active instance

---

### DELETE /instances/{instance_id}
Destroy an instance immediately (before TTL).

**Response 204**

---

## Workers

### POST /workers
Register a worker (called automatically by the worker agent on startup).

**Request**
```json
{
  "id": "worker-fc-01",
  "address": "10.0.1.5",
  "agent_port": 9090,
  "runtime": "firecracker",
  "max_instances": 100
}
```

---

### POST /workers/{worker_id}/heartbeat
Update worker last-seen timestamp. Workers call this every 15s.

**Response 204**

---

### GET /workers
List all active workers.

---

### DELETE /workers/{worker_id}
Deregister a worker.

---

## Challenges

### POST /challenges
Register a challenge.

**Request**
```json
{
  "id": "web300",
  "name": "Web 300",
  "runtime": "docker",
  "image": "ghcr.io/osiris/web300:latest",
  "cpu_count": 1,
  "memory_mb": 512,
  "port": 8080,
  "ttl_seconds": 3600,
  "flag_salt": "optional-random-salt"
}
```

For Firecracker/Cloud Hypervisor, use `kernel_image` and `rootfs_image` instead of `image`.

---

### GET /challenges
List all registered challenges.

---

### GET /challenges/{challenge_id}
Get a challenge by ID.

---

### DELETE /challenges/{challenge_id}
Remove a challenge.

---

## Gateway

### GET /traefik/config
Returns Traefik dynamic configuration for all running instances.
Traefik polls this endpoint every 5 seconds.

---

## Health

### GET /health
Returns `{"status": "ok"}`. No API key required.

---

## Metrics

### GET /metrics
Prometheus metrics endpoint. No API key required.
Protect this endpoint with a firewall rule or IP allowlist in production.
