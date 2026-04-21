#!/usr/bin/env bash
# IsolateX Setup Script
# Installs and configures everything needed to run IsolateX.
# Safe to re-run — already-installed tools are updated, not reinstalled.
#
# Usage:
#   ./setup.sh              # One-command setup (auto-detects host capabilities)
#   ./setup.sh --external-ctfd                     # Auto-integrate with existing CTFd
#   ./setup.sh --external-ctfd-container <name>    # Integrate a running CTFd container
#   ./setup.sh --external-ctfd-path <path>         # Integrate a filesystem CTFd checkout
#   ./setup.sh --external-ctfd-url <url>           # Existing CTFd base URL (default: http://localhost:8000)
#   ./setup.sh --isolatex-url-for-ctfd <url>       # URL CTFd should use to reach IsolateX

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[IsolateX]${NC} $*"; }
success() { echo -e "${GREEN}[IsolateX]${NC} $*"; }
warn()    { echo -e "${YELLOW}[IsolateX]${NC} $*"; }
error()   { echo -e "${RED}[IsolateX]${NC} $*"; exit 1; }

# ── Args ──────────────────────────────────────────────────────────────────────
EXTERNAL_CTFD=false
EXTERNAL_CTFD_PATH=""
EXTERNAL_CTFD_CONTAINER=""
EXTERNAL_CTFD_URL="${CTFD_URL:-http://localhost:8000}"
ISOLATEX_URL_FOR_CTFD=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --external-ctfd)
      EXTERNAL_CTFD=true
      shift
      ;;
    --external-ctfd-path)
      EXTERNAL_CTFD=true
      EXTERNAL_CTFD_PATH="${2:-}"
      [ -n "$EXTERNAL_CTFD_PATH" ] || error "--external-ctfd-path requires a value"
      shift 2
      ;;
    --external-ctfd-container)
      EXTERNAL_CTFD=true
      EXTERNAL_CTFD_CONTAINER="${2:-}"
      [ -n "$EXTERNAL_CTFD_CONTAINER" ] || error "--external-ctfd-container requires a value"
      shift 2
      ;;
    --external-ctfd-url)
      EXTERNAL_CTFD=true
      EXTERNAL_CTFD_URL="${2:-}"
      [ -n "$EXTERNAL_CTFD_URL" ] || error "--external-ctfd-url requires a value"
      shift 2
      ;;
    --isolatex-url-for-ctfd)
      ISOLATEX_URL_FOR_CTFD="${2:-}"
      [ -n "$ISOLATEX_URL_FOR_CTFD" ] || error "--isolatex-url-for-ctfd requires a value"
      shift 2
      ;;
    *)
      error "Unknown argument: $1"
      ;;
  esac
done

OS="$(uname -s)"
ARCH="$(uname -m)"
[ "$ARCH" = "x86_64" ] && ARCH_ALT="amd64" || ARCH_ALT="arm64"
AUTO_INSTALL_KCTF=false
AUTO_INSTALL_KATA_FC=false
KCTF_READY=false
KATA_FC_READY=false
KCTF_REASON=""
KATA_FC_REASON=""

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

get_env_value() {
  local key="$1"
  local value=""
  if [ -f .env ]; then
    value="$(grep -E "^${key}=" .env | tail -1 | cut -d= -f2-)"
  fi
  echo "$value"
}

detect_external_ctfd_container() {
  # Best-effort: pick a running container name that contains "ctfd".
  docker ps --format '{{.Names}}' | grep -E 'ctfd' | head -1 || true
}

detect_isolatex_url_for_container() {
  local container="$1"
  local gateway
  gateway="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.Gateway}} {{end}}' "$container" 2>/dev/null | awk '{print $1}')"
  if [ -n "$gateway" ]; then
    echo "http://${gateway}:8080"
    return
  fi
  echo "http://host.docker.internal:8080"
}

write_plugin_env_file() {
  local target_file="$1"
  local isolatex_url="$2"
  local api_key="$3"
  local kctf_enabled="$4"
  local kctf_reason="$5"
  local kata_enabled="$6"
  local kata_reason="$7"
  cat > "$target_file" <<EOF
ISOLATEX_URL=${isolatex_url}
ISOLATEX_API_KEY=${api_key}
ISOLATEX_CAP_KCTF_ENABLED=${kctf_enabled}
ISOLATEX_CAP_KCTF_REASON=${kctf_reason}
ISOLATEX_CAP_KATA_FIRECRACKER_ENABLED=${kata_enabled}
ISOLATEX_CAP_KATA_FIRECRACKER_REASON=${kata_reason}
EOF
  chmod 600 "$target_file" 2>/dev/null || true
}

