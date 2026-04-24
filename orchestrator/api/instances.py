"""
Instance lifecycle endpoints.

POST   /instances               Launch a new instance for a team
GET    /instances/{id}          Get instance by ID
GET    /instances/team/{team_id}/{challenge_id}  Get active instance for a team
DELETE /instances/{id}          Stop an instance
POST   /instances/{id}/restart  Stop + relaunch (TTL resets to full)
POST   /instances/{id}/renew    Extend TTL (capped at MAX_TTL_SECONDS from now)
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timezone, timedelta
import httpx
import uuid

from orchestrator.db.session import get_db
from orchestrator.db.models import Instance, InstanceStatus, Challenge, Worker
from orchestrator.api.schemas import InstanceCreate, InstanceResponse, RenewResponse
from orchestrator.api.deps import require_api_key
from orchestrator.api.settings import _get_setting
from orchestrator.core.flags import derive_flag
from orchestrator.core.router import register_route, deregister_route
from orchestrator.core.scheduler_worker import pick_worker
from orchestrator.config import settings
import structlog

router = APIRouter(prefix="/instances", tags=["instances"])
log = structlog.get_logger()


async def _effective_ttl(db: AsyncSession, challenge: Challenge) -> int:
    """Return TTL in seconds: per-challenge override, then DB setting, then env default."""
    if challenge.ttl_seconds:
        return challenge.ttl_seconds
    return await _get_setting(db, "default_ttl_seconds", settings.default_ttl_seconds)



# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=InstanceResponse, status_code=201,
             dependencies=[Depends(require_api_key)])
async def create_instance(
    body: InstanceCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
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

    challenge = await _get_challenge(db, body.challenge_id)
    worker = await pick_worker(db, challenge.runtime)
    if not worker:
        raise HTTPException(status_code=503, detail="no available worker for this runtime")

    inst = await _create_instance_record(db, body.team_id, challenge, worker)
    background.add_task(_launch_on_worker, inst, challenge, worker)
    log.info("instance created", instance_id=str(inst.id), team=body.team_id)
    return inst


@router.get("/team/{team_id}/{challenge_id}", response_model=InstanceResponse,
            dependencies=[Depends(require_api_key)])
async def get_team_instance(team_id: str, challenge_id: str, db: AsyncSession = Depends(get_db)):
    inst = await _active_instance(db, team_id, challenge_id)
    if not inst:
        raise HTTPException(status_code=404, detail="no active instance")
    return inst


@router.get("/{instance_id}", response_model=InstanceResponse,
            dependencies=[Depends(require_api_key)])
async def get_instance(instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    inst = await _fetch(db, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="not found")
    return inst


@router.delete("/{instance_id}", status_code=204,
               dependencies=[Depends(require_api_key)])
async def stop_instance(
    instance_id: uuid.UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    inst = await _fetch(db, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="not found")
    if inst.status not in (InstanceStatus.pending, InstanceStatus.running):
        raise HTTPException(status_code=409, detail="instance is not active")

    inst.status = InstanceStatus.destroyed
    inst.updated_at = datetime.now(timezone.utc)
    await db.commit()
    background.add_task(_destroy_on_worker, inst)


@router.post("/{instance_id}/restart", response_model=InstanceResponse,
             dependencies=[Depends(require_api_key)])
async def restart_instance(
    instance_id: uuid.UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Stop the current instance and launch a fresh one. TTL resets to full."""
    inst = await _fetch(db, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="not found")
    if inst.status not in (InstanceStatus.pending, InstanceStatus.running):
        raise HTTPException(status_code=409, detail="instance is not active")

    challenge = await _get_challenge(db, inst.challenge_id)
    worker = await pick_worker(db, challenge.runtime)
    if not worker:
        raise HTTPException(status_code=503, detail="no available worker for this runtime")

    # Destroy old instance
    old_inst = inst
    old_inst.status = InstanceStatus.destroyed
    old_inst.updated_at = datetime.now(timezone.utc)
    await db.commit()
    background.add_task(_destroy_on_worker, old_inst)

    # Create fresh instance with full TTL
    new_inst = await _create_instance_record(db, inst.team_id, challenge, worker)
    background.add_task(_launch_on_worker, new_inst, challenge, worker)
    log.info("instance restarted", old=str(old_inst.id), new=str(new_inst.id))
    return new_inst


@router.post("/{instance_id}/renew", response_model=RenewResponse,
             dependencies=[Depends(require_api_key)])
