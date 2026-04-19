"""
Runtime adapter registry.

Supported runtimes (weakest → strongest isolation):

  docker           standard containers
  kctf             Kubernetes pod + nsjail
  kata-firecracker kCTF + Kata Containers (Firecracker as the Kata hypervisor backend)
"""
from .base import RuntimeAdapter
from .docker import DockerAdapter
from .kctf import KCTFAdapter
from .kata import KataAdapter

ADAPTERS: dict[str, type[RuntimeAdapter]] = {
    "docker":           DockerAdapter,
    "kctf":             KCTFAdapter,
    "kata-firecracker": KataAdapter,
}


def get_adapter(runtime: str) -> RuntimeAdapter:
    cls = ADAPTERS.get(runtime)
    if cls is None:
        raise ValueError(
            f"Unknown runtime '{runtime}'. Available: {list(ADAPTERS)}."
        )
    if runtime == "kata-firecracker":
        return cls(runtime=runtime)
    return cls()
