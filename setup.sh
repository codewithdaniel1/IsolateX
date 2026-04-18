#!/usr/bin/env bash
# IsolateX Setup Script
# Installs and configures everything needed to run IsolateX.
# Safe to re-run — already-installed tools are updated, not reinstalled.
#
# Usage:
#   ./setup.sh              # Docker runtime only (local dev)
#   ./setup.sh --kctf       # Docker + Kubernetes + kCTF
#   ./setup.sh --kata       # Docker + Kubernetes + kCTF + Kata Containers
#   ./setup.sh --kata-fc    # Docker + Kubernetes + kCTF + Kata + Firecracker
#   ./setup.sh --all        # Everything

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[IsolateX]${NC} $*"; }
success() { echo -e "${GREEN}[IsolateX]${NC} $*"; }
warn()    { echo -e "${YELLOW}[IsolateX]${NC} $*"; }
error()   { echo -e "${RED}[IsolateX]${NC} $*"; exit 1; }

# ── Args ──────────────────────────────────────────────────────────────────────
INSTALL_KCTF=false
INSTALL_KATA=false
INSTALL_KATA_FC=false

for arg in "$@"; do
  case $arg in
    --kctf)    INSTALL_KCTF=true ;;
    --kata)    INSTALL_KCTF=true; INSTALL_KATA=true ;;
    --kata-fc) INSTALL_KCTF=true; INSTALL_KATA=true; INSTALL_KATA_FC=true ;;
    --all)     INSTALL_KCTF=true; INSTALL_KATA=true; INSTALL_KATA_FC=true ;;
  esac
done

OS="$(uname -s)"
ARCH="$(uname -m)"
[ "$ARCH" = "x86_64" ] && ARCH_ALT="amd64" || ARCH_ALT="arm64"

echo ""
echo "  ██╗███████╗ ██████╗ ██╗      █████╗ ████████╗███████╗██╗  ██╗"
echo "  ██║██╔════╝██╔═══██╗██║     ██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝"
echo "  ██║███████╗██║   ██║██║     ███████║   ██║   █████╗   ╚███╔╝ "
echo "  ██║╚════██║██║   ██║██║     ██╔══██║   ██║   ██╔══╝   ██╔██╗ "
echo "  ██║███████║╚██████╔╝███████╗██║  ██║   ██║   ███████╗██╔╝ ██╗"
echo "  ╚═╝╚══════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝"
echo ""
info "Starting IsolateX setup..."
echo ""

# ── Helpers ───────────────────────────────────────────────────────────────────
need_cmd() { command -v "$1" &>/dev/null || error "Required command '$1' not found. Please install it first."; }

version_gte() {
  # Returns 0 if $1 >= $2 (both semver strings)
  printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

# ── 1. Docker ─────────────────────────────────────────────────────────────────
install_or_update_docker() {
  info "Checking Docker..."

  if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "0")
    success "Docker already installed (v${DOCKER_VER}) — updating..."
    case "$OS" in
      Linux)
        if command -v apt-get &>/dev/null; then
          sudo apt-get update -qq
          sudo apt-get install -y --only-upgrade docker-ce docker-ce-cli containerd.io docker-compose-plugin
        elif command -v yum &>/dev/null; then
          sudo yum update -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
        fi
        ;;
      Darwin)
        if command -v brew &>/dev/null; then
          brew upgrade --cask docker 2>/dev/null || true
        else
          warn "Update Docker Desktop manually from https://www.docker.com/products/docker-desktop/"
        fi
        ;;
    esac
  else
    info "Installing Docker..."
    case "$OS" in
      Linux)
        curl -fsSL https://get.docker.com | sudo sh
        sudo usermod -aG docker "$USER"
        sudo systemctl enable --now docker
        warn "You may need to log out and back in for docker group membership to take effect."
        ;;
      Darwin)
        if command -v brew &>/dev/null; then
          brew install --cask docker
          info "Opening Docker Desktop — please complete setup and then re-run this script."
          open /Applications/Docker.app
          exit 0
        else
          error "Please install Docker Desktop from https://www.docker.com/products/docker-desktop/ then re-run."
        fi
        ;;
      *)
        error "Unsupported OS: $OS. Install Docker manually: https://docs.docker.com/get-docker/"
        ;;
    esac
  fi

  # Verify Docker Compose v2
  if ! docker compose version &>/dev/null; then
    info "Installing Docker Compose plugin..."
    case "$OS" in
      Linux)
        COMPOSE_VER=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep tag_name | cut -d'"' -f4)
        sudo curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VER}/docker-compose-linux-${ARCH}" \
          -o /usr/local/lib/docker/cli-plugins/docker-compose
        sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
        ;;
    esac
  fi

  success "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null) ready."
}

