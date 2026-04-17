"""
Runtime Adapter Interface
=========================

Isolation spectrum used in docs:
docker -> kCTF -> kata -> kata-firecracker

Actual runtime strings in code today:
- docker
- kctf
- kata
- kata-firecracker

To add a new runtime (e.g. gVisor, Kata Containers, QEMU/KVM):
  1. Create a new file in worker/adapters/<your_runtime>.py
  2. Subclass RuntimeAdapter
  3. Implement launch() and destroy()
  4. Register it in worker/adapters/__init__.py
  5. Add the runtime name to orchestrator/db/models.py RuntimeType enum
  6. Document it in docs/adding-a-runtime.md

Your adapter receives a LaunchRequest (all fields the orchestrator knows about the
challenge) and must return a LaunchResult with the host port the challenge listens on.
The orchestrator uses that port to register the gateway route.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LaunchRequest:
    instance_id: str
    challenge_id: str
    runtime: str
    # microVM fields
    kernel_image: Optional[str]
    rootfs_image: Optional[str]
    # container fields
    image: Optional[str]
    # resources
    cpu_count: int
    memory_mb: int
    port: int
    flag: str
    # arbitrary runtime-specific config as JSON string
    extra_config: Optional[str]


@dataclass
class LaunchResult:
    # The host port that traffic should be forwarded to for this instance
    port: int
    # Any metadata the adapter wants to store for destroy (stored in memory on the worker)
    metadata: dict


class RuntimeAdapter(ABC):
    @abstractmethod
    async def launch(self, req: LaunchRequest) -> LaunchResult:
        """
        Start an isolated environment for the given instance.
        Must be idempotent: if called twice with the same instance_id, return
        the existing result rather than starting a duplicate.
        """
        ...

    @abstractmethod
    async def destroy(self, instance_id: str) -> None:
        """
        Tear down and clean up all resources for the given instance.
        Must be safe to call even if launch() never completed.
        """
        ...
