# kCTF Setup Guide

> **Operator guide** — This document is for infrastructure operators setting up the Kubernetes cluster manually.
> For most users, run `./setup.sh --kctf` instead — it handles everything on this page automatically.
> See [setup.md](setup.md) for the full quickstart.
>
> **Requirements:** Linux host with KVM enabled (VT-x / AMD-V in BIOS). Not available on macOS or Windows without a Linux VM.

kCTF is Google's CTF infrastructure framework. It uses Kubernetes with nsjail
(namespace-based sandboxing) inside each pod for challenge isolation.

IsolateX uses kCTF-style pods: standard Kubernetes pods with hardened security
contexts. You do not need to install the full kCTF toolchain — IsolateX manages
pod lifecycle directly via the Kubernetes API.

---

## Quick start (local dev with kind)

```bash
# Install kind
curl -Lo /usr/local/bin/kind \
  https://kind.sigs.k8s.io/dl/v0.22.0/kind-linux-amd64
chmod +x /usr/local/bin/kind

# Run the IsolateX kCTF setup script
./infra/kctf/setup-cluster.sh --kind
```

---

## Production setup (k3s)

k3s is a lightweight, production-ready Kubernetes distribution.

```bash
# Install k3s (disabling built-in Traefik — IsolateX brings its own gateway)
curl -sfL https://get.k3s.io | sh -s - --disable traefik --disable servicelb

# Run the IsolateX kCTF setup script
sudo ./infra/kctf/setup-cluster.sh
```

---

## What the setup script does

1. Creates the `kctf` namespace
2. Applies Pod Security Standards (restricted profile) on the namespace
3. Applies default-deny NetworkPolicy (no east-west pod traffic)
4. Applies LimitRange (CPU/memory caps per pod)
5. Creates the `isolatex-worker` ServiceAccount + RBAC Role

---

## Challenge image requirements for kCTF

Challenge Docker images for kCTF must:
- Run as a non-root user (UID != 0)
- Not require write access to the root filesystem (use `tmpfs` for `/tmp`)
- Not require any Linux capabilities
- Listen on the port specified in the challenge config

Example Dockerfile:

```dockerfile
FROM ubuntu:22.04

RUN useradd -r -u 65534 challenge
WORKDIR /challenge
COPY challenge .
RUN chown challenge:challenge /challenge/challenge

USER challenge
EXPOSE 8888
CMD ["/challenge/challenge"]
```

---

## Networking in kCTF

The default-deny NetworkPolicy means:
- Challenge pods cannot reach each other
- Challenge pods can only receive traffic from the IsolateX gateway
- Challenge pods can resolve DNS (UDP/TCP port 53 is allowed out)

If a challenge needs outbound internet access, add a specific NetworkPolicy
in the challenge's deployment config. See `infra/kctf/manifests/network-policy.yaml`.

---

## nsjail (optional, for additional sandboxing)

For the strongest isolation, you can run `nsjail` inside your kCTF pods.
nsjail provides another layer of Linux namespace isolation on top of Kubernetes.

Example: run your challenge binary inside nsjail within the pod:

```bash
nsjail \
  --mode o \
  --port 8888 \
  --chroot /chroot \
  --user 65534 \
  --group 65534 \
  --iface_no_lo \
  -- /challenge/challenge
```

See the nsjail documentation for full options. This is recommended for
pwn challenges running in kCTF (since container isolation is weaker than KVM).

---

## Verifying the cluster

```bash
# Check namespace
kubectl get namespace kctf

# Check NetworkPolicy
kubectl get networkpolicy -n kctf

# Check LimitRange
kubectl get limitrange -n kctf

# Check RBAC
kubectl get serviceaccount isolatex-worker -n kctf
kubectl get role isolatex-worker -n kctf
kubectl get rolebinding isolatex-worker -n kctf
```
