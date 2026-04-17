# IsolateX Strategy & Runtime Spectrum

## Executive Summary

The IsolateX spectrum is ordered like this:

1. `docker`
2. `kctf`
3. `kata+kCTF`
4. `kata+FC`
5. `FC`

In code, the actual runtime strings remain:

- `docker`
- `kctf`
- `kata`
- `firecracker`

The `kata+kCTF` and `kata+FC` steps are documented isolation tiers layered on top of those runtime values.

---

## The Spectrum

Choose the isolation tier that matches the workload risk:

```text
docker
  -> weakest isolation, fastest iteration, lowest cost

kctf
  -> stronger Kubernetes-based isolation with hardened pod settings

kata+kctf
  -> guest-kernel Kubernetes path for stronger isolation

kata+fc
  -> VM-backed step between Kata-on-Kubernetes and direct Firecracker

fc
  -> direct KVM microVMs for highest-risk workloads
```

---

## Why This Spectrum Exists

### Different threat models demand different runtimes

- Low-risk workloads like static web or basic crypto usually fit `docker` or `kctf`.
- Medium-risk workloads that may expose RCE benefit from `kata+kCTF`.
- Higher-risk workloads can move up to `kata+FC`.
- Highest-risk workloads like pwn, AI code execution, or sandbox escape research belong on `FC`.

### Cost still matters

The stronger the isolation boundary, the more host overhead you usually pay:

- `docker` is cheapest and densest
- `kctf` adds Kubernetes overhead
- `kata+kCTF` adds guest-kernel overhead
- `kata+FC` adds stronger VM-backed overhead
- `FC` trades density for strongest isolation

### Operations still matter

- `docker` is easiest to stand up for local dev
- `kctf` and `kata+kCTF` fit teams already operating Kubernetes
- `kata+FC` and `FC` require KVM-capable hosts and more host prep

---

## Recommended CSAW Model

### Tier 1: Easy/Medium

- Tier: `kata+kCTF`
- Code mapping: `kata`
- Good for: web, crypto, reversing, easier misc challenges
- Why: strong isolation without paying microVM-per-team cost on every challenge

### Tier 2: Hard

- Tier: `kata+FC` / `FC`
- Code mapping: `firecracker`
- Good for: pwn, RCE, AI/code execution, anything with hostile shell access
- Why: dedicated microVM isolation and tighter blast-radius control

This model keeps the runtime strings simple while still reflecting the real deployment shape.

---

## When To Use Each Runtime

| Situation | Recommended tier | Why |
|---|---|---|
| Local dev, static web, fast iteration | `docker` | Fastest setup and lowest overhead |
| Standard Kubernetes-backed challenge isolation | `kctf` | Better operational fit for cluster-based events |
| Medium-risk challenge on Kubernetes | `kata+kCTF` | Guest kernel adds meaningful isolation margin |
| Harder VM-backed challenge tier | `kata+FC` | Stronger VM-backed step before going fully direct |
| High-risk hostile code execution | `FC` | Strongest path in this repo |

---

## Security Principles

1. Isolation first.
   Choose the runtime based on breakout risk, not convenience alone.

2. Defense in depth.
   Runtime isolation, network policy, dropped capabilities, seccomp, TTL cleanup, and per-team flags all matter together.

3. No shared mutable state.
   One team gets one isolated environment, and teardown should remove it completely.

4. Operational clarity matters.
   Runtime names in challenge config should match the actual adapter names in code, even when the strategy docs talk about `kata+kCTF` and `kata+FC`.

---

## Future Extensibility

Adding a new runtime still follows the same shape:

1. Implement a new adapter in `worker/adapters/`
2. Register it in `worker/adapters/__init__.py`
3. Add it to `RuntimeType` in `orchestrator/db/models.py`
4. Document the host setup and tradeoffs

Examples:

- gVisor
- QEMU-backed VMs
- Podman
- Incus / LXD

---

## Decision Matrix

| Challenge type | Lower risk | Medium risk | High risk |
|---|---|---|---|
| Web | `docker` | `kata+kCTF` | `FC` |
| Crypto | `docker` | `kctf` or `kata+kCTF` | `FC` if code exec is involved |
| Reversing | `docker` | `kctf` or `kata+kCTF` | `kata+FC` or `FC` |
| Pwn | — | `kata+FC` | `FC` |
| Misc | `docker` | `kctf` or `kata+kCTF` | `FC` if execution is exposed |
| AI / code execution | — | `kata+FC` | `FC` |

For CSAW-style events, default to `kata+kCTF` for most challenges and reserve `kata+FC` / `FC` for the genuinely dangerous ones.
