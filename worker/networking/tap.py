"""
Tap device management for microVM networking (Firecracker).
Each microVM gets its own tap device attached to a shared bridge.
Traffic between tap devices on the same bridge is blocked by ebtables rules
set up during host preparation (see docs/firecracker-host-setup.md).
"""
import asyncio


async def create_tap(name: str) -> None:
    await _run("ip", "tuntap", "add", "dev", name, "mode", "tap")
    await _run("ip", "link", "set", name, "up")


async def delete_tap(name: str) -> None:
    await _run("ip", "link", "delete", name, check=False)


async def assign_tap_to_bridge(tap: str, bridge: str) -> None:
    await _run("ip", "link", "set", tap, "master", bridge)


async def _run(*args, check: bool = True):
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if check and proc.returncode != 0:
        raise RuntimeError(f"network command failed: {' '.join(args)}\n{stderr.decode()}")