async def renew_instance(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Reset the TTL of a running instance to now + original TTL.
    Capped at max_ttl_seconds from now (global admin setting).
    """
    inst = await _fetch(db, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="not found")
    if inst.status != InstanceStatus.running:
        raise HTTPException(status_code=409, detail="can only renew a running instance")

    challenge = await _get_challenge(db, inst.challenge_id)
    ttl = await _effective_ttl(db, challenge)
    now = datetime.now(timezone.utc)

    # Always reset to now + full TTL
    new_expires = now + timedelta(seconds=ttl)

    if new_expires <= inst.expires_at:
        raise HTTPException(status_code=409,
                            detail="instance is already at the maximum allowed time")

    seconds_added = int((new_expires - inst.expires_at).total_seconds())
    inst.expires_at = new_expires
    inst.updated_at = now
    await db.commit()

    log.info("instance renewed", instance_id=str(inst.id), seconds_added=seconds_added,
             new_expires=new_expires.isoformat())
    return RenewResponse(expires_at=new_expires, seconds_added=seconds_added)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch(db: AsyncSession, instance_id: uuid.UUID) -> Instance | None:
    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    return result.scalar_one_or_none()


async def _active_instance(db: AsyncSession, team_id: str, challenge_id: str) -> Instance | None:
    result = await db.execute(
        select(Instance).where(
            and_(
                Instance.team_id == team_id,
                Instance.challenge_id == challenge_id,
                Instance.status.in_([InstanceStatus.pending, InstanceStatus.running]),
            )
        )
    )
    return result.scalar_one_or_none()


async def _get_challenge(db: AsyncSession, challenge_id: str) -> Challenge:
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=404, detail="challenge not found")
    return challenge


async def _create_instance_record(
    db: AsyncSession, team_id: str, challenge: Challenge, worker: Worker
) -> Instance:
    instance_id = uuid.uuid4()
    flag = derive_flag(team_id, challenge.id, str(instance_id), challenge.flag_salt)
    ttl = await _effective_ttl(db, challenge)
    now = datetime.now(timezone.utc)

    inst = Instance(
        id=instance_id,
        team_id=team_id,
        challenge_id=challenge.id,
        worker_id=worker.id,
        runtime=challenge.runtime,
        status=InstanceStatus.pending,
        flag=flag,
        expires_at=now + timedelta(seconds=ttl),
        started_at=now,
    )
    db.add(inst)
    await db.commit()
    await db.refresh(inst)
    return inst


async def _wait_for_ready(worker: Worker, instance_id: str, timeout: int = 30, interval: float = 0.5) -> None:
    """Poll worker /ready endpoint until container is accepting HTTP or timeout."""
    import asyncio
    import time
    url = f"http://{worker.address}:{worker.agent_port}/ready/{instance_id}"
    deadline = time.monotonic() + timeout
    headers = {"x-api-key": settings.api_key}
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(interval)
    log.warning("readiness check timed out", instance_id=instance_id)


async def _wait_for_http_route(endpoint_host: str, timeout: int = 10, interval: float = 0.5) -> None:
    """
    Wait until Traefik has picked up the dynamic router for this host.
    Avoids short-lived 404s right after status flips to running.
    """
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=False) as client:
                resp = await client.get("http://traefik/", headers={"Host": endpoint_host})
                # 404 means route not propagated yet; any other status means router exists.
                if resp.status_code != 404:
                    return
        except Exception:
            pass
        await asyncio.sleep(interval)
    log.warning("route propagation timed out", endpoint_host=endpoint_host)


async def _launch_on_worker(inst: Instance, challenge: Challenge, worker: Worker):
    from orchestrator.db.session import AsyncSessionLocal
    payload = {
        "instance_id": str(inst.id),
        "challenge_id": challenge.id,
        "runtime": challenge.runtime.value,
        "protocol": challenge.protocol,
        "image": challenge.image,
        "cpu_count": challenge.cpu_count,
        "memory_mb": challenge.memory_mb,
        "port": challenge.port,
        "flag": inst.flag,
        "expose_tcp_port": (
            challenge.protocol == "tcp"
            and settings.base_domain == "localhost"
            and not settings.tls_enabled
        ),
        "extra_config": challenge.extra_config,
    }
    url = f"http://{worker.address}:{worker.agent_port}/launch"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers={"x-api-key": settings.api_key})
            resp.raise_for_status()
            data = resp.json()

        backend_host = data.get("backend_host") or worker.address
        backend_port = int(data.get("backend_port") or data.get("port"))

        # Persist backend target immediately so Traefik can expose a route while
        # the instance is still pending.
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Instance).where(Instance.id == inst.id))
            pending_record = result.scalar_one()
            pending_record.backend_host = backend_host
            pending_record.backend_port = backend_port
            await db.commit()

        endpoint = await register_route(str(inst.id), challenge.id, backend_host, backend_port)
        await _wait_for_ready(worker, str(inst.id))
        if challenge.protocol != "tcp":
            await _wait_for_http_route(endpoint)

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Instance).where(Instance.id == inst.id))
            record = result.scalar_one()
            record.status = InstanceStatus.running
            record.backend_host = backend_host
            record.backend_port = backend_port
            if challenge.protocol == "tcp":
                meta = data.get("metadata") or {}
                public_host = meta.get("public_host")
                public_port = meta.get("public_port")
                if public_host and public_port:
                    record.endpoint = f"tcp://{public_host}:{public_port}"
                else:
                    record.endpoint = f"tcp://{endpoint}:{challenge.port}"
            else:
                record.endpoint = f"https://{endpoint}" if settings.tls_enabled else f"http://{endpoint}"
            await db.commit()
        log.info("instance running", instance_id=str(inst.id), endpoint=endpoint)
    except Exception as e:
        log.error("launch failed", instance_id=str(inst.id), error=str(e))
        from orchestrator.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Instance).where(Instance.id == inst.id))
            record = result.scalar_one_or_none()
            if record:
                record.status = InstanceStatus.error
                await db.commit()


async def _destroy_on_worker(inst: Instance):
    from orchestrator.db.session import AsyncSessionLocal
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
            await client.delete(url, headers={"x-api-key": settings.api_key})
    except Exception as e:
        log.error("destroy worker call failed", instance_id=str(inst.id), error=str(e))
