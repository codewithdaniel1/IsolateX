# IsolateX API Reference

Base URL: `http://orchestrator:8080` (local dev: `http://localhost:8080`)

All control-plane endpoints require:
```
x-api-key: <your API key>
```
Exception: `GET /health` is intentionally public for health checks.

Interactive docs (Swagger UI): `http://localhost:8080/docs`

---

## Instances

### Launch instance
```
POST /instances
```
```json
{ "team_id": "team-42", "challenge_id": "web100" }
```
Returns `201` with the instance object.  
Returns `409` if this team already has a running instance for this challenge.

### Get active instance for a team
```
GET /instances/team/{team_id}/{challenge_id}
```
Returns the active (pending or running) instance, or `404` if none exists.

### Get instance by ID
```
GET /instances/{instance_id}
```

### Stop instance
```
DELETE /instances/{instance_id}
```
Returns `204`. Destroys the instance and deregisters the gateway route.

### Restart instance
```
POST /instances/{instance_id}/restart
```
Destroys the current instance and launches a new one for the same team + challenge.  
TTL resets to the full challenge default.  
Returns the new instance object.

### Renew instance TTL
```
POST /instances/{instance_id}/renew
```
Resets `expires_at` to `now + ttl_seconds` for that challenge.  
Returns `409` if renewing would not extend the current expiry.

Returns:
```json
{
  "expires_at": "2026-04-17T20:00:00Z",
  "seconds_added": 900
}
```

---

## Instance object

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "team_id": "team-42",
  "challenge_id": "web100",
  "runtime": "docker",
  "status": "running",
  "endpoint": "http://ab12cd34.web100.localhost",
  "expires_at": "2026-04-17T19:30:00Z",
  "started_at": "2026-04-17T19:00:00Z",
  "created_at": "2026-04-17T19:00:00Z"
}
```

**Status values:** `pending` → `running` → `destroyed` / `expired` / `error`

**Endpoint format:**
- Local dev (`BASE_DOMAIN=localhost`): `http://<prefix>.<challenge-id>.localhost`
- Production: `https://<prefix>.<challenge-id>.<base-domain>`

`endpoint` is always a reverse-proxy URL. Challenge backends are internal-only and are never returned as direct host/node ports.

---

## Challenges

### Register challenge
```
POST /challenges
```
```json
{
  "id": "web100",
  "name": "Web 100",
  "runtime": "docker",
  "image": "myctf-web100:latest",
  "port": 80,
  "cpu_count": 1,
  "memory_mb": 512,
  "ttl_seconds": 3600
}
```

| Field | Required | Default | Description |
|---|---|---|---|
| `id` | Yes | — | Unique slug, must match CTFd challenge slug |
| `name` | Yes | — | Display name |
| `runtime` | Yes | — | `docker`, `kctf`, or `kata-firecracker` |
| `image` | Yes | — | Docker image to run |
| `port` | Yes | — | Port the app listens on inside the container |
| `cpu_count` | No | 1 | CPU cores (1, 2, 4) |
| `memory_mb` | No | 512 | Memory in MB (512, 1024, 2048) |
| `ttl_seconds` | No | global default | Instance lifetime; null = use global default |
| `extra_config` | No | — | JSON string for adapter-specific options |

**Runtimes:**

| Value | Description |
|---|---|
| `docker` | Standard Docker container (local dev, easy challenges) |
| `kctf` | Kubernetes pod + nsjail (medium isolation) |
| `kata-firecracker` | Kubernetes + Kata Containers with Firecracker backend (strongest isolation) |

### Update challenge settings
```
PATCH /challenges/{challenge_id}
```
Updates one or more fields without replacing the whole record. Used by the admin UI.

```json
{
  "ttl_seconds": 3600,
  "cpu_count": 2,
  "memory_mb": 1024
}
```
All fields are optional. Only the provided fields are updated.

### List challenges
```
GET /challenges
```

### Get challenge
```
GET /challenges/{challenge_id}
```

### Delete challenge
```
DELETE /challenges/{challenge_id}
```

---

## Workers

### List workers
```
GET /workers
```
Returns all registered workers and their status (active if last heartbeat < 60s ago).

### Register worker
```
POST /workers
```
Called automatically by the worker agent on startup.

```json
{
  "id": "worker-docker-01",
  "address": "worker-docker",
  "agent_port": 9090,
  "runtime": "docker",
  "max_instances": 50
}
```

### Worker heartbeat
```
POST /workers/{worker_id}/heartbeat
```
Called automatically by the worker agent every 30s.

---

## Traefik config (internal)

```
GET /traefik/config
```
Returns dynamic route config for Traefik's HTTP provider. Traefik polls this every 5 seconds. Not for direct use.
Each instance route includes forward-auth against CTFd session ownership.

---

## Settings

### Get settings
```
GET /settings
```

Returns:
```json
{
  "default_ttl_seconds": 1800
}
```

### Update settings
```
PATCH /settings
```

```json
{
  "default_ttl_seconds": 3600
}
```

---

## Health check

```
GET /health
```
Returns `{"status": "ok"}` when the orchestrator is up.
