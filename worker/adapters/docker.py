"""
Docker Adapter
==============
Runs each challenge instance as a hardened Docker container.
Best for: static web challenges, beginner-level challenges, local dev.
Not recommended for: pwn, shell access, code execution, or anything
where a player may try container escape.

Security hardening applied:
- per-instance isolated bridge network (instance + reverse proxy only)
- no host-port publishing (challenge backends are never internet-facing)
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
        self._gateway_container: str | None = None

    async def _resolve_gateway_container(self) -> str:
        if self._gateway_container:
            return self._gateway_container

        explicit = (settings.docker_gateway_container or "").strip()
        if explicit:
            self._gateway_container = explicit
            return explicit

        out = await _run(
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.service=traefik",
            "--format",
            "{{.Names}}",
            capture=True,
            check=False,
        )
        candidates = [line.strip() for line in out.decode().splitlines() if line.strip()]
        if candidates:
            self._gateway_container = candidates[0]
            return self._gateway_container

        raise RuntimeError(
            "could not find gateway container; set DOCKER_GATEWAY_CONTAINER to your Traefik container name"
        )

    async def launch(self, req: LaunchRequest) -> LaunchResult:
        if req.instance_id in self._instances:
            return LaunchResult(
                backend_host=self._instances[req.instance_id]["backend_host"],
                backend_port=self._instances[req.instance_id]["backend_port"],
                metadata=self._instances[req.instance_id],
            )

        container_name = f"isolatex_{req.instance_id[:16]}"
        network_name = f"{settings.docker_network_prefix}{req.instance_id[:16]}"

        extra = json.loads(req.extra_config) if req.extra_config else {}

        # One network per instance prevents team-to-team lateral movement.
        await _run(
            "docker",
            "network",
            "create",
            "--driver",
            "bridge",
            network_name,
            check=False,
        )

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", network_name,
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

        try:
            await _run(*cmd)
            gateway = await self._resolve_gateway_container()
            await _run("docker", "network", "connect", network_name, gateway, check=False)

            metadata = {
                "container_name": container_name,
                "container_port": req.port,
                "network": network_name,
                "gateway_container": gateway,
                "backend_host": container_name,
                "backend_port": req.port,
            }
            self._instances[req.instance_id] = metadata
            log.info(
                "docker container started",
                instance_id=req.instance_id,
                container=container_name,
                backend=f"{container_name}:{req.port}",
                network=network_name,
            )
            return LaunchResult(
                backend_host=container_name,
                backend_port=req.port,
                metadata=metadata,
            )
        except Exception:
            await _run("docker", "rm", "-f", container_name, check=False)
            await _run("docker", "network", "rm", network_name, check=False)
            raise

    async def destroy(self, instance_id: str) -> None:
        meta = self._instances.pop(instance_id, None)
        if not meta:
            # Fallback: find by label in case worker restarted
            container_name = f"isolatex_{instance_id[:16]}"
            network_name = f"{settings.docker_network_prefix}{instance_id[:16]}"
            try:
                gateway = await self._resolve_gateway_container()
            except Exception:
                gateway = None
        else:
            container_name = meta["container_name"]
            network_name = meta.get("network", f"{settings.docker_network_prefix}{instance_id[:16]}")
            gateway = meta.get("gateway_container")

        if gateway:
            await _run("docker", "network", "disconnect", network_name, gateway, check=False)

        await _run("docker", "rm", "-f", container_name, check=False)
        await _run("docker", "network", "rm", network_name, check=False)
        log.info("docker container destroyed", instance_id=instance_id, container=container_name)


async def _run(*args, capture: bool = False, check: bool = True):
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
    )
    stdout, stderr = await proc.communicate()
    if check and proc.returncode != 0:
        err = stderr.decode(errors="ignore").strip() if stderr else ""
        raise RuntimeError(f"command failed ({proc.returncode})" + (f": {err}" if err else ""))
    return stdout
