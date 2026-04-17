#!/usr/bin/env bash
# IsolateX — kCTF fresh cluster setup
# Sets up a local k3s or kind cluster configured for kCTF-style challenge isolation.
#
# What this does:
#   1. Installs k3s (or kind for local dev)
#   2. Creates the kctf namespace
#   3. Applies a default-deny NetworkPolicy for east-west isolation
#   4. Applies LimitRange so pods can't consume unlimited resources
#   5. Applies PodSecurity admission (restricted profile)
#   6. Creates a ServiceAccount for the IsolateX worker to use
#
# Usage:
#   ./setup-cluster.sh [--kind]       # use kind for local dev (no root needed)
#   ./setup-cluster.sh                # use k3s (production-ish, needs root)
set -euo pipefail

USE_KIND=false
if [[ "${1:-}" == "--kind" ]]; then USE_KIND=true; fi

NAMESPACE="kctf"

echo "[kctf-setup] Starting kCTF cluster setup..."

# ── 1. Install cluster ────────────────────────────────────────────────────────
if [[ $USE_KIND == true ]]; then
    echo "[kctf-setup] Setting up kind cluster..."
    if ! command -v kind &>/dev/null; then
        echo "[kctf-setup] Installing kind..."
        curl -Lo /usr/local/bin/kind \
            https://kind.sigs.k8s.io/dl/v0.22.0/kind-linux-amd64
        chmod +x /usr/local/bin/kind
    fi
    kind create cluster --name isolatex --config - <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
  - role: worker
EOF
    export KUBECONFIG="$(kind get kubeconfig-path --name isolatex 2>/dev/null || echo ~/.kube/config)"
else
    echo "[kctf-setup] Installing k3s..."
    curl -sfL https://get.k3s.io | sh -s - \
        --disable traefik \
        --disable servicelb
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi

echo "[kctf-setup] Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s

# ── 2. Namespace ──────────────────────────────────────────────────────────────
echo "[kctf-setup] Creating namespace $NAMESPACE..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# Enable restricted pod security for the namespace
kubectl label namespace "$NAMESPACE" \
    pod-security.kubernetes.io/enforce=restricted \
    pod-security.kubernetes.io/audit=restricted \
    pod-security.kubernetes.io/warn=restricted \
    --overwrite

# ── 3. Apply all kCTF manifests ────────────────────────────────────────────────
echo "[kctf-setup] Applying kCTF manifests..."
kubectl apply -f "$(dirname "$0")/manifests/"

echo ""
echo "[kctf-setup] Done! kCTF namespace is ready."
echo "  Namespace:    $NAMESPACE"
echo "  KUBECONFIG:   ${KUBECONFIG}"
echo ""
echo "  Next: configure the IsolateX worker with:"
echo "    RUNTIME=kctf"
echo "    KUBECONFIG=${KUBECONFIG}"
echo "    KCTF_NAMESPACE=${NAMESPACE}"
