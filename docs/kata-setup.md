# Kata + Firecracker Setup Guide

> **Operator guide** — This document is for infrastructure operators setting up Kata Containers with the Firecracker backend manually.
> For most users, run `./setup.sh` instead — on Linux hosts with `/dev/kvm`, it auto-installs Kata + Firecracker.
> See [setup.md](setup.md) for the full quickstart.
>
> **Requirements:** Linux host with KVM hardware virtualization enabled (VT-x for Intel, AMD-V for AMD — set in BIOS). Not available on macOS or Windows without a Linux VM. Firecracker requires `/dev/kvm` to be accessible.

Kata Containers runs your Kubernetes pods inside lightweight VMs instead of sharing the host kernel.
The Firecracker backend replaces QEMU with a minimal microVM, giving the smallest possible attack surface.

---

## What is Kata + Firecracker?

```
Standard pod:
  Kubernetes → containerd → container runtime → shared host kernel

Kata + Firecracker pod:
  Kubernetes → containerd → Kata runtime → Firecracker microVM → guest kernel
```

**Key benefits:**
- Each pod gets its own kernel — kernel exploits inside one pod don't affect the host or other pods.
- Firecracker has no legacy device emulation, dramatically reducing attack surface vs QEMU.

---

## Prerequisites

Your Kubernetes cluster must support nested virtualization or run on a hypervisor that allows `/dev/kvm` access.

Verify KVM is available:
```bash
ls -la /dev/kvm
```

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

## Install Kata Containers

### On your Kubernetes nodes

```bash
# Via the official Kata install script
bash -c "$(curl -fsSL https://raw.githubusercontent.com/kata-containers/kata-containers/main/utils/kata-manager.sh) install-kata-containers"

# Verify
kata-runtime --version
```

---

## Install Firecracker

```bash
FC_LATEST=$(curl -s https://api.github.com/repos/firecracker-microvm/firecracker/releases/latest | grep tag_name | cut -d'"' -f4)
ARCH=$(uname -m)
curl -sLO "https://github.com/firecracker-microvm/firecracker/releases/download/${FC_LATEST}/firecracker-${FC_LATEST}-${ARCH}.tgz"
tar -xzf "firecracker-${FC_LATEST}-${ARCH}.tgz"
sudo install -m 0755 "release-${FC_LATEST}-${ARCH}/firecracker-${FC_LATEST}-${ARCH}" /usr/local/bin/firecracker
sudo install -m 0755 "release-${FC_LATEST}-${ARCH}/jailer-${FC_LATEST}-${ARCH}" /usr/local/bin/jailer
rm -rf "firecracker-${FC_LATEST}-${ARCH}.tgz" "release-${FC_LATEST}-${ARCH}"

# Verify
firecracker --version
```

---

## Configure Kata to use Firecracker

```bash
sudo mkdir -p /etc/kata-containers
sudo tee /etc/kata-containers/configuration-fc.toml > /dev/null <<'TOML'
[hypervisor.firecracker]
path = "/usr/local/bin/firecracker"
jailer_path = "/usr/local/bin/jailer"
kernel = "/opt/kata/share/kata-containers/vmlinux.container"
image = "/opt/kata/share/kata-containers/kata-containers.img"
TOML
```

---

## Register the RuntimeClass

Create a RuntimeClass so pods can request Kata + Firecracker:

```yaml
# infra/kctf/manifests/kata-fc-runtime-class.yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata-firecracker
handler: kata-fc
```

Apply it:
```bash
kubectl apply -f infra/kctf/manifests/kata-fc-runtime-class.yaml
```

---

## Using Kata-Firecracker for a challenge

When you register a challenge for the `kata-firecracker` runtime:

```json
{
  "id": "pwn300",
  "name": "Pwn 300",
  "runtime": "kata-firecracker",
  "image": "ghcr.io/myorg/pwn300:latest",
  "port": 8888
}
```

The worker agent creates a pod with `runtimeClassName: kata-firecracker` automatically.

In your pod spec (for reference — IsolateX handles this):

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pwn-challenge
  namespace: kctf
spec:
  runtimeClassName: kata-firecracker
  containers:
    - name: challenge
      image: ghcr.io/myorg/pwn300:latest
      env:
        - name: ISOLATEX_FLAG
          value: flag{...}
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534
```

---

## Security properties

| Boundary | What it provides |
|---|---|
| Kernel isolation | Guest kernel (Kata + Firecracker) — kernel exploits trapped in microVM |
| Minimal attack surface | Firecracker has no legacy device emulation |
| Network isolation | NetworkPolicy blocks pod-to-pod traffic |
| Exposure model | Challenge backends stay internal (`ClusterIP`) and are reachable only through the reverse proxy |
| Resource limits | LimitRange enforces CPU/memory caps |
| Capabilities | All dropped, seccomp enforced |

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

```bash
ls -la /dev/kvm
sudo chown root:kvm /dev/kvm
sudo chmod 660 /dev/kvm
```

### Firecracker binary not found

Verify the install:
```bash
firecracker --version
jailer --version
which firecracker
```

### Slow pod startup

Verify the Kata configuration file points to the correct Firecracker binary:
```bash
cat /etc/kata-containers/configuration-fc.toml
```
