"""
Cloud Hypervisor MicroVM Adapter
==================================
Cloud Hypervisor is an open-source VMM from Intel/Microsoft that is the
second most popular Firecracker alternative.  It supports virtio-net,
virtio-block, and a REST API on a Unix socket.

Security model is equivalent to Firecracker:
- KVM-based isolation
- One microVM per team instance
- Dedicated tap device per instance
- No shared rootfs (copy-per-instance)
- Minimal device model

See docs/cloud-hypervisor-host-setup.md for host preparation.
"""
import asyncio
import json
import os
import shutil
import structlog
from pathlib import Path

from worker.adapters.base import RuntimeAdapter, LaunchRequest, LaunchResult
from worker.networking.tap import create_tap, delete_tap, assign_tap_to_bridge
from worker.config import settings

log = structlog.get_logger()


class CloudHypervisorAdapter(RuntimeAdapter):
    def __init__(self):
        self._instances: dict[str, dict] = {}

    async def launch(self, req: LaunchRequest) -> LaunchResult:
        if req.instance_id in self._instances:
            return LaunchResult(
                port=self._instances[req.instance_id]["host_port"],
                metadata=self._instances[req.instance_id],
            )

        host_port = _allocate_port(req.instance_id)
        run_dir = Path(settings.firecracker_run_dir) / req.instance_id
        run_dir.mkdir(parents=True, exist_ok=True)

        rootfs = run_dir / "rootfs.raw"
        await asyncio.to_thread(shutil.copy2, req.rootfs_image, str(rootfs))

        tap_name = f"cht_{req.instance_id[:8]}"
        await create_tap(tap_name)
        await assign_tap_to_bridge(tap_name, settings.tap_bridge)

        api_socket = run_dir / "ch.sock"

        proc = await _start_cloud_hypervisor(
            req=req,
            rootfs=rootfs,
            tap_name=tap_name,
            api_socket=api_socket,
            host_port=host_port,
        )

        metadata = {
            "host_port": host_port,
            "tap_name": tap_name,
            "run_dir": str(run_dir),
            "pid": proc.pid,
            "api_socket": str(api_socket),
        }
        self._instances[req.instance_id] = metadata
        log.info("cloud-hypervisor instance started", instance_id=req.instance_id, port=host_port)
        return LaunchResult(port=host_port, metadata=metadata)

    async def destroy(self, instance_id: str) -> None:
        meta = self._instances.pop(instance_id, None)
        if not meta:
            return

        pid = meta.get("pid")
        if pid:
            try:
                os.kill(pid, 15)
                await asyncio.sleep(1)
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

        tap = meta.get("tap_name")
        if tap:
            try:
                await delete_tap(tap)
            except Exception as e:
                log.warning("tap delete failed", tap=tap, error=str(e))

        run_dir = meta.get("run_dir")
        if run_dir and os.path.exists(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)

        log.info("cloud-hypervisor instance destroyed", instance_id=instance_id)


def _allocate_port(instance_id: str) -> int:
    span = settings.port_range_end - settings.port_range_start
    return settings.port_range_start + (int(instance_id.replace("-", ""), 16) % span)


async def _start_cloud_hypervisor(
    req: LaunchRequest,
    rootfs: Path,
    tap_name: str,
    api_socket: Path,
    host_port: int,
) -> asyncio.subprocess.Process:
    guest_ip = f"192.168.{(host_port - settings.port_range_start) // 254}.{((host_port - settings.port_range_start) % 254) + 1}"
    cmd = [
        settings.cloud_hypervisor_bin,
        "--api-socket", str(api_socket),
        "--kernel", req.kernel_image,
        "--disk", f"path={rootfs}",
        "--cpus", f"boot={req.cpu_count}",
        "--memory", f"size={req.memory_mb}M",
        "--net", f"tap={tap_name},mac=02:CH:{host_port:04x}:00:01",
        "--cmdline", (
            f"console=hvc0 root=/dev/vda rw "
            f"ip={guest_ip}::192.168.0.1:255.255.0.0::eth0:off "
            f"ISOLATEX_FLAG={req.flag} ISOLATEX_PORT={req.port}"
        ),
        "--serial", "off",
        "--console", "off",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    log.info("cloud-hypervisor process started", pid=proc.pid)
    return proc
