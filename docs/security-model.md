# IsolateX Security Model

## Threat model

Players are assumed to be actively hostile. A player who gets shell access inside their challenge instance will attempt to:
- reach other teams' instances
- read another team's flag
- reach internal orchestration APIs (orchestrator, worker agent)
- escape to the host or Kubernetes control plane
- exhaust resources to deny service to others

IsolateX is designed so that even a player who fully compromises their challenge environment cannot do any of the above.

---

## Isolation by runtime

### Docker (`docker`)

Weakest isolation — use only for challenges where players cannot get shell access.

- One isolated Docker network per instance (challenge + gateway only)
- No host port publishing for challenge containers
- Reverse proxy is the only ingress path; backend containers are never directly exposed
- `--cap-drop ALL` and `--security-opt no-new-privileges:true` are available via `extra_config` (`cap_drop=true`)
- CPU and memory limits enforced
- **Not recommended** for: pwn, RCE, kernel exploitation, anything where a player can run arbitrary commands inside the container

### kCTF / Kubernetes (`kctf`)

Medium isolation via Linux namespaces + nsjail.

- One pod per team instance
- Backends exposed as internal `ClusterIP` services only (no public `NodePort`)
- Kubernetes NetworkPolicy: default-deny east-west, only gateway can reach challenge pods
- `runAsNonRoot`, `allowPrivilegeEscalation: false`, all capabilities dropped, `seccomp: RuntimeDefault`
- Ephemeral pod storage only — no PersistentVolumeClaims
- **Recommended for**: web challenges, reversing, crypto, moderate pwn

### Kata Containers — Firecracker backend (`kata-firecracker`)

Strongest isolation — Firecracker microVM instead of QEMU.

- Firecracker has a smaller attack surface than QEMU (no legacy device emulation)
- Each pod gets its own kernel and VM boundary
- **Recommended for**: kernel exploitation, AI code execution, untrusted binaries

---

## Flag isolation

Each team's flag is derived with HMAC-SHA256:

```
flag = flag_prefix + "{" + HMAC(secret, team_id + ":" + challenge_id + ":" + instance_id + ":" + salt) + "}"
```

Properties:
- Unique per team — team A's flag does not work for team B
- Deterministic — re-derivable for verification without storing plaintext
- Leaking one flag does not help derive others (HMAC is one-way; the secret is never exposed)
- `flag_salt` in the challenge config allows rotating flags between events

---

## Network isolation

| Traffic | Allowed? |
|---|---|
| Player → gateway (HTTPS) | Yes |
| Player → instance backend directly | **No** |
| Gateway → instance backend | Yes |
| Instance → another instance | **No** (per-instance network / NetworkPolicy) |
| Instance → orchestrator API | **No** |
| Instance → worker agent | No (default compose); must remain blocked in production firewalling |
| Instance → Kubernetes API | **No** (kCTF/Kata workers use `automountServiceAccountToken: false`) |
| Instance → host metadata (AWS IMDS, etc.) | Must be blocked at host/network layer in production |
| Instance → internet | Configurable by network policy/runtime setup |
| Worker → orchestrator | Yes (API key required) |
| Orchestrator → worker | Yes (internal network only) |
| Player with wrong team session → another team's endpoint | **No** (reverse-proxy forward-auth) |

---

## Controls checklist

### Per instance
- [ ] 1 team = 1 instance enforced (409 on duplicate)
- [ ] Per-team derived flag (not a shared static flag)
- [ ] CPU and memory limits enforced
- [ ] Auto-destroy on TTL expiry (reaper runs every 30s)
- [ ] Non-root user inside instance (where challenge image permits)
- [ ] No privilege escalation (`no-new-privileges`)
- [ ] Linux capabilities dropped (`--cap-drop ALL` for Docker, securityContext for k8s)
- [ ] seccomp default profile

### Network
- [ ] Default-deny east-west (NetworkPolicy / isolated bridge)
- [ ] Gateway-only ingress
- [ ] No outbound internet by default

### Orchestrator
- [ ] API key required on all endpoints
- [ ] Orchestrator not directly reachable by players (behind gateway IP allowlist in production)
- [ ] TTL reaper enforces expiry even if player never clicks Stop

### Secrets
- [ ] `FLAG_HMAC_SECRET` never exposed to players or committed to source control
- [ ] `API_KEY` not committed to source control (use `.env` or a secrets manager)
- [ ] `flag_salt` rotated between events

---

## What is NOT a security boundary

- **The challenge application itself** — players exploit this by design
- **The gateway** — terminates TLS but is not an isolation boundary
- **CTFd authentication** — IsolateX trusts `team_id` from the CTFd session; CTFd is responsible for authenticating players

---

## Incident response

If a player is suspected of breaking out of their instance:

1. `DELETE /instances/<id>` — immediately destroy the instance
2. Review worker logs for unusual syscalls or outbound network activity
3. For Kata-Firecracker: inspect pod logs, node runtime logs, and the RuntimeClass used
4. For Docker: `docker inspect <container>` and check host process list
5. For kCTF: `kubectl describe pod <name>` and audit logs
6. Rotate `FLAG_HMAC_SECRET` and `API_KEY` if the control plane may have been reached
