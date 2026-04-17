# IsolateX Security Model

## Threat model

Players are assumed to be actively hostile. A player who gets shell access inside
their challenge instance will attempt to:
- reach other teams' instances
- reach internal orchestration APIs
- access the host or cluster control plane
- read another team's flag
- exhaust resources to deny service to others

IsolateX is designed so that even a player who fully compromises their challenge
environment cannot do any of the above.

---

## Isolation boundaries

### Kata / Kata-Firecracker
- **Compute**: each pod runs inside a lightweight VM with its own guest kernel.
  A kernel exploit inside the guest does not automatically compromise the host.
- **Network**: Kubernetes networking still applies. NetworkPolicy can deny pod-to-pod
  traffic and only allow ingress from the gateway.
- **Storage**: challenge state stays inside the pod's ephemeral filesystem unless you
  explicitly mount additional volumes.
- **Process**: the challenge still runs as an ordinary container process inside the
  Kata guest, with Kubernetes securityContext controls applied on top.

### kCTF / Kubernetes
- **Compute**: one pod per team instance. Linux namespaces isolate PID, network, mount.
- **Network**: default-deny NetworkPolicy. No pod-to-pod communication allowed.
  Only the gateway can reach challenge pods.
- **Storage**: ephemeral pod storage only (no PersistentVolumeClaims).
  Pod deletion wipes all data.
- **Process**: `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`,
  all Linux capabilities dropped, seccomp RuntimeDefault enforced.

### Docker
- **Compute**: Linux namespaces (weakest boundary — not recommended for pwn/RCE challenges).
- **Network**: isolated bridge with ICC (inter-container communication) disabled.
  Containers bind only to `127.0.0.1:<host_port>` — not exposed to other containers.
- **Process**: `--cap-drop ALL`, `--no-new-privileges`, `--read-only`,
  `--security-opt no-new-privileges`.
- **Recommendation**: use Docker only for static web or easy challenges.
  For anything with shell access, use kCTF, Kata, or Kata-Firecracker.

---

## Flag isolation

Each team's flag is derived with HMAC-SHA256:

```
flag = flag_prefix + "{" + HMAC(secret, team_id + ":" + challenge_id + ":" + instance_id + ":" + salt) + "}"
```

Properties:
- Unique per team — team A's flag does not solve for team B.
- Deterministic — can be re-derived for verification without storing plaintext.
- Leaking one flag does not help an attacker derive flags for other teams
  (HMAC is a one-way function; the secret key is never exposed).
- `flag_salt` in the challenge config allows rotating flags between events.

---

## Network isolation summary

| Traffic | Allowed? |
|---|---|
| Player → gateway (HTTPS) | Yes |
| Gateway → their instance's port | Yes |
| Instance → another instance | **No** |
| Instance → orchestrator API | **No** |
| Instance → worker agent | **No** |
| Instance → Kubernetes API | **No** |
| Instance → host metadata | **No** |
| Instance → internet | Configurable (off by default) |
| Worker → orchestrator | Yes (API key required) |
| Orchestrator → worker | Yes (internal network only) |

---

## Controls checklist

### Per instance
- [ ] One team = one instance (409 on duplicate)
- [ ] Non-root user inside instance
- [ ] No privilege escalation
- [ ] CPU and memory limits enforced
- [ ] Read-only root filesystem where possible
- [ ] /tmp as tmpfs only
- [ ] All Linux capabilities dropped (Docker/kCTF)
- [ ] seccomp default profile (all runtimes)
- [ ] Per-team derived flag (not shared flag)
- [ ] Auto-destroy on TTL expiry

### Network
- [ ] Default deny east-west
- [ ] Gateway-only ingress
- [ ] No outbound by default
- [ ] No access to metadata services (AWS/GCP/Azure IMDS, Kubernetes API)

### Orchestrator
- [ ] API key required on all endpoints
- [ ] No direct exposure to players (behind gateway IP allowlist)
- [ ] TTL reaper runs in the orchestrator

### Secrets
- [ ] FLAG_HMAC_SECRET never exposed to players
- [ ] API_KEY not committed to source control (use .env or secrets manager)
- [ ] Challenge flag_salt rotated between events

---

## What is NOT a security boundary

- The challenge application itself (players exploit this by design)
- The gateway (terminates TLS but not an isolation boundary)
- CTFd authentication (IsolateX trusts team_id from CTFd session, but CTFd is responsible for auth)

---

## Incident response

If a player is suspected of breaking out of their instance:

1. Run `DELETE /instances/<id>` to immediately destroy the instance.
2. Review worker logs for unusual syscalls or network activity.
3. For Kata / Kata-Firecracker: inspect the pod, node runtime logs, and the selected RuntimeClass.
4. For Docker: check for container escape via `docker inspect` and host process list.
5. For kCTF: `kubectl describe pod <name>` and review audit logs.
6. Rotate `FLAG_HMAC_SECRET` and `API_KEY` if the control plane may have been reached.
