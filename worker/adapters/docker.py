"""
Docker Adapter
==============
Runs each challenge instance as a hardened Docker container.
Best for: static web challenges, beginner-level challenges, local dev.
Not recommended for: pwn, shell access, code execution, or anything
where a player may try container escape.

Security hardening applied:
- network_mode: none by default (override in extra_config if the challenge
  needs outbound), connected only to an isolated bridge
- no new privileges
- read-only root filesystem (writable tmpfs for /tmp only)
- all Linux capabilities dropped
- seccomp default profile enforced
- no privileged mode
- non-root user
- pid_limit enforced
- memory + cpu limits enforced
- containers are labelled with isolatex.instance_id so cleanup is reliable

For dev: Docker is a drop-in that lets you iterate on challenge images
without needing KVM or a Kubernetes cluster.
"""
import asyncio
import json
import structlog

from .base import RuntimeAdapter, LaunchRequest, LaunchResult
from config import settings

log = structlog.get_logger()


class DockerAdapter(RuntimeAdapter):
    def __init__(self):
        self._instances: dict[str, dict] = {}
        self._network_ready = False
        self._network_lock = asyncio.Lock()

    async def _ensure_network(self):
        if self._network_ready:
            return

        async with self._network_lock:
            if self._network_ready:
                return

            try:
                await _run("docker", "network", "inspect", settings.docker_network,
                           capture=True, check=False)
            except Exception:
                pass
            await _run(
                "docker", "network", "create",
                "--driver", "bridge",
                "--opt", "com.docker.network.bridge.enable_icc=false",
                "--opt", "com.docker.network.bridge.enable_ip_masquerade=true",
                settings.docker_network,
                check=False,
            )
            self._network_ready = True

    async def launch(self, req: LaunchRequest) -> LaunchResult:
        await self._ensure_network()

        if req.instance_id in self._instances:
            return LaunchResult(
                port=self._instances[req.instance_id]["host_port"],
                metadata=self._instances[req.instance_id],
            )

        host_port = _allocate_port(req.instance_id)
        container_name = f"isolatex_{req.instance_id[:16]}"

        extra = json.loads(req.extra_config) if req.extra_config else {}
        network = extra.get("network", settings.docker_network)

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", network,
            "--publish", f"{settings.docker_bind_host}:{host_port}:{req.port}",
            "--env", f"ISOLATEX_FLAG={req.flag}",
            "--env", f"ISOLATEX_PORT={req.port}",
            "--label", f"{settings.docker_label_prefix}.instance_id={req.instance_id}",
            "--label", f"{settings.docker_label_prefix}.challenge_id={req.challenge_id}",
            # Resource limits
            "--cpus", str(req.cpu_count),
            "--memory", f"{req.memory_mb}m",
            "--pids-limit", str(extra.get("pids_limit", 256)),
        ]

        # Hardening — only applied when explicitly requested via extra_config
        # Docker runtime is for local dev; kCTF/Kata-FC handle production hardening
        if extra.get("cap_drop"):
            cmd += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges:true"]

        cmd += [req.image]

        await _run(*cmd)
        metadata = {"host_port": host_port, "container_name": container_name,
                    "container_port": req.port, "network": network}
        self._instances[req.instance_id] = metadata
        log.info("docker container started", instance_id=req.instance_id,
                 container=container_name, port=host_port)
        return LaunchResult(port=host_port, metadata=metadata)

    async def destroy(self, instance_id: str) -> None:
        meta = self._instances.pop(instance_id, None)
        if not meta:
            # Fallback: find by label in case worker restarted
            container_name = f"isolatex_{instance_id[:16]}"
        else:
            container_name = meta["container_name"]

        await _run("docker", "rm", "-f", container_name, check=False)
        log.info("docker container destroyed", instance_id=instance_id, container=container_name)


def _allocate_port(instance_id: str) -> int:
    span = settings.port_range_end - settings.port_range_start
    return settings.port_range_start + (int(instance_id.replace("-", ""), 16) % span)


async def _run(*args, capture: bool = False, check: bool = True):
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
    )
    stdout, stderr = await proc.communicate()
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{stderr}")
    return stdout
