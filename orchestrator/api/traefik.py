"""
Traefik HTTP provider endpoint.
Traefik polls GET /traefik/config every few seconds.
IsolateX reads all running instances from Postgres and returns a complete
Traefik dynamic configuration so Traefik knows where to route each subdomain.

Nginx operators: see gateway/nginx/ for the sidecar reload approach instead.
"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from orchestrator.db.session import get_db
from orchestrator.db.models import Instance, InstanceStatus
from orchestrator.core.router import instance_subdomain
from orchestrator.config import settings
from orchestrator.api.deps import require_api_key

router = APIRouter(prefix="/traefik", tags=["gateway"])
log = structlog.get_logger()


@router.get("/config")
async def traefik_config(
    x_api_key: str = Header(default="", alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    # Dev mode: Traefik HTTP provider cannot attach API-key headers in our default stack.
    # Allow internal unauthenticated polling only for localhost/no-TLS deployments.
    if not (settings.base_domain == "localhost" and not settings.tls_enabled):
        await require_api_key(x_api_key=x_api_key)

    result = await db.execute(
        select(Instance).where(
            Instance.status.in_([InstanceStatus.running, InstanceStatus.pending])
        )
    )
    rows = result.scalars().all()

    routers = {}
    services = {}
    middlewares = {}
    localhost_dev = settings.base_domain == "localhost" and not settings.tls_enabled

    for inst in rows:
        if not inst.backend_host or inst.backend_port is None:
            log.warning(
                "skipping route without backend target",
                instance_id=str(inst.id),
                backend_host=inst.backend_host,
                backend_port=inst.backend_port,
            )
            continue

        subdomain = instance_subdomain(str(inst.id), inst.challenge_id)
        key = str(inst.id).replace("-", "")[:12]
        auth_key = f"auth-{key}"
        auth_url = f"{settings.ctfd_url.rstrip('/')}/isolatex/authz?instance_id={inst.id}"

        route_middlewares = [] if localhost_dev else [auth_key]
        router_cfg = {
            "rule": f"Host(`{subdomain}`)",
            "service": key,
            "entryPoints": ["websecure" if settings.tls_enabled else "web"],
            **({"tls": {"certResolver": "letsencrypt"}} if settings.tls_enabled else {}),
        }
        if route_middlewares:
            router_cfg["middlewares"] = route_middlewares
        routers[key] = router_cfg
        services[key] = {
            "loadBalancer": {
                "servers": [{"url": f"http://{inst.backend_host}:{inst.backend_port}"}]
            }
        }
        if not localhost_dev:
            middlewares[auth_key] = {
                "forwardAuth": {
                    "address": auth_url,
                    "trustForwardHeader": True,
                }
            }

    http_cfg = {"routers": routers, "services": services}
    if middlewares:
        http_cfg["middlewares"] = middlewares
    return {"http": http_cfg}