# ── 2. kubectl ────────────────────────────────────────────────────────────────
install_or_update_kubectl() {
  info "Checking kubectl..."
  LATEST_K8S=$(curl -sL https://dl.k8s.io/release/stable.txt)

  if command -v kubectl &>/dev/null; then
    CURRENT=$(kubectl version --client -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['clientVersion']['gitVersion'])" 2>/dev/null || echo "v0")
    if version_gte "${CURRENT#v}" "${LATEST_K8S#v}"; then
      success "kubectl ${CURRENT} already up to date."
      return
    fi
    info "Updating kubectl ${CURRENT} → ${LATEST_K8S}..."
  else
    info "Installing kubectl ${LATEST_K8S}..."
  fi

  case "$OS" in
    Linux)
      curl -sLO "https://dl.k8s.io/release/${LATEST_K8S}/bin/linux/${ARCH_ALT}/kubectl"
      sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
      rm kubectl
      ;;
    Darwin)
      if command -v brew &>/dev/null; then
        brew install kubectl 2>/dev/null || brew upgrade kubectl
      else
        curl -sLO "https://dl.k8s.io/release/${LATEST_K8S}/bin/darwin/${ARCH_ALT}/kubectl"
        chmod +x kubectl && sudo mv kubectl /usr/local/bin/kubectl
      fi
      ;;
  esac
  success "kubectl $(kubectl version --client --short 2>/dev/null | head -1) ready."
}

# ── 3. k3s (lightweight Kubernetes for kCTF) ─────────────────────────────────
install_or_update_k3s() {
  info "Checking k3s (Kubernetes)..."

  if command -v k3s &>/dev/null; then
    CURRENT=$(k3s --version 2>/dev/null | awk '{print $3}')
    info "k3s ${CURRENT} found — updating..."
    curl -sfL https://get.k3s.io | sudo sh -s - --write-kubeconfig-mode 644
  else
    info "Installing k3s..."
    curl -sfL https://get.k3s.io | sudo sh -s - --write-kubeconfig-mode 644
    # Make kubeconfig available to current user
    mkdir -p "$HOME/.kube"
    sudo cp /etc/rancher/k3s/k3s.yaml "$HOME/.kube/config"
    sudo chown "$USER:$USER" "$HOME/.kube/config"
  fi

  # Wait for node to be ready
  info "Waiting for Kubernetes node to be ready..."
  for i in $(seq 1 30); do
    if kubectl get nodes 2>/dev/null | grep -q " Ready"; then
      break
    fi
    sleep 3
  done
  success "Kubernetes (k3s) ready: $(kubectl get nodes --no-headers 2>/dev/null | head -1)"
}

# ── 4. kCTF namespace + NetworkPolicy ─────────────────────────────────────────
setup_kctf_namespace() {
  info "Setting up kCTF namespace..."

  kubectl create namespace kctf --dry-run=client -o yaml | kubectl apply -f -

  # Default-deny NetworkPolicy
  cat <<'EOF' | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: kctf
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
EOF

  # Allow ingress only from the gateway (traefik) namespace
  cat <<'EOF' | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-gateway-ingress
  namespace: kctf
spec:
  podSelector:
    matchLabels:
      app: isolatex-challenge
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
EOF

  success "kCTF namespace ready."
}

# ── 5. Kata Containers ────────────────────────────────────────────────────────
install_or_update_kata() {
  info "Checking Kata Containers..."

  if command -v kata-runtime &>/dev/null; then
    CURRENT=$(kata-runtime --version 2>/dev/null | head -1)
    info "Kata found (${CURRENT}) — updating..."
  else
    info "Installing Kata Containers..."
  fi

  case "$OS" in
    Linux)
      # Kata Containers 3.x via official install script
      bash -c "$(curl -fsSL https://raw.githubusercontent.com/kata-containers/kata-containers/main/utils/kata-manager.sh) install-kata-containers"

      # Register RuntimeClass for kata (QEMU backend)
      cat <<'EOF' | kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata-qemu
EOF
      success "Kata (QEMU) RuntimeClass registered."
      ;;
    Darwin)
      warn "Kata Containers requires a Linux host. On macOS, use a Linux VM or cloud instance."
      warn "See: https://github.com/kata-containers/kata-containers/blob/main/docs/install/README.md"
      ;;
  esac
}

