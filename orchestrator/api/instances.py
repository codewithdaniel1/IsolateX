from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timezone, timedelta
import httpx
import uuid

from orchestrator.db.session import get_db
from orchestrator.db.models import Instance, InstanceStatus, Challenge, Worker
from orchestrator.api.schemas import InstanceCreate, InstanceResponse
from orchestrator.api.deps import require_api_key
from orchestrator.core.flags import derive_flag
from orchestrator.core.router import register_route, deregister_route
from orchestrator.core.scheduler_worker import pick_worker
from orchestrator.config import settings
import structlog

router = APIRouter(prefix="/instances", tags=["instances"])
log = structlog.get_logger()


@router.post("", response_model=InstanceResponse, status_code=201,
             dependencies=[Depends(require_api_key)])
async def create_instance(
    body: InstanceCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Enforce max one active instance per team per challenge
    existing = await db.execute(
        select(Instance).where(
            and_(
                Instance.team_id == body.team_id,
                Instance.challenge_id == body.challenge_id,
                Instance.status.in_([InstanceStatus.pending, InstanceStatus.running]),
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="instance already running for this team")

    challenge_result = await db.execute(
        select(Challenge).where(Challenge.id == body.challenge_id)
    )
    challenge = challenge_result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=404, detail="challenge not found")

    worker = await pick_worker(db, challenge.runtime)
    if not worker:
        raise HTTPException(status_code=503, detail="no available worker for this runtime")

    instance_id = uuid.uuid4()
    flag = derive_flag(body.team_id, body.challenge_id, str(instance_id), challenge.flag_salt)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=challenge.ttl_seconds)

    inst = Instance(
        id=instance_id,
        team_id=body.team_id,
        challenge_id=body.challenge_id,
        worker_id=worker.id,
        runtime=challenge.runtime,
        status=InstanceStatus.pending,
        flag=flag,
        expires_at=expires_at,
    )
    db.add(inst)
    await db.commit()
    await db.refresh(inst)

    background.add_task(_launch_on_worker, inst, challenge, worker)
    log.info("instance created", instance_id=str(instance_id), team=body.team_id)
    return inst


@router.get("/{instance_id}", response_model=InstanceResponse,
            dependencies=[Depends(require_api_key)])
async def get_instance(instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404, detail="not found")
    return inst


@router.get("/team/{team_id}/{challenge_id}", response_model=InstanceResponse,
            dependencies=[Depends(require_api_key)])
async def get_team_instance(team_id: str, challenge_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Instance).where(
            and_(
                Instance.team_id == team_id,
                Instance.challenge_id == challenge_id,
                Instance.status.in_([InstanceStatus.pending, InstanceStatus.running]),
            )
        )
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404, detail="no active instance")
    return inst


@router.delete("/{instance_id}", status_code=204,
               dependencies=[Depends(require_api_key)])
async def destroy_instance(
    instance_id: uuid.UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404, detail="not found")

    inst.status = InstanceStatus.destroyed
    await db.commit()

    background.add_task(_destroy_on_worker, inst)


# ---------------------------------------------------------------------------
# Background helpers
# ---------------------------------------------------------------------------

async def _launch_on_worker(inst: Instance, challenge: Challenge, worker: Worker):
    payload = {
        "instance_id": str(inst.id),
        "challenge_id": challenge.id,
        "runtime": challenge.runtime.value,
        "kernel_image": challenge.kernel_image,
        "rootfs_image": challenge.rootfs_image,
        "image": challenge.image,
        "cpu_count": challenge.cpu_count,
        "memory_mb": challenge.memory_mb,
        "port": challenge.port,
        "flag": inst.flag,
        "extra_config": challenge.extra_config,
    }
    url = f"http://{worker.address}:{worker.agent_port}/launch"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            endpoint = await register_route(
                str(inst.id), challenge.id, worker.address, data["port"]
            )
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Instance).where(Instance.id == inst.id))
                record = result.scalar_one()
                record.status = InstanceStatus.running
                record.endpoint = f"https://{endpoint}" if settings.tls_enabled else f"http://{endpoint}"
                await db.commit()
            log.info("instance running", instance_id=str(inst.id), endpoint=endpoint)
    except Exception as e:
        log.error("launch failed", instance_id=str(inst.id), error=str(e))
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Instance).where(Instance.id == inst.id))
            record = result.scalar_one_or_none()
            if record:
                record.status = InstanceStatus.error
                await db.commit()


async def _destroy_on_worker(inst: Instance):
    await deregister_route(str(inst.id), inst.challenge_id)
    if not inst.worker_id:
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Worker).where(Worker.id == inst.worker_id))
        worker = result.scalar_one_or_none()
    if not worker:
        return
    url = f"http://{worker.address}:{worker.agent_port}/destroy/{inst.id}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.delete(url)
    except Exception as e:
        log.error("destroy worker call failed", instance_id=str(inst.id), error=str(e))


# avoid circular import — import here after functions defined
from orchestrator.db.session import AsyncSessionLocal  # noqa: E402
