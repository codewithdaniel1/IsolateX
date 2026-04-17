"""
Worker picker — chooses the least-loaded worker that supports the requested runtime.
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta

from orchestrator.db.models import Worker, Instance, InstanceStatus, RuntimeType
from orchestrator.config import settings


async def pick_worker(db: AsyncSession, runtime: RuntimeType) -> Worker | None:
    """
    Returns the active worker for the given runtime with the most spare capacity.
    Returns None if no worker is available.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.worker_heartbeat_timeout_seconds
    )

    # Count both in-flight and active instances per worker.
    subq = (
        select(Instance.worker_id, func.count(Instance.id).label("count"))
        .where(Instance.status.in_([InstanceStatus.pending, InstanceStatus.running]))
        .group_by(Instance.worker_id)
        .subquery()
    )

    result = await db.execute(
        select(Worker, func.coalesce(subq.c.count, 0).label("load"))
        .outerjoin(subq, Worker.id == subq.c.worker_id)
        .where(
            Worker.active == True,
            Worker.runtime == runtime,
            Worker.last_seen >= cutoff,
        )
        .order_by(
            (Worker.max_instances - func.coalesce(subq.c.count, 0)).desc()
        )
    )

    row = result.first()
    if row is None:
        return None

    worker, load = row
    if load >= worker.max_instances:
        return None

    return worker
