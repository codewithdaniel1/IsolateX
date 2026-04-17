# Firecracker Host Setup

This guide prepares a Linux host to run IsolateX Firecracker workers.

## Requirements

- Bare-metal Linux host (or a VM with nested virtualization enabled)
- Kernel >= 5.10
- `/dev/kvm` accessible
- Root or `CAP_NET_ADMIN` for tap device management
- iproute2 installed

Run the capability check first:
```bash
./infra/scripts/check-hardware.sh
```

---

## 1. Verify KVM access

```bash
ls -la /dev/kvm
# Should show: crw-rw---- 1 root kvm 10, 232 ...

# Add your user to the kvm group
sudo usermod -aG kvm $USER

# Or for the worker process, ensure it runs with access to /dev/kvm
```

---

## 2. Install Firecracker and jailer

```bash
FC_VERSION="1.9.0"
ARCH="x86_64"

wget "https://github.com/firecracker-microvm/firecracker/releases/download/v${FC_VERSION}/firecracker-v${FC_VERSION}-${ARCH}.tgz"
tar -xvf firecracker-v${FC_VERSION}-${ARCH}.tgz
sudo mv release-v${FC_VERSION}-${ARCH}/firecracker-v${FC_VERSION}-${ARCH} /usr/local/bin/firecracker
sudo mv release-v${FC_VERSION}-${ARCH}/jailer-v${FC_VERSION}-${ARCH} /usr/local/bin/jailer
sudo chmod +x /usr/local/bin/firecracker /usr/local/bin/jailer

# Verify
firecracker --version
jailer --version
```

---

## 3. Create the isolatex bridge

Each microVM tap device is attached to this bridge.
Traffic between tap devices is blocked via ebtables (step 4).

```bash
# Create bridge
sudo ip link add isolatex0 type bridge
sudo ip link set isolatex0 up
sudo ip addr add 172.16.0.1/16 dev isolatex0

# Persist across reboots (systemd-networkd example)
sudo tee /etc/systemd/network/99-isolatex.netdev > /dev/null <<'EOF'
[NetDev]
Name=isolatex0
Kind=bridge
EOF

sudo tee /etc/systemd/network/99-isolatex.network > /dev/null <<'EOF'
[Match]
Name=isolatex0

[Network]
Address=172.16.0.1/16
EOF

sudo systemctl restart systemd-networkd
```

---

## 4. Block east-west traffic between microVMs

Tap devices on the same bridge can talk to each other by default.
Block this with ebtables so instances cannot reach each other.

```bash
sudo apt install ebtables   # or: dnf install ebtables

# Drop all traffic between ports on the isolatex0 bridge
# (allows tap→host but not tap→tap)
sudo ebtables -A FORWARD --logical-in isolatex0 --logical-out isolatex0 -j DROP

# Persist
sudo ebtables-save > /etc/ebtables.conf

# Restore on boot (add to /etc/rc.local or a systemd service)
sudo ebtables-restore < /etc/ebtables.conf
```

---

## 5. Create jailer UID/GID

The jailer drops Firecracker to a dedicated unprivileged UID.

```bash
sudo groupadd -g 10000 firecracker
sudo useradd -u 10000 -g 10000 -r -s /sbin/nologin firecracker
```

---

## 6. Set up the Firecracker run directory

```bash
sudo mkdir -p /run/isolatex/firecracker
sudo chown root:firecracker /run/isolatex/firecracker
sudo chmod 770 /run/isolatex/firecracker
```

---

## 7. Enable IP forwarding

```bash
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.d/99-isolatex.conf

# NAT so guests can reach the challenge's own port via host routing
sudo iptables -t nat -A POSTROUTING -s 172.16.0.0/16 -j MASQUERADE
```

---

## 8. Build challenge images

```bash
./infra/firecracker/build-image.sh challenges/web300/ /images/web300/
```

---

## 9. Start the worker

```bash
RUNTIME=firecracker \
FIRECRACKER_BIN=/usr/local/bin/firecracker \
JAILER_BIN=/usr/local/bin/jailer \
FIRECRACKER_RUN_DIR=/run/isolatex/firecracker \
FIRECRACKER_UID=10000 \
FIRECRACKER_GID=10000 \
TAP_BRIDGE=isolatex0 \
ORCHESTRATOR_URL=http://orchestrator:8080 \
ORCHESTRATOR_API_KEY=your-api-key \
uvicorn worker.main:app --host 0.0.0.0 --port 9090
```

---

## Security notes

- Never pass `--no-seccomp` to the jailer in production.
- The jailer uses a chroot — the guest cannot see the host filesystem.
- Each microVM gets its own kernel, so a kernel exploit in the guest does not directly affect the host.
- Periodically update the host kernel and Firecracker binaries.
- Monitor for jailer or Firecracker CVEs.
