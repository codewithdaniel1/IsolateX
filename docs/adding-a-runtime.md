# Adding a New Runtime to IsolateX

IsolateX is designed to support any microVM or container runtime.
This document walks through every step needed to add one.

Examples of runtimes you might add:
- gVisor (runsc)
- Kata Containers
- QEMU/KVM full VMs
- Podman
- Incus / LXD
- Any future microVM (e.g. Dragonball, NEMU)

---

## Step 1 — Create the adapter

Create `worker/adapters/<your_runtime>.py`.
Implement the `RuntimeAdapter` base class from `worker/adapters/base.py`.

```python
from worker.adapters.base import RuntimeAdapter, LaunchRequest, LaunchResult

class MyRuntimeAdapter(RuntimeAdapter):

    async def launch(self, req: LaunchRequest) -> LaunchResult:
        # req fields available:
        #   req.instance_id     str   unique ID for this instance
        #   req.challenge_id    str   challenge identifier
        #   req.runtime         str   runtime name (your runtime)
        #   req.kernel_image    str?  path to kernel (microVMs only)
        #   req.rootfs_image    str?  path to rootfs (microVMs only)
        #   req.image           str?  container image tag (containers only)
        #   req.cpu_count       int   vCPUs / CPU limit
        #   req.memory_mb       int   memory in MB
        #   req.port            int   challenge port inside the runtime
        #   req.flag            str   per-team flag to inject
        #   req.extra_config    str?  JSON string of runtime-specific config

        host_port = ...  # the port on THIS host that traffic should go to
        # ... your launch logic ...
        return LaunchResult(port=host_port, metadata={"your": "metadata"})

    async def destroy(self, instance_id: str) -> None:
        # ... your teardown logic ...
        pass
```

Rules:
- `launch()` must be idempotent: if called twice with the same `instance_id`, return the same result without starting a duplicate.
- `destroy()` must be safe to call even if `launch()` never completed.
- Never let exceptions from one instance affect other instances.
- Clean up ALL resources on destroy: processes, network devices, volumes, temp files.

---

## Step 2 — Register the adapter

Open `worker/adapters/__init__.py` and add your adapter:

```python
from worker.adapters.my_runtime import MyRuntimeAdapter

ADAPTERS: dict[str, type[RuntimeAdapter]] = {
    "firecracker":      FirecrackerAdapter,
    "cloud_hypervisor": CloudHypervisorAdapter,
    "kctf":             KCTFAdapter,
    "docker":           DockerAdapter,
    "my_runtime":       MyRuntimeAdapter,   # ← add this
}
```

---

## Step 3 — Add the runtime type to the orchestrator

Open `orchestrator/db/models.py` and add to `RuntimeType`:

```python
class RuntimeType(str, enum.Enum):
    firecracker      = "firecracker"
    cloud_hypervisor = "cloud_hypervisor"
    kctf             = "kctf"
    docker           = "docker"
    my_runtime       = "my_runtime"    # ← add this
```

---

## Step 4 — Run a worker with the new runtime

On your compute host:

```bash
RUNTIME=my_runtime \
ORCHESTRATOR_URL=http://orchestrator:8080 \
ORCHESTRATOR_API_KEY=your-key \
uvicorn worker.main:app --host 0.0.0.0 --port 9090
```

The worker auto-registers with the orchestrator on startup.

---

## Step 5 — Register a challenge using the new runtime

```bash
curl -X POST http://orchestrator:8080/challenges \
  -H "x-api-key: $API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "id": "web300",
    "name": "Web 300",
    "runtime": "my_runtime",
    "image": "my-challenge-image:latest",
    "cpu_count": 1,
    "memory_mb": 512,
    "port": 8080,
    "ttl_seconds": 3600
  }'
```

---

## Step 6 — Document your runtime

Add a file `docs/<your-runtime>-setup.md` explaining:
- Host requirements (packages, kernel modules, capabilities)
- How to install the runtime binary
- Any networking setup needed
- Security model differences vs Firecracker/Docker
- Known limitations

---

## Security checklist for new runtimes

Before using a runtime in production with hostile workloads, verify:

- [ ] Instances cannot reach each other's network
- [ ] Instances cannot reach the worker agent API
- [ ] Instances cannot reach the orchestrator
- [ ] Instances cannot access the host's filesystem outside the jail
- [ ] CPU and memory limits are enforced by the runtime, not just advisory
- [ ] Escape from the runtime does not give host root
- [ ] Instance teardown completely removes all associated resources
- [ ] Flag is injected in a way players cannot extract from image metadata

For microVMs (KVM-based): the kernel isolation is the primary boundary.
For containers: additional seccomp, capability drop, and NetworkPolicy controls are required.
The weaker the isolation primitive, the more layered controls you need.

---

## LaunchRequest / LaunchResult reference

```python
@dataclass
class LaunchRequest:
    instance_id:  str            # UUID
    challenge_id: str
    runtime:      str
    kernel_image: Optional[str]  # microVM: local path to vmlinux
    rootfs_image: Optional[str]  # microVM: local path to rootfs.ext4
    image:        Optional[str]  # container: docker image tag
    cpu_count:    int
    memory_mb:    int
    port:         int            # port the challenge listens on INSIDE the runtime
    flag:         str            # inject this as ISOLATEX_FLAG env var
    extra_config: Optional[str]  # JSON string for runtime-specific options

@dataclass
class LaunchResult:
    port:     int   # port on THIS HOST that the gateway should forward to
    metadata: dict  # arbitrary data; store anything you need for destroy()
```
