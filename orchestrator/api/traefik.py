"""
Traefik HTTP provider endpoint.
Traefik polls GET /traefik/config every few seconds.
IsolateX reads all running instances from Postgres and returns a complete
Traefik dynamic configuration so Traefik knows where to route each subdomain.

Nginx operators: see gateway/nginx/ for the sidecar reload approach instead.
"""
from fastapi import APIRouter, Depends
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


@router.get("/config", dependencies=[Depends(require_api_key)])
async def traefik_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Instance).where(Instance.status == InstanceStatus.running)
    )
    rows = result.scalars().all()

    routers = {}
    services = {}
    middlewares = {}

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

        routers[key] = {
            "rule": f"Host(`{subdomain}`)",
            "service": key,
            "entryPoints": ["websecure" if settings.tls_enabled else "web"],
            "middlewares": [auth_key],
            **({"tls": {"certResolver": "letsencrypt"}} if settings.tls_enabled else {}),
        }
        services[key] = {
            "loadBalancer": {
                "servers": [{"url": f"http://{inst.backend_host}:{inst.backend_port}"}]
            }
        }
        middlewares[auth_key] = {
            "forwardAuth": {
                "address": auth_url,
                "trustForwardHeader": True,
            }
        }

    return {"http": {"routers": routers, "services": services, "middlewares": middlewares}}
