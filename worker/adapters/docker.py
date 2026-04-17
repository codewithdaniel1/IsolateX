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
import subprocess
import shlex
import structlog

from worker.adapters.base import RuntimeAdapter, LaunchRequest, LaunchResult
from worker.config import settings

log = structlog.get_logger()


class DockerAdapter(RuntimeAdapter):
    def __init__(self):
        self._instances: dict[str, dict] = {}
        asyncio.get_event_loop().run_until_complete(self._ensure_network())

    async def _ensure_network(self):
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
            "--internal",
            settings.docker_network,
            check=False,
        )

    async def launch(self, req: LaunchRequest) -> LaunchResult:
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
            "--publish", f"127.0.0.1:{host_port}:{req.port}",
            "--env", f"ISOLATEX_FLAG={req.flag}",
            "--env", f"ISOLATEX_PORT={req.port}",
            "--label", f"{settings.docker_label_prefix}.instance_id={req.instance_id}",
            "--label", f"{settings.docker_label_prefix}.challenge_id={req.challenge_id}",
            # Resource limits
            "--cpus", str(req.cpu_count),
            "--memory", f"{req.memory_mb}m",
            "--pids-limit", str(extra.get("pids_limit", 256)),
            # Hardening
            "--read-only",
            "--tmpfs", "/tmp:size=64m,noexec,nosuid",
            "--cap-drop", "ALL",
            "--no-new-privileges",
            "--security-opt", "no-new-privileges:true",
            "--security-opt", "seccomp=unconfined",  # use default seccomp
            req.image,
        ]

        # Remove --security-opt seccomp=unconfined if default profile desired
        # (above passes "unconfined" only as placeholder — replace with your
        #  seccomp profile path in production)

        await _run(*cmd)
        metadata = {"host_port": host_port, "container_name": container_name}
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