sync_local_plugin_env_file() {
  local api_key
  local kctf_enabled="false"
  local kata_enabled="false"

  api_key="$(get_env_value API_KEY)"
  [ -n "$api_key" ] || return 0

  if $KCTF_READY; then
    kctf_enabled="true"
  fi
  if $KATA_FC_READY; then
    kata_enabled="true"
  fi

  write_plugin_env_file \
    "./ctfd-plugin/.isolatex.env" \
    "http://orchestrator:8080" \
    "$api_key" \
    "$kctf_enabled" \
    "${KCTF_REASON}" \
    "$kata_enabled" \
    "${KATA_FC_REASON}"
}

plan_runtime_installs() {
  if [ "$OS" != "Linux" ]; then
    warn "Advanced runtimes require Linux host. Proceeding with Docker runtime only on ${OS}."
    AUTO_INSTALL_KCTF=false
    AUTO_INSTALL_KATA_FC=false
    KCTF_REASON="kCTF is disabled because this host is not Linux. This cannot be enabled from the IsolateX page. Run IsolateX on a Linux host, then rerun ./setup.sh."
    KATA_FC_REASON="kata-firecracker is disabled because this host is not Linux. This cannot be enabled from the IsolateX page. Run IsolateX on a Linux host with KVM enabled, then rerun ./setup.sh."
    return
  fi

  AUTO_INSTALL_KCTF=true

  if [ -e /dev/kvm ]; then
    AUTO_INSTALL_KATA_FC=true
    KATA_FC_REASON=""
  else
    warn "/dev/kvm not detected. kCTF will be installed; Kata-Firecracker will be skipped."
    AUTO_INSTALL_KATA_FC=false
    KATA_FC_REASON="kata-firecracker is disabled because /dev/kvm is unavailable. This cannot be enabled from the IsolateX page. Enable VT-x/AMD-V in BIOS and ensure KVM modules are loaded, then rerun ./setup.sh."
  fi

  KCTF_REASON=""
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

# ── 5. Kata + Firecracker ─────────────────────────────────────────────────────
install_or_update_kata_firecracker() {
  info "Setting up Kata + Firecracker backend..."

  case "$OS" in
    Linux)
      # Check KVM availability
      if ! ls /dev/kvm &>/dev/null; then
        error "/dev/kvm not found. Kata + Firecracker requires KVM hardware virtualization. Enable VT-x/AMD-V in BIOS."
      fi

      # Install Kata Containers
      if command -v kata-runtime &>/dev/null; then
        CURRENT=$(kata-runtime --version 2>/dev/null | head -1)
        info "Kata found (${CURRENT}) — updating..."
      else
        info "Installing Kata Containers..."
      fi
      bash -c "$(curl -fsSL https://raw.githubusercontent.com/kata-containers/kata-containers/main/utils/kata-manager.sh) install-kata-containers"

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

  ensure_env_key() {
    local key="$1"
    if ! grep -Eq "^${key}=" .env; then
      echo "${key}=$(openssl rand -hex 32)" >> .env
      info "Added missing ${key} to .env"
    fi
  }

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

  # Backfill any keys that older .env files might not include.
  ensure_env_key "API_KEY"
  ensure_env_key "FLAG_HMAC_SECRET"
  ensure_env_key "SECRET_KEY"
  ensure_env_key "CTFD_SECRET_KEY"
  chmod 600 .env 2>/dev/null || true
  sync_local_plugin_env_file

  # Pull/build images
  info "Building IsolateX Docker images..."
  docker compose pull --ignore-buildable 2>/dev/null || true
  docker compose build orchestrator worker-docker
  if ! $EXTERNAL_CTFD; then
    # Bundled mode: try latest CTFd first, then fallback images if latest build fails.
    if ! bash ./scripts/build-ctfd-with-fallback.sh; then
      error "Bundled CTFd build failed for latest and fallback image candidates."
    fi
  fi

  # Start the stack
  info "Starting IsolateX stack..."
  if $EXTERNAL_CTFD; then
    # External CTFd mode: run IsolateX core services only.
    docker compose up -d postgres redis orchestrator worker-docker
  else
    # Bundled mode: full stack including CTFd + gateway.
    docker compose up -d
  fi

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
  if $EXTERNAL_CTFD; then
    echo "  External CTFd:   ${EXTERNAL_CTFD_URL}"
  else
    echo "  CTFd:            http://localhost:8000"
  fi
  echo "  Orchestrator:    http://localhost:8080/docs"
  if $EXTERNAL_CTFD; then
    echo "  Admin UI:        ${EXTERNAL_CTFD_URL%/}/isolatex/admin"
  else
    echo "  Admin UI:        http://localhost:8000/isolatex/admin  (after CTFd setup)"
  fi
  echo ""
}

