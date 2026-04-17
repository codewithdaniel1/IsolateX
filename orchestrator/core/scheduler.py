"""
TTL reaper — runs every REAP_INTERVAL seconds, finds expired instances,
tells the appropriate worker to destroy them, then marks them destroyed.
"""
import asyncio
import httpx
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Instance, InstanceStatus, Worker
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.config import settings
import structlog

log = structlog.get_logger()


async def reap_expired():
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Instance).where(
                and_(
                    Instance.status == InstanceStatus.running,
                    Instance.expires_at <= now,
                )
            )
        )
        expired = result.scalars().all()

        for inst in expired:
            log.info("reaping expired instance", instance_id=str(inst.id), team=inst.team_id)
            await _destroy_instance(db, inst)


async def _destroy_instance(db: AsyncSession, inst: Instance):
    if inst.worker_id:
        worker_result = await db.execute(
            select(Worker).where(Worker.id == inst.worker_id)
        )
        worker = worker_result.scalar_one_or_none()
        if worker:
            url = f"http://{worker.address}:{worker.agent_port}/destroy/{inst.id}"
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.delete(url)
                    if resp.status_code not in (200, 204, 404):
                        log.warning("worker destroy returned unexpected status",
                                    status=resp.status_code, instance_id=str(inst.id))
            except Exception as e:
                log.error("failed to reach worker for destroy", error=str(e),
                          instance_id=str(inst.id))

    inst.status = InstanceStatus.destroyed
    inst.updated_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("instance destroyed", instance_id=str(inst.id))


async def run_reaper():
    while True:
        try:
            await reap_expired()
        except Exception as e:
            log.error("reaper error", error=str(e))
        await asyncio.sleep(settings.reap_interval_seconds)