# ── 6. Kata + Firecracker ─────────────────────────────────────────────────────
install_or_update_kata_firecracker() {
  info "Setting up Kata + Firecracker backend..."

  case "$OS" in
    Linux)
      # Check KVM availability
      if ! ls /dev/kvm &>/dev/null; then
        error "/dev/kvm not found. Firecracker requires KVM hardware virtualization. Enable VT-x/AMD-V in BIOS."
      fi

      # Install Firecracker
      if command -v firecracker &>/dev/null; then
        FC_VER=$(firecracker --version 2>/dev/null | head -1)
        info "Firecracker found (${FC_VER}) — updating..."
      else
        info "Installing Firecracker..."
      fi

      FC_LATEST=$(curl -s https://api.github.com/repos/firecracker-microvm/firecracker/releases/latest | grep tag_name | cut -d'"' -f4)
      curl -sLO "https://github.com/firecracker-microvm/firecracker/releases/download/${FC_LATEST}/firecracker-${FC_LATEST}-${ARCH}.tgz"
      tar -xzf "firecracker-${FC_LATEST}-${ARCH}.tgz"
      sudo install -m 0755 "release-${FC_LATEST}-${ARCH}/firecracker-${FC_LATEST}-${ARCH}" /usr/local/bin/firecracker
      sudo install -m 0755 "release-${FC_LATEST}-${ARCH}/jailer-${FC_LATEST}-${ARCH}" /usr/local/bin/jailer
      rm -rf "firecracker-${FC_LATEST}-${ARCH}.tgz" "release-${FC_LATEST}-${ARCH}"

      # Configure Kata to use Firecracker
      sudo mkdir -p /etc/kata-containers
      sudo tee /etc/kata-containers/configuration-fc.toml > /dev/null <<'TOML'
[hypervisor.firecracker]
path = "/usr/local/bin/firecracker"
jailer_path = "/usr/local/bin/jailer"
kernel = "/opt/kata/share/kata-containers/vmlinux.container"
image = "/opt/kata/share/kata-containers/kata-containers.img"
TOML

      # Register RuntimeClass for kata-firecracker
      cat <<'EOF' | kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata-firecracker
handler: kata-fc
EOF
      success "Kata-Firecracker RuntimeClass registered."
      ;;
    Darwin)
      warn "Firecracker requires a Linux host with KVM. Not available on macOS."
      ;;
  esac
}

# ── 7. IsolateX stack ─────────────────────────────────────────────────────────
setup_isolatex() {
  info "Setting up IsolateX..."

  # Generate secrets if .env doesn't exist
  if [ ! -f .env ]; then
    info "Generating .env with random secrets..."
    cat > .env <<EOF
API_KEY=$(openssl rand -hex 32)
FLAG_HMAC_SECRET=$(openssl rand -hex 32)
SECRET_KEY=$(openssl rand -hex 32)
CTFD_SECRET_KEY=$(openssl rand -hex 32)
EOF
    success ".env created with random secrets."
  else
    success ".env already exists — keeping existing secrets."
  fi

  # Pull/build images
  info "Building IsolateX Docker images..."
  docker compose pull --ignore-buildable 2>/dev/null || true
  docker compose build

  # Start the stack
  info "Starting IsolateX stack..."
  docker compose up -d

  # Wait for orchestrator health
  info "Waiting for orchestrator to be ready..."
  for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/health &>/dev/null; then
      break
    fi
    sleep 2
  done

  success "IsolateX stack is running."
  echo ""
  echo "  CTFd:            http://localhost:8000"
  echo "  Orchestrator:    http://localhost:8080/docs"
  echo "  Admin UI:        http://localhost:8000/isolatex/admin  (after CTFd setup)"
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
install_or_update_docker

if $INSTALL_KCTF; then
  install_or_update_kubectl
  install_or_update_k3s
  setup_kctf_namespace
fi

if $INSTALL_KATA; then
  install_or_update_kata
fi

if $INSTALL_KATA_FC; then
  install_or_update_kata_firecracker
fi

setup_isolatex

echo ""
success "Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Go to http://localhost:8000 and complete CTFd setup"
echo "  2. Go to Admin → Plugins → IsolateX to configure TTL and resource tiers"
echo "  3. Register your challenges:"
echo "     curl -X POST http://localhost:8080/challenges \\"
echo "       -H 'x-api-key: \$(grep API_KEY .env | cut -d= -f2)' \\"
echo "       -H 'content-type: application/json' \\"
echo "       -d '{\"id\":\"my-challenge\",\"name\":\"My Challenge\",\"runtime\":\"docker\",\"image\":\"my-image:latest\",\"port\":80}'"
echo ""
if $INSTALL_KCTF; then
  echo "  Kubernetes is running. Worker env vars for kCTF runtime:"
  echo "    RUNTIME=kctf"
  echo "    KUBECONFIG=\$HOME/.kube/config"
  echo "    KCTF_NAMESPACE=kctf"
  echo ""
fi
if $INSTALL_KATA; then
  echo "  Kata RuntimeClasses installed:"
  kubectl get runtimeclass 2>/dev/null || true
  echo ""
fi
