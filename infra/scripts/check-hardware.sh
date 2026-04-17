#!/usr/bin/env bash
# IsolateX hardware capability check
# Run this on any host before deploying a worker to know which runtimes are supported.
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
info() { echo -e "        $*"; }

echo ""
echo "══════════════════════════════════════════"
echo "  IsolateX Host Capability Check"
echo "══════════════════════════════════════════"
echo ""

SUPPORTS_MICROVM=true
SUPPORTS_KCTF=true
SUPPORTS_DOCKER=true

# ── KVM ──────────────────────────────────────────────────────────────────────
echo "▸ KVM / microVM support"
if [[ -c /dev/kvm ]]; then
    ok "/dev/kvm exists"
    if [[ -r /dev/kvm && -w /dev/kvm ]]; then
        ok "/dev/kvm is readable and writable"
    else
        fail "/dev/kvm exists but current user cannot access it"
        info "Fix: sudo usermod -aG kvm \$USER  or  chmod 666 /dev/kvm"
        SUPPORTS_MICROVM=false
    fi
else
    fail "/dev/kvm not found"
    info "Check: CPU supports virtualization (VT-x / AMD-V) and it is enabled in BIOS"
    info "Check: 'lscpu | grep Virtualization'"
    info "Check: 'cat /proc/cpuinfo | grep vmx' or 'grep svm'"
    SUPPORTS_MICROVM=false
fi

if grep -qE '(vmx|svm)' /proc/cpuinfo 2>/dev/null; then
    ok "CPU hardware virtualization flags present"
else
    fail "vmx/svm not in /proc/cpuinfo — virtualization may be disabled in BIOS"
    SUPPORTS_MICROVM=false
fi

# ── Firecracker ───────────────────────────────────────────────────────────────
echo ""
echo "▸ Firecracker"
if command -v firecracker &>/dev/null; then
    FC_VER=$(firecracker --version 2>&1 | head -1)
    ok "firecracker found: $FC_VER"
else
    warn "firecracker binary not found in PATH"
    info "Install: https://github.com/firecracker-microvm/firecracker/releases"
    SUPPORTS_MICROVM=false
fi

if command -v jailer &>/dev/null; then
    ok "jailer found"
else
    warn "jailer binary not found — required for Firecracker privilege separation"
    SUPPORTS_MICROVM=false
fi

# ── Cloud Hypervisor ──────────────────────────────────────────────────────────
echo ""
echo "▸ Cloud Hypervisor"
if command -v cloud-hypervisor &>/dev/null; then
    CHV_VER=$(cloud-hypervisor --version 2>&1 | head -1)
    ok "cloud-hypervisor found: $CHV_VER"
else
    warn "cloud-hypervisor not found (optional — only needed for cloud_hypervisor runtime)"
    info "Install: https://github.com/cloud-hypervisor/cloud-hypervisor/releases"
fi

# ── Networking ────────────────────────────────────────────────────────────────
echo ""
echo "▸ Networking (microVM tap support)"
if command -v ip &>/dev/null; then
    ok "iproute2 (ip) found"
else
    fail "iproute2 not found — required for tap device management"
    info "Install: apt install iproute2 / dnf install iproute"
    SUPPORTS_MICROVM=false
fi

if ip link show isolatex0 &>/dev/null; then
    ok "bridge isolatex0 exists"
else
    warn "bridge isolatex0 not found — create it before starting Firecracker workers"
    info "Fix: ip link add isolatex0 type bridge && ip link set isolatex0 up"
fi

# ── Docker ────────────────────────────────────────────────────────────────────
echo ""
echo "▸ Docker"
if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version)
    ok "docker found: $DOCKER_VER"
    if docker info &>/dev/null; then
        ok "docker daemon reachable"
    else
        fail "docker daemon not running or not accessible"
        info "Fix: sudo systemctl start docker  or  sudo usermod -aG docker \$USER"
        SUPPORTS_DOCKER=false
    fi
else
    fail "docker not found"
    info "Install: https://docs.docker.com/engine/install/"
    SUPPORTS_DOCKER=false
fi

# ── Kubernetes / kCTF ─────────────────────────────────────────────────────────
echo ""
echo "▸ Kubernetes / kCTF"
if command -v kubectl &>/dev/null; then
    KUBECTL_VER=$(kubectl version --client --short 2>/dev/null || kubectl version --client 2>/dev/null | head -1)
    ok "kubectl found: $KUBECTL_VER"
else
    warn "kubectl not found (only needed for kctf runtime)"
    info "Install: https://kubernetes.io/docs/tasks/tools/"
    SUPPORTS_KCTF=false
fi

if command -v helm &>/dev/null; then
    ok "helm found"
else
    warn "helm not found (needed for kCTF cluster setup)"
fi

# ── Kernel version ────────────────────────────────────────────────────────────
echo ""
echo "▸ Kernel"
KERNEL=$(uname -r)
KERNEL_MAJOR=$(uname -r | cut -d. -f1)
KERNEL_MINOR=$(uname -r | cut -d. -f2)
if [[ $KERNEL_MAJOR -gt 5 || ($KERNEL_MAJOR -eq 5 && $KERNEL_MINOR -ge 10) ]]; then
    ok "Kernel $KERNEL (>= 5.10, good for Firecracker)"
else
    warn "Kernel $KERNEL — Firecracker recommends >= 5.10"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Summary"
echo "══════════════════════════════════════════"
[[ $SUPPORTS_MICROVM == true ]] && ok "Firecracker / Cloud Hypervisor: SUPPORTED" || fail "Firecracker / Cloud Hypervisor: NOT supported on this host"
[[ $SUPPORTS_KCTF == true ]]    && ok "kCTF (Kubernetes): kubectl present"        || warn "kCTF: kubectl not found"
[[ $SUPPORTS_DOCKER == true ]]  && ok "Docker: SUPPORTED"                          || fail "Docker: NOT supported or daemon down"
echo ""
echo "See docs/ for setup guides for each runtime."
echo ""
