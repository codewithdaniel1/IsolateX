"""
Routing backend — registers per-instance routes with Traefik.

Traefik polls /traefik/config every 5s (HTTP provider). Routes are
derived from running instances in the database at poll time, so no
explicit add/remove is needed — this module provides helpers for
consistent subdomain generation used when building the endpoint URL.

Subdomain format:  <instance-id-short>.<challenge-id>.<base_domain>
e.g.               ab12cd34.web200.ctf.osiris.sh
"""
import structlog
from orchestrator.config import settings

log = structlog.get_logger()


def instance_subdomain(instance_id: str, challenge_id: str) -> str:
    short = str(instance_id).replace("-", "")[:8]
    return f"{short}.{challenge_id}.{settings.base_domain}"


async def register_route(instance_id: str, challenge_id: str, backend_host: str, backend_port: int) -> str:
    subdomain = instance_subdomain(instance_id, challenge_id)
    log.info(
        "traefik route registered",
        subdomain=subdomain,
        backend=f"{backend_host}:{backend_port}",
    )
    return subdomain


async def deregister_route(instance_id: str, challenge_id: str) -> str:
    subdomain = instance_subdomain(instance_id, challenge_id)
    log.info("traefik route removed", instance_id=instance_id, subdomain=subdomain)
    return subdomain
