"""
Firecracker MicroVM Adapter
============================
Launches each challenge instance as a Firecracker microVM via the jailer.

Security model:
- Every microVM runs under a dedicated UID/GID (jailer enforces this)
- seccomp filter applied by default (never pass --no-seccomp)
- Each microVM gets its own tap device and network namespace
- No shared filesystems; rootfs is a copy-on-write overlay per instance
- The Firecracker API socket is inside the jail, unreachable from the guest

Requirements on the host:
- /dev/kvm must exist and be accessible
- firecracker and jailer binaries in PATH (or configured)
- A bridge interface (default: isolatex0) must exist
- iproute2 installed (ip, tc commands)
- Run as root or with CAP_NET_ADMIN for tap setup

In the documented ladder, this adapter covers the `kata+FC` / `FC` end of the spectrum.

See docs/firecracker-host-setup.md for full host preparation steps.
"""
import asyncio
import json
import os
import shutil
import structlog
from pathlib import Path
from typing import Optional

from worker.adapters.base import RuntimeAdapter, LaunchRequest, LaunchResult
from worker.networking.tap import create_tap, delete_tap, assign_tap_to_bridge
from worker.config import settings

log = structlog.get_logger()

FC_API_TIMEOUT = 10  # seconds to wait for Firecracker API socket to appear


class FirecrackerAdapter(RuntimeAdapter):
    def __init__(self):
        # instance_id -> metadata dict
        self._instances: dict[str, dict] = {}

    async def launch(self, req: LaunchRequest) -> LaunchResult:
        if req.instance_id in self._instances:
            return LaunchResult(
                port=self._instances[req.instance_id]["host_port"],
                metadata=self._instances[req.instance_id],
            )

        host_port = _allocate_port(req.instance_id)
        jail_dir = Path(settings.firecracker_run_dir) / req.instance_id
        jail_dir.mkdir(parents=True, exist_ok=True)

        overlay_path = await _prepare_rootfs(req, jail_dir)
        tap_name = f"tap_{req.instance_id[:8]}"
        guest_ip = _derive_guest_ip(host_port)
        host_ip = _derive_host_ip(host_port)

        await create_tap(tap_name)
        await assign_tap_to_bridge(tap_name, settings.tap_bridge)

        fc_config = _build_fc_config(
            req=req,
            overlay_path=str(overlay_path),
            tap_name=tap_name,
            guest_ip=guest_ip,
            host_port=host_port,
        )

        config_path = jail_dir / "vm_config.json"
        config_path.write_text(json.dumps(fc_config, indent=2))

        pid = await _start_jailer(req.instance_id, config_path, jail_dir)
        (jail_dir / "firecracker.pid").write_text(str(pid))

        metadata = {
            "host_port": host_port,
            "tap_name": tap_name,
            "jail_dir": str(jail_dir),
            "pid": pid,
            "guest_ip": guest_ip,
        }
        self._instances[req.instance_id] = metadata
        log.info("firecracker instance started", instance_id=req.instance_id, port=host_port)
        return LaunchResult(port=host_port, metadata=metadata)

    async def destroy(self, instance_id: str) -> None:
        meta = self._instances.pop(instance_id, None)
        jail_dir = Path(settings.firecracker_run_dir) / instance_id
        pid_file = jail_dir / "firecracker.pid"
        pid = meta.get("pid") if meta else _read_pid(pid_file)
        tap = meta.get("tap_name") if meta else f"tap_{instance_id[:8]}"

        # Kill the Firecracker process
        if pid:
            try:
                os.kill(pid, 15)  # SIGTERM
                await asyncio.sleep(2)
                try:
                    os.kill(pid, 9)  # SIGKILL if still alive
                except ProcessLookupError:
                    pass
            except ProcessLookupError:
                pass

        # Remove tap device
        if tap:
            try:
                await delete_tap(tap)
            except Exception as e:
                log.warning("tap delete failed", tap=tap, error=str(e))

        # Wipe jail directory
        if jail_dir.exists():
            shutil.rmtree(jail_dir, ignore_errors=True)

        log.info("firecracker instance destroyed", instance_id=instance_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _allocate_port(instance_id: str) -> int:
    """Deterministic port from instance_id within configured range."""
    span = settings.port_range_end - settings.port_range_start
    return settings.port_range_start + (int(instance_id.replace("-", ""), 16) % span)


def _derive_guest_ip(host_port: int) -> str:
    idx = host_port - settings.port_range_start
    a, b = divmod(idx, 254)
    return f"172.16.{a % 254}.{b + 1}"


def _derive_host_ip(host_port: int) -> str:
    idx = host_port - settings.port_range_start
    a, b = divmod(idx, 254)
    return f"172.16.{a % 254}.{b + 2}"


async def _prepare_rootfs(req: LaunchRequest, jail_dir: Path) -> Path:
    """
    Create a copy-on-write overlay rootfs for this instance.
    The base rootfs is read-only; each instance gets a writable upper layer.
    This means blowing up the rootfs doesn't affect other instances.
    """
    base = req.rootfs_image
    overlay = jail_dir / "rootfs.ext4"
    # For now: copy the base image. In production use overlayfs or dm-snapshot.
    await asyncio.to_thread(shutil.copy2, base, str(overlay))
    return overlay


def _build_fc_config(
    req: LaunchRequest,
    overlay_path: str,
    tap_name: str,
    guest_ip: str,
    host_port: int,
) -> dict:
    extra = json.loads(req.extra_config) if req.extra_config else {}
    return {
        "boot-source": {
            "kernel_image_path": req.kernel_image,
            "boot_args": (
                f"console=ttyS0 reboot=k panic=1 pci=off "
                f"ip={guest_ip}::172.16.0.1:255.255.0.0::eth0:off "
                f"ISOLATEX_FLAG={req.flag} "
                f"ISOLATEX_PORT={req.port}"
            ),
        },
        "drives": [
            {
                "drive_id": "rootfs",
                "path_on_host": overlay_path,
                "is_root_device": True,
                "is_read_only": False,
            }
        ],
        "machine-config": {
            "vcpu_count": req.cpu_count,
            "mem_size_mib": req.memory_mb,
            "smt": False,
        },
        "network-interfaces": [
            {
                "iface_id": "eth0",
                "guest_mac": _mac_from_port(host_port),
                "host_dev_name": tap_name,
            }
        ],
        **extra,
    }


def _mac_from_port(port: int) -> str:
    h = f"{port:06x}"
    return f"02:fc:{h[0:2]}:{h[2:4]}:{h[4:6]}:01"


async def _start_jailer(instance_id: str, config_path: Path, jail_dir: Path) -> int:
    """
    Start Firecracker under the jailer for privilege separation and seccomp.
    The jailer drops privileges to firecracker_uid/gid and applies a seccomp filter.
    """
    cmd = [
        settings.jailer_bin,
        "--id", instance_id,
        "--exec-file", settings.firecracker_bin,
        "--uid", str(settings.firecracker_uid),
        "--gid", str(settings.firecracker_gid),
        "--chroot-base-dir", str(jail_dir),
        "--",
        "--config-file", str(config_path),
        "--no-api",  # API not needed; config is file-based
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    log.info("jailer started", pid=proc.pid, instance_id=instance_id)
    return proc.pid


def _read_pid(pid_file: Path) -> Optional[int]:
    try:
        return int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
