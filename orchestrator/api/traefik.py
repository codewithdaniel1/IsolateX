"""
Traefik HTTP provider endpoint.
Traefik polls GET /traefik/config every few seconds.
IsolateX reads all running instances from Redis and returns a complete
Traefik dynamic configuration so Traefik knows where to route each subdomain.

Nginx operators: see gateway/nginx/ for the sidecar reload approach instead.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from orchestrator.db.session import get_db
from orchestrator.db.models import Instance, InstanceStatus, Worker
from orchestrator.core.router import instance_subdomain
from orchestrator.config import settings
from orchestrator.api.deps import require_api_key

router = APIRouter(prefix="/traefik", tags=["gateway"])
log = structlog.get_logger()


@router.get("/config", dependencies=[Depends(require_api_key)])
async def traefik_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Instance, Worker)
        .join(Worker, Instance.worker_id == Worker.id)
        .where(Instance.status == InstanceStatus.running)
    )
    rows = result.all()

    routers = {}
    services = {}

    for inst, worker in rows:
        if inst.backend_port is None:
            log.warning("skipping route without backend port", instance_id=str(inst.id))
            continue

        subdomain = instance_subdomain(str(inst.id), inst.challenge_id)
        key = str(inst.id).replace("-", "")[:12]

        routers[key] = {
            "rule": f"Host(`{subdomain}`)",
            "service": key,
            "entryPoints": ["websecure" if settings.tls_enabled else "web"],
            **({"tls": {"certResolver": "letsencrypt"}} if settings.tls_enabled else {}),
        }
        services[key] = {
            "loadBalancer": {
                "servers": [{"url": f"http://{worker.address}:{inst.backend_port}"}]
            }
        }

    return {"http": {"routers": routers, "services": services}}
