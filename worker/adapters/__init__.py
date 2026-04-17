"""
Runtime adapter registry.

Supported runtimes (weakest → strongest isolation):

  docker           standard containers
  kctf             Kubernetes pod + nsjail
  kata             kCTF + Kata Containers (default hypervisor: QEMU)
  kata-firecracker kCTF + Kata Containers (Firecracker as the Kata hypervisor backend)

Both kata and kata-firecracker are Kubernetes-native. The difference is which
hypervisor Kata uses underneath. kata-firecracker has a smaller attack surface.
"""
from .base import RuntimeAdapter
from .docker import DockerAdapter
from .kctf import KCTFAdapter
from .kata import KataAdapter

ADAPTERS: dict[str, type[RuntimeAdapter]] = {
    "docker":           DockerAdapter,
    "kctf":             KCTFAdapter,
    "kata":             KataAdapter,             # Kata with default hypervisor
    "kata-firecracker": KataAdapter,             # Kata with Firecracker backend
    # KataAdapter reads the runtime string to select the correct RuntimeClass.
    # "kata"            → uses RuntimeClass named "kata"
    # "kata-firecracker" → uses RuntimeClass named "kata-firecracker"
}


def get_adapter(runtime: str) -> RuntimeAdapter:
    cls = ADAPTERS.get(runtime)
    if cls is None:
        raise ValueError(
            f"Unknown runtime '{runtime}'. Available: {list(ADAPTERS)}."
        )
    return cls(runtime=runtime)
