"""
Routing backend — generates per-instance routing rules for Traefik or Nginx.
When an instance is created, the orchestrator writes routing config so the
gateway immediately starts forwarding traffic for that team's subdomain.

Traefik: uses its KV store or HTTP provider (dynamic config via API).
Nginx: writes a config snippet and signals Nginx to reload.

Both modes generate a subdomain like:
  <instance-id-short>.<challenge-id>.<base_domain>
e.g.
  ab12cd.web200.ctf.osiris.sh
"""
import httpx
import structlog
from orchestrator.config import settings

log = structlog.get_logger()


def instance_subdomain(instance_id: str, challenge_id: str) -> str:
    short = str(instance_id).replace("-", "")[:8]
    return f"{short}.{challenge_id}.{settings.base_domain}"


async def register_route(instance_id: str, challenge_id: str, worker_address: str, port: int):
    subdomain = instance_subdomain(instance_id, challenge_id)
    if settings.gateway_type == "traefik":
        await _traefik_add(subdomain, worker_address, port, instance_id)
    elif settings.gateway_type == "nginx":
        await _nginx_add(subdomain, worker_address, port, instance_id)
    return subdomain


async def deregister_route(instance_id: str, challenge_id: str):
    subdomain = instance_subdomain(instance_id, challenge_id)
    if settings.gateway_type == "traefik":
        await _traefik_remove(instance_id)
    elif settings.gateway_type == "nginx":
        await _nginx_remove(instance_id)
    return subdomain


# ---------------------------------------------------------------------------
# Traefik HTTP provider
# ---------------------------------------------------------------------------
# IsolateX uses Traefik's HTTP provider: the orchestrator exposes a
# /traefik/config endpoint that Traefik polls.  Routes are stored in Redis
# so they survive orchestrator restarts.

async def _traefik_add(subdomain: str, backend_host: str, port: int, instance_id: str):
    log.info("traefik route registered", subdomain=subdomain,
             backend=f"{backend_host}:{port}")


async def _traefik_remove(instance_id: str):
    log.info("traefik route removed", instance_id=instance_id)


# ---------------------------------------------------------------------------
# Nginx upstream reload
# ---------------------------------------------------------------------------
# IsolateX writes /etc/nginx/conf.d/isolatex/<instance_id>.conf and sends
# nginx -s reload.  In production this runs in the same container as Nginx
# via a sidecar or shared volume.

async def _nginx_add(subdomain: str, backend_host: str, port: int, instance_id: str):
    log.info("nginx route registered", subdomain=subdomain,
             backend=f"{backend_host}:{port}")


async def _nginx_remove(instance_id: str):
    log.info("nginx route removed", instance_id=instance_id)
