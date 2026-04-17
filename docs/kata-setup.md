# Kata Containers Setup Guide

Kata Containers runs your Kubernetes pods inside lightweight VMs instead of sharing the host kernel.
This gives you stronger isolation while keeping the Kubernetes operational model.

---

## What is Kata?

```
Standard pod:
  Kubernetes → containerd → container runtime → shared host kernel

Kata pod:
  Kubernetes → containerd → Kata runtime → Firecracker/QEMU → guest kernel
```

**Key benefit:** Each pod gets its own kernel. A kernel exploit inside one pod doesn't affect the host or other pods.

---

## Prerequisites

Your Kubernetes cluster must support nested virtualization or run on a hypervisor that allows `/dev/kvm` access.

For kind (local dev):
```bash
kind create cluster --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
EOF
```

For k3s (production):
```bash
curl -sfL https://get.k3s.io | sh -s - --disable traefik
```

---

## Install Kata

### On your Kubernetes nodes

```bash
# Ubuntu 22.04
sudo apt install -y kata-runtime

# Verify
kata-runtime --version
```

### In the cluster

Create a RuntimeClass so pods can request Kata:

```yaml
# infra/kctf/manifests/kata-runtime-class.yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
```

Apply it:
```bash
kubectl apply -f infra/kctf/manifests/kata-runtime-class.yaml
```

---

## Using Kata for a challenge

In your pod spec, add `runtimeClassName: kata`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-challenge
  namespace: kctf
spec:
  runtimeClassName: kata    # ← use Kata instead of default runtime
  containers:
    - name: challenge
      image: ghcr.io/osiris/web-challenge:latest
      env:
        - name: ISOLATEX_FLAG
          value: flag{...}
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534
```

---

## IsolateX integration

When you register a challenge for the `kata` runtime, the orchestrator should set:

```json
{
  "id": "web300",
  "name": "Web 300",
  "runtime": "kata",
  "image": "ghcr.io/osiris/web300:latest",
  "port": 8080
}
```

The worker agent creates a pod with `runtimeClassName: kata` automatically.

---

## Security properties (`kata`)

| Boundary | What it provides |
|---|---|
| Namespace isolation | PID, mount, network (nsjail handles this) |
| Kernel isolation | Guest kernel (Kata) — kernel exploits trapped in VM |
| Network isolation | NetworkPolicy blocks pod-to-pod traffic |
| Resource limits | LimitRange enforces CPU/memory caps |
| Capabilities | All dropped, seccomp enforced |

---

## `kata-firecracker` vs `kata`

Kata can use multiple hypervisors:

**`kata-firecracker`**
- Fastest startup
- Smallest memory footprint
- Minimal device model
- Recommended for Kubernetes

**`kata`**
- Slower startup
- More device support
- Better compatibility with complex workloads

Use `kata-firecracker` when you want the stronger VM-backed option above `kata`.

---

## Troubleshooting

### Pod stuck in "Creating"

```bash
kubectl describe pod <name> -n kctf
kubectl logs -n kctf <pod-name>
```

Check that Kata runtime is installed on the node:
```bash
kata-runtime --version
```

### `/dev/kvm` permission denied

Ensure the Kata runtime process can access `/dev/kvm`:
```bash
ls -la /dev/kvm
sudo chown root:kvm /dev/kvm
sudo chmod 660 /dev/kvm
```

### Slow pod startup

If Firecracker isn't available, Kata falls back to QEMU (much slower).
Verify Firecracker is installed:
```bash
firecracker --version
```
