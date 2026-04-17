# IsolateX API Reference

Base URL: `http://orchestrator:8080`

All endpoints require the header:
```
x-api-key: <your API key>
```

---

## Instances

### Launch instance
```
POST /instances
```
```json
{ "team_id": "team-42", "challenge_id": "web100" }
```
Returns `201` with the instance object. Returns `409` if this team already has a running instance for this challenge.

### Get instance by ID
```
GET /instances/{instance_id}
```

### Get active instance for a team
```
GET /instances/team/{team_id}/{challenge_id}
```
Returns `404` if no active instance exists.

### Stop instance
```
DELETE /instances/{instance_id}
```
Returns `204`. Destroys the instance and deregisters the gateway route.

### Restart instance
```
POST /instances/{instance_id}/restart
```
Destroys the current instance and launches a new one for the same team + challenge. **TTL resets to the full challenge default.**

Returns the new instance object.

### Renew instance TTL
```
POST /instances/{instance_id}/renew
```
Extends the TTL by the challenge's `ttl_seconds`. Never extends past **2 hours from the current time**.

Returns:
```json
{
  "expires_at": "2026-04-17T20:00:00Z",
  "seconds_added": 1800
}
```
Returns `409` if the instance is already at the 2-hour cap.

---

## Instance object

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "team_id": "team-42",
  "challenge_id": "web100",
  "runtime": "kata",
  "status": "running",
  "endpoint": "https://ab12cd34.web100.ctf.osiris.sh",
  "flag": "flag{...}",
  "expires_at": "2026-04-17T19:30:00Z",
  "started_at": "2026-04-17T19:00:00Z",
  "created_at": "2026-04-17T19:00:00Z"
}
```

**Status values:** `pending` → `running` → `destroyed` / `expired` / `error`

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
  "runtime": "kata",
  "image": "ghcr.io/osiris/web100:latest",
  "port": 8080,
  "cpu_count": 1,
  "memory_mb": 256,
  "ttl_seconds": 3600,
  "flag_salt": "<openssl rand -hex 16>"
}
```

`ttl_seconds` is optional. Omitting it uses the global default (1800s = 30 min).

**Runtimes:** `docker` | `kctf` | `kata` | `kata-firecracker`

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

### Register worker (called by worker agent on startup)
```
POST /workers
```
```json
{
  "id": "worker-kata-01",
  "address": "10.0.1.5",
  "agent_port": 9090,
  "runtime": "kata",
  "max_instances": 50
}
```

### Worker heartbeat
```
POST /workers/{worker_id}/heartbeat
```

---

## Traefik config (internal)

```
GET /traefik/config
```
Returns dynamic route config for Traefik HTTP provider polling. Not for direct use.
