from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from orchestrator.db.session import get_db
from orchestrator.db.models import Worker
from orchestrator.api.schemas import WorkerRegister, WorkerResponse
from orchestrator.api.deps import require_api_key
import structlog

router = APIRouter(prefix="/workers", tags=["workers"])
log = structlog.get_logger()


@router.post("", response_model=WorkerResponse, status_code=201,
             dependencies=[Depends(require_api_key)])
async def register_worker(body: WorkerRegister, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.id == body.id))
    worker = result.scalar_one_or_none()
    if worker:
        worker.address = body.address
        worker.agent_port = body.agent_port
        worker.runtime = body.runtime
        worker.max_instances = body.max_instances
        worker.active = True
        worker.last_seen = datetime.now(timezone.utc)
    else:
        worker = Worker(**body.model_dump())
        worker.last_seen = datetime.now(timezone.utc)
        db.add(worker)
    await db.commit()
    await db.refresh(worker)
    log.info("worker registered", worker_id=body.id, runtime=body.runtime)
    return worker


@router.post("/{worker_id}/heartbeat", status_code=204,
             dependencies=[Depends(require_api_key)])
async def heartbeat(worker_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="worker not found")
    worker.last_seen = datetime.now(timezone.utc)
    await db.commit()


@router.get("", response_model=list[WorkerResponse],
            dependencies=[Depends(require_api_key)])
async def list_workers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.active == True))
    return result.scalars().all()


@router.delete("/{worker_id}", status_code=204,
               dependencies=[Depends(require_api_key)])
async def deregister_worker(worker_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="worker not found")
    worker.active = False
    await db.commit()
