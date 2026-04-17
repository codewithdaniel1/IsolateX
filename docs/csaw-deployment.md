# CSAW 2026 Deployment Guide

This is the production deployment guide for IsolateX powering OSIRIS's CSAW CTF event.

## Event Profile

- **Duration:** Days
- **Competitors:** Hundreds teams
- **Challenges:** 100+ (diverse: web, pwn, crypto, rev, misc)
- **Concurrent instances:** 500+ at peak

## Architecture

Two-tier isolation strategy:

### Tier 1: Easy/Medium Challenges

Runtime: **Kata + kCTF**

**Challenges:** web, crypto, reversing, easy misc

**Why Kata + kCTF:**
- Cost-efficient (Kubernetes is good at packing)
- Strong isolation (guest kernel blocks kernel exploits)
- No per-team microVM overhead
- Stays within Kubernetes operations model

**Example challenges:**
- Web login bypass
- Simple crypto
- Reversing binary
- Trivial web service

**Isolation level:** ⭐⭐⭐⭐ (very strong for 4-hour event)

### Tier 2: Hard Challenges

Runtime: **Firecracker**

**Challenges:** pwn, RCE, AI/code execution, hardcore reversing

**Why Firecracker:**
- Dedicated microVM per team (no resource contention)
- Kernel isolation (players can't kernel-exploit the host)
- Maximum blast radius control
- Best isolation for untrusted code execution

**Example challenges:**
- Pwn binary with shell
- AI sandbox (LLM code execution)
- Kernel module reverse engineering
- System call sandbox escape

**Isolation level:** ⭐⭐⭐⭐⭐ (strongest)

## Infrastructure Setup

### 1. Kubernetes Cluster (kCTF)

```bash
# On your cluster control node
./infra/kctf/setup-cluster.sh          # k3s, production-like
# OR
./infra/kctf/setup-cluster.sh --kind   # kind, local testing
```

This creates:
- `kctf` namespace
- NetworkPolicy (default-deny east-west)
- LimitRange (CPU/memory caps)
- PodSecurity restricted profile
- `isolatex-worker` ServiceAccount + RBAC

### 2. Kata RuntimeClass

```bash
kubectl apply -f - <<'EOF'
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
EOF
```

### 3. Firecracker Worker Pool (for hard challenges)

Prepare 2-3 bare-metal or dedicated VM hosts for Firecracker:

On each host:
```bash
./infra/scripts/check-hardware.sh

# Follow docs/firecracker-host-setup.md for:
# - Kernel >= 5.10
# - /dev/kvm access
# - Firecracker + jailer installation
# - Bridge setup (isolatex0)
# - ebtables rules for isolation
```

### 4. IsolateX Orchestrator

Deploy in your cluster or separately (recommend in-cluster):

```bash
# Create orchestrator deployment
kubectl create namespace isolatex

kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orchestrator
  namespace: isolatex
spec:
  replicas: 2
  selector:
    matchLabels:
      app: orchestrator
  template:
    metadata:
      labels:
        app: orchestrator
    spec:
      containers:
      - name: orchestrator
        image: ghcr.io/osiris/isolatex-orchestrator:latest
        ports:
        - containerPort: 8080
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: orchestrator-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: orchestrator-secrets
              key: redis-url
        - name: API_KEY
          valueFrom:
            secretKeyRef:
              name: orchestrator-secrets
              key: api-key
        - name: FLAG_HMAC_SECRET
          valueFrom:
            secretKeyRef:
              name: orchestrator-secrets
              key: flag-secret
EOF
```

### 5. kCTF Worker Agent (Kubernetes)

The orchestrator talks to the Kubernetes API directly.
No separate worker agent needed for Tier 1.

### 6. Firecracker Worker Agents (Hard challenges)

On each Firecracker host:

```bash
RUNTIME=firecracker \
ORCHESTRATOR_URL=http://orchestrator.isolatex:8080 \
ORCHESTRATOR_API_KEY=$API_KEY \
uvicorn worker.main:app --host 0.0.0.0 --port 9090
```

### 7. Gateway (Traefik + Let's Encrypt)

```bash
kubectl apply -f gateway/traefik/

# Update for your domain
# Edit gateway/traefik/dynamic.yml to point to CTFd
```

---

## Challenge Registration

Before the event, register all challenges:

### Easy/Medium (Kata + kCTF)

```bash
curl -X POST http://orchestrator:8080/challenges \
  -H "x-api-key: $API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "id": "web100",
    "name": "Easy Web",
    "runtime": "kata",
    "runtime_class": "kata",
    "image": "ghcr.io/osiris/web100:latest",
    "port": 8080,
    "memory_mb": 256,
    "cpu_count": 1,
    "ttl_seconds": 3600,
    "flag_salt": "'$(openssl rand -hex 16)'"
  }'
```

### Hard (Firecracker)

```bash
# Build challenge image for Firecracker
./infra/firecracker/build-image.sh challenges/pwn100/ /images/pwn100/

# Register
curl -X POST http://orchestrator:8080/challenges \
  -H "x-api-key: $API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "id": "pwn100",
    "name": "Pwn 100",
    "runtime": "firecracker",
    "kernel_image": "/images/pwn100/vmlinux",
    "rootfs_image": "/images/pwn100/rootfs.ext4",
    "port": 8888,
    "memory_mb": 512,
    "cpu_count": 2,
    "ttl_seconds": 3600,
    "flag_salt": "'$(openssl rand -hex 16)'"
  }'
```

---

## Day-of Operations

### Pre-event

1. Verify all workers are registered and healthy
   ```bash
   curl http://orchestrator:8080/workers -H "x-api-key: $API_KEY"
   ```

2. Test a few challenges
   ```bash
   # Via CTFd UI: click Launch Instance on each challenge type
   ```

3. Monitor
   ```bash
   kubectl logs -n isolatex -f deployment/orchestrator
   kubectl get pods -n kctf -w   # watch kctf pods
   ```

### During event

**Monitor these:**
- Orchestrator error rate (should be < 0.1%)
- Worker availability (should stay 100%)
- TTL reaper (runs every 30s)
- Firecracker worker capacity (should not exceed 80%)

**If a worker fails:**
1. Orchestrator auto-detects (heartbeat timeout)
2. New instances route to healthy workers
3. Instances on failed worker degrade gracefully (show error to player, cleanup in TTL)

**If orchestrator crashes:**
1. Keep it running via Kubernetes (auto-restart)
2. Instance state persists in Postgres
3. Players may see "instance starting" but it recovers when orchestrator comes up

---

## Capacity Planning

### Node count

For ~500 teams, ~150 concurrent instances:

**Kubernetes (kCTF + Kata):**
- 3× worker nodes, 16 vCPU / 32 GB RAM each
- Can handle ~400 concurrent Kata pods

**Firecracker:**
- 2× worker nodes, 32 vCPU / 64 GB RAM each
- Can handle ~200 concurrent Firecracker microVMs (at 1 vCPU / 512 MB each)

**Storage:**
- Postgres: 10 GB (state is small)
- Redis: 1 GB (cache only)
- Firecracker images: 5-10 GB per challenge

### Network

- Ingress: 1 Gbps aggregate (fine for CTF traffic)
- Pod networking: SDN or overlay, nothing special needed

---

## Security Checklist

- [ ] NetworkPolicy applied (default-deny)
- [ ] PodSecurity restricted on kctf namespace
- [ ] ebtables rules blocking pod-to-pod on Firecracker bridge
- [ ] Firecracker UID/GID drops enforced
- [ ] jailer seccomp profiles active
- [ ] API key rotated (never use default)
- [ ] FLAG_HMAC_SECRET never exposed
- [ ] TLS certificates from Let's Encrypt
- [ ] Orchestrator has IP allowlist if exposed (should not be)
- [ ] Postgres password strong
- [ ] Redis on isolated network (not internet-facing)

---

## Incident Response

**"A player claims they accessed another team's instance"**

1. Check player's pod
   ```bash
   kubectl describe pod -n kctf <pod-name>
   kubectl logs -n kctf <pod-name>
   ```

2. Check network traffic (if you have CNI logs)
   ```bash
   # Look for outbound to other pods — NetworkPolicy should block
   ```

3. If confirmed escape:
   - Immediately kill the instance (DELETE /instances/<id>)
   - Rotate FLAG_HMAC_SECRET
   - Review Firecracker worker logs for kernel exploits
   - Consider patching kernel before next event

**"Instance won't start"**

1. Check worker health
   ```bash
   curl http://worker:9090/health
   ```

2. Check orchestrator logs
   ```bash
   kubectl logs -n isolatex orchestrator
   ```

3. Check Kubernetes/Firecracker resources
   ```bash
   kubectl top nodes
   ```

**"Massive lag during event"**

- Check if Firecracker workers are saturated
- Check if Kubernetes is thrashing
- Check network latency
- May need to scale up workers mid-event (feasible with k3s)

---

## Post-event

1. Collect logs and metrics
2. Cleanup: delete all instances (TTL handles this automatically)
3. Deregister workers
4. Plan for next iteration

---

## Backup / Disaster Recovery

- Postgres: backup instance state before event (for forensics)
- Orchestrator: stateless, can redeploy anytime
- Challenge images: keep on secure storage (rebuild if needed)
- API keys: rotate after event

---

## Cost estimate

For a 4-8 hour event with ~500 teams:

| Component | Estimate |
|---|---|
| Kubernetes cluster (3 nodes, 8 hours) | ~$100-150 |
| Firecracker hosts (2 nodes, 8 hours) | ~$100-150 |
| Postgres (managed) | ~$20 |
| Bandwidth | ~$10-20 |
| **Total** | ~$250-350 |

(Costs vary by cloud provider and region.)