integrate_external_ctfd() {
  local api_key
  local isolatex_url
  local plugin_env_file
  local auto_container
  local kctf_enabled="false"
  local kata_enabled="false"

  api_key="$(get_env_value API_KEY)"
  [ -n "$api_key" ] || error "API_KEY missing from .env"
  if $KCTF_READY; then
    kctf_enabled="true"
  fi
  if $KATA_FC_READY; then
    kata_enabled="true"
  fi

  if [ -n "$ISOLATEX_URL_FOR_CTFD" ]; then
    isolatex_url="$ISOLATEX_URL_FOR_CTFD"
  elif [ -n "$EXTERNAL_CTFD_CONTAINER" ]; then
    isolatex_url="$(detect_isolatex_url_for_container "$EXTERNAL_CTFD_CONTAINER")"
  else
    isolatex_url="http://localhost:8080"
  fi

  info "Configuring IsolateX plugin connection for external CTFd..."
  success "Using IsolateX URL for CTFd: ${isolatex_url}"

  if [ -n "$EXTERNAL_CTFD_PATH" ]; then
    local plugin_target="${EXTERNAL_CTFD_PATH%/}/CTFd/plugins/isolatex"
    info "Installing plugin into filesystem CTFd path: ${plugin_target}"
    mkdir -p "${EXTERNAL_CTFD_PATH%/}/CTFd/plugins"
    rm -rf "$plugin_target"
    cp -R ./ctfd-plugin "$plugin_target"
    plugin_env_file="${plugin_target}/.isolatex.env"
    write_plugin_env_file "$plugin_env_file" "$isolatex_url" "$api_key" "$kctf_enabled" "${KCTF_REASON}" "$kata_enabled" "${KATA_FC_REASON}"

    if [ -x "${EXTERNAL_CTFD_PATH%/}/venv/bin/pip" ]; then
      "${EXTERNAL_CTFD_PATH%/}/venv/bin/pip" install --quiet httpx==0.27.0 || warn "Could not install httpx in venv"
    elif [ -x "${EXTERNAL_CTFD_PATH%/}/.venv/bin/pip" ]; then
      "${EXTERNAL_CTFD_PATH%/}/.venv/bin/pip" install --quiet httpx==0.27.0 || warn "Could not install httpx in .venv"
    else
      warn "Could not find a Python virtualenv at ${EXTERNAL_CTFD_PATH}. Ensure httpx is installed in CTFd."
    fi
    success "Filesystem CTFd plugin installed and configured."
  fi

  if [ -z "$EXTERNAL_CTFD_CONTAINER" ]; then
    auto_container="$(detect_external_ctfd_container)"
    if [ -n "$auto_container" ]; then
      EXTERNAL_CTFD_CONTAINER="$auto_container"
      if [ -z "$ISOLATEX_URL_FOR_CTFD" ]; then
        isolatex_url="$(detect_isolatex_url_for_container "$EXTERNAL_CTFD_CONTAINER")"
        success "Auto-detected CTFd container '${EXTERNAL_CTFD_CONTAINER}'"
        success "Auto-detected container-to-host IsolateX URL: ${isolatex_url}"
      fi
    fi
  fi

  if [ -n "$EXTERNAL_CTFD_CONTAINER" ]; then
    info "Installing plugin into container: ${EXTERNAL_CTFD_CONTAINER}"
    docker exec "$EXTERNAL_CTFD_CONTAINER" sh -lc "mkdir -p /opt/CTFd/CTFd/plugins/isolatex"
    docker cp ./ctfd-plugin/. "${EXTERNAL_CTFD_CONTAINER}:/opt/CTFd/CTFd/plugins/isolatex/"
    docker exec -i "$EXTERNAL_CTFD_CONTAINER" sh -lc "cat > /opt/CTFd/CTFd/plugins/isolatex/.isolatex.env" <<EOF
ISOLATEX_URL=${isolatex_url}
ISOLATEX_API_KEY=${api_key}
ISOLATEX_CAP_KCTF_ENABLED=${kctf_enabled}
ISOLATEX_CAP_KCTF_REASON=${KCTF_REASON}
ISOLATEX_CAP_KATA_FIRECRACKER_ENABLED=${kata_enabled}
ISOLATEX_CAP_KATA_FIRECRACKER_REASON=${KATA_FC_REASON}
EOF
    docker exec "$EXTERNAL_CTFD_CONTAINER" sh -lc "chmod 600 /opt/CTFd/CTFd/plugins/isolatex/.isolatex.env" >/dev/null 2>&1 || true
    docker exec "$EXTERNAL_CTFD_CONTAINER" sh -lc "(python -m pip install --no-cache-dir httpx==0.27.0 || pip install --no-cache-dir httpx==0.27.0)" \
      >/dev/null 2>&1 || warn "Could not auto-install httpx inside container; ensure it exists in CTFd."
    docker restart "$EXTERNAL_CTFD_CONTAINER" >/dev/null 2>&1 || warn "Could not auto-restart ${EXTERNAL_CTFD_CONTAINER}; restart it manually."
    success "Container CTFd plugin installed and configured."
  fi

  if [ -z "$EXTERNAL_CTFD_PATH" ] && [ -z "$EXTERNAL_CTFD_CONTAINER" ]; then
    warn "Could not auto-detect an external CTFd path/container for plugin install."
    echo "  Manual fallback:"
    echo "    1) Copy ./ctfd-plugin to your CTFd plugins folder as 'isolatex'"
    echo "    2) Create CTFd plugin file '.isolatex.env' with:"
    echo "         ISOLATEX_URL=${isolatex_url}"
    echo "         ISOLATEX_API_KEY=<copy API_KEY from IsolateX .env>"
    echo "    3) Restart CTFd"
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
install_or_update_docker
plan_runtime_installs

if $AUTO_INSTALL_KCTF; then
  if install_or_update_kubectl && install_or_update_k3s && setup_kctf_namespace; then
    KCTF_READY=true
    KCTF_REASON=""
  else
    warn "kCTF installation did not fully complete. Continuing with Docker runtime."
    KCTF_READY=false
    KCTF_REASON="kCTF setup did not complete on this host. This cannot be enabled from the IsolateX page. Check setup logs, fix Kubernetes prerequisites, then rerun ./setup.sh."
  fi
fi

if $AUTO_INSTALL_KATA_FC; then
  if $KCTF_READY && install_or_update_kata_firecracker; then
    KATA_FC_READY=true
    KATA_FC_REASON=""
  else
    warn "Kata-Firecracker setup skipped or failed. Continuing without kata-firecracker runtime."
    KATA_FC_READY=false
    if [ -z "$KATA_FC_REASON" ]; then
      KATA_FC_REASON="kata-firecracker setup did not complete on this host. This cannot be enabled from the IsolateX page. Verify KVM and Kata prerequisites, then rerun ./setup.sh."
    fi
  fi
fi

# Auto-switch to external mode when a non-IsolateX CTFd is already reachable.
if ! $EXTERNAL_CTFD; then
  local_ctfd_id="$(docker compose ps -q ctfd 2>/dev/null || true)"
  if [ -z "$local_ctfd_id" ] && curl -fsS "${EXTERNAL_CTFD_URL%/}/login" >/dev/null 2>&1; then
    EXTERNAL_CTFD=true
    info "Detected existing CTFd at ${EXTERNAL_CTFD_URL}; enabling external integration mode."
  fi
fi

setup_isolatex

if $EXTERNAL_CTFD; then
  integrate_external_ctfd
fi

echo ""
success "Setup complete!"
echo ""
echo "  Next steps:"
if $EXTERNAL_CTFD; then
  echo "  1. Open your CTFd at ${EXTERNAL_CTFD_URL}"
  echo "  2. Confirm IsolateX appears in the admin navbar"
  echo "  3. Go to Admin → Plugins → IsolateX and configure challenge runtimes"
else
  echo "  1. Go to http://localhost:8000 and complete CTFd setup"
  echo "  2. Go to Admin → Plugins → IsolateX to configure TTL and resource tiers"
fi
echo "  4. Register your challenges (existing CTFd challenge names are skipped, never overwritten):"
echo "     curl -X POST http://localhost:8080/challenges \\"
echo "       -H 'x-api-key: \$(grep API_KEY .env | cut -d= -f2)' \\"
echo "       -H 'content-type: application/json' \\"
echo "       -d '{\"id\":\"my-challenge\",\"name\":\"My Challenge\",\"runtime\":\"docker\",\"image\":\"my-image:latest\",\"port\":80}'"
echo ""
if $KCTF_READY; then
  echo "  Kubernetes is running. Worker env vars for kCTF runtime:"
  echo "    RUNTIME=kctf"
  echo "    KUBECONFIG=\$HOME/.kube/config"
  echo "    KCTF_NAMESPACE=kctf"
  echo ""
fi
if $KATA_FC_READY; then
  echo "  Kata + Firecracker RuntimeClass installed:"
  kubectl get runtimeclass 2>/dev/null || true
  echo ""
fi
