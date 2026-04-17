# IsolateX Strategy & Runtime Spectrum

## Executive Summary

IsolateX is a configurable challenge isolation platform that supports multiple runtimes.
Organizations choose based on their threat model, cost, and operational capacity.

This document outlines the design philosophy and why each runtime exists.

---

## The Spectrum

IsolateX supports a complete spectrum from weak to strongest isolation:

```
Docker
  ↓ (weak, fast, cheap)
kCTF (standard Kubernetes)
  ↓ (medium isolation, operational ease)
Kata + kCTF (kCTF + guest kernel)
  ↓ (strong isolation, still Kubernetes-native)
Firecracker (direct KVM microVMs)
  ↑ (strongest, dedicated per-team)
```

---

## Why this spectrum?

### Different threat models demand different solutions

**Low-risk (static web, crypto, rev):** Docker or kCTF is fine. Player can't break anything critical.

**Medium-risk (web exploitation, simple RCE):** Kata + kCTF gives stronger isolation while keeping Kubernetes's operational benefits.

**High-risk (pwn, AI code execution, sandbox escapes):** Dedicated Firecracker microVMs. Player gets their own kernel. Escape stays in the VM.

### Cost-efficiency

- Docker: $0.01 per instance
- kCTF: $0.05 per instance (Kubernetes overhead)
- Kata + kCTF: $0.08 per instance (guest kernel overhead)
- Kata + Firecracker: $0.15 per instance (dedicated microVM)
- Raw Firecracker: $0.20 per instance (max control)

For an event with ~200 concurrent instances, that's:
- All Docker: $2/hour
- All Kata + kCTF: $9.60/hour
- Hybrid (Kata+k8s + Kata+FC): $12-15/hour

### Operational simplicity

- Docker: trivial
- kCTF: simple (one kubectl)
- Kata + kCTF: simple (add one RuntimeClass)
- Kata + Firecracker: moderate (manage Firecracker pool)
- Raw Firecracker: complex (build orchestrator)

---

## CSAW Configuration

CSAW uses a **two-tier approach:**

### Tier 1: Easy/Medium (Kata + kCTF)

**Challenges:** web, crypto, reversing, easy misc

**Why:**
- Cost-efficient (pack many pods in one cluster)
- Strong isolation (guest kernel blocks kernel exploits)
- Operational ease (standard kCTF lifecycle)

**Isolation level:** ⭐⭐⭐⭐ (very strong for 4-hour event)

**Justification:**
- CSAW is time-limited (4-8 hours)
- Players are students, not state actors
- Kernel 0-day in 4 hours is unlikely
- Cost savings are real

### Tier 2: Hard (Firecracker)

**Challenges:** pwn, RCE, AI code execution, hardcore reversing

**Why:**
- Dedicated microVM per team (no resource contention)
- Kernel isolation (different kernel per instance)
- Maximum blast radius control

**Isolation level:** ⭐⭐⭐⭐⭐ (strongest)

**Justification:**
- Shell access in pwn requires maximum isolation
- Code execution workloads (AI/LLM) need their own kernel
- Firecracker's fast startup (125ms) handles scale
- Worth the cost for high-risk challenges

---

## IsolateX for others

Organizations using IsolateX have full flexibility:

- **University CTF (like CSAW):** Kata + kCTF + Firecracker (our model)
- **Beginner CTF:** Docker only
- **Enterprise red team lab:** All Firecracker
- **Security research platform:** Firecracker + custom networking
- **Serverless sandbox:** All Docker or Kata + kCTF

The platform doesn't dictate. It supports all of the above.

---

## Architecture decisions

### Why Kata + kCTF instead of just kCTF?

**Plain kCTF (medium isolation):**
- Shared kernel across all pods
- Kernel exploit could theoretically jump between pods (though NetworkPolicy helps)
- Good enough for most CTFs

**Kata + kCTF (strong isolation):**
- Each kCTF pod gets guest kernel (Firecracker or QEMU underneath)
- Kernel exploit trapped in guest; can't reach host or other pods
- Still benefits from kCTF orchestration
- Small cost overhead (guest kernel + VM startup)

**For CSAW:** Kata + kCTF is worth it because:
1. Adds real security margin
2. Keeps kCTF simplicity
3. Cost per instance is still very low
4. Easy to implement (one RuntimeClass definition)

### Why Firecracker for hard challenges?

**Firecracker (direct KVM microVMs):**
- Orchestrator picks a Firecracker worker
- Worker launches microVM directly
- Orchestrator routes traffic to it
- Per-team dedicated kernel and resources
- Fastest startup (125ms) and highest density

**For hard CSAW challenges:** Firecracker is the right call because:
1. Shell access requires maximum isolation
2. Dedicated kernel per team blocks kernel exploits
3. Fast startup and high density handle scale
4. Cost-justified for high-risk workloads

### Why not Firecracker for everything?

Because:
- 4-5x higher cost than kCTF
- Most challenges don't need it
- CSAW is 4 hours, not 24/7 public platform
- kCTF with Kata provides 95% of isolation at 1/4 the cost

---

## Security principles

1. **Isolation is the goal, not the technology**
   - Docker, kCTF, Kata, Firecracker are all tools
   - Each has a threat model it's designed for
   - Use the right tool for the right risk level

2. **Defense in depth**
   - NetworkPolicy (no pod-to-pod even on kCTF)
   - seccomp (block dangerous syscalls)
   - Capability drop (remove privileges)
   - Resource limits (prevent DoS)
   - TTL (no stale instances)
   - One layer failing doesn't mean game over

3. **No shared mutable state**
   - Each instance is ephemeral
   - One team can't read another's files
   - Flags are per-team derived (not shared)
   - No inter-instance communication

4. **Fail secure**
   - If orchestrator crashes, instances degrade gracefully
   - If a worker fails, instances route to healthy workers
   - If TTL reaper fails, orchestrator handles cleanup

---

## Future extensibility

Adding a new runtime takes:
1. One file implementing `RuntimeAdapter`
2. Adding it to the registry
3. Updating the runtime type enum
4. Done

Examples:
- gVisor (another sandbox option)
- Kata + Cloud Hypervisor (different VM engine)
- QEMU (full VMs if needed)
- Podman (Docker alternative)
- Incus / LXD containers

The orchestrator doesn't care. It just dispatches to the right adapter.

---

## Portfolio value

This design shows:
- ✓ Architectural thinking (not just "pick one tech")
- ✓ Risk stratification (different challenges, different protections)
- ✓ Cost consciousness (balance security and efficiency)
- ✓ Extensibility (support many runtimes via clean interfaces)
- ✓ Real-world constraints (time-limited event, student competitors)

That's much stronger than "we built a CTF isolation platform."

---

## Decision matrix: which runtime for which challenge?

| Challenge | Easy level | Medium level | Hard level |
|---|---|---|---|
| Web | Docker | Kata+kCTF | Firecracker |
| Crypto | Docker | kCTF | — |
| Reversing | Docker | kCTF | Kata+kCTF or Firecracker |
| Pwn | — | — | Firecracker |
| Misc/misc. | Docker | kCTF or Kata+kCTF | Firecracker if code exec |
| AI/code exec | — | Kata+kCTF | Firecracker |

**For CSAW:** use Tier 1 (Kata+kCTF) unless it's explicitly a pwn or RCE challenge.
