"""
Runtime adapter registry.

To add a new runtime:
1. Create worker/adapters/<runtime_name>.py implementing RuntimeAdapter
2. Import and register it here
3. See docs/adding-a-runtime.md for the full checklist
"""
from worker.adapters.base import RuntimeAdapter, LaunchRequest, LaunchResult
from worker.adapters.firecracker import FirecrackerAdapter
from worker.adapters.cloud_hypervisor import CloudHypervisorAdapter
from worker.adapters.kctf import KCTFAdapter
from worker.adapters.docker import DockerAdapter

ADAPTERS: dict[str, type[RuntimeAdapter]] = {
    "firecracker":      FirecrackerAdapter,
    "cloud_hypervisor": CloudHypervisorAdapter,
    "kctf":             KCTFAdapter,
    "docker":           DockerAdapter,
    # "gvisor":         GVisorAdapter,        # example future runtime
    # "kata":           KataAdapter,          # example future runtime
    # "qemu":           QEMUAdapter,          # example future runtime
}


def get_adapter(runtime: str) -> RuntimeAdapter:
    cls = ADAPTERS.get(runtime)
    if cls is None:
        raise ValueError(
            f"Unknown runtime '{runtime}'. Available: {list(ADAPTERS)}. "
            "See docs/adding-a-runtime.md to add a new one."
        )
    return cls()
