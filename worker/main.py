"""
IsolateX Worker Agent
=====================
Runs on each compute host. Receives launch/destroy commands from the
orchestrator and dispatches to the configured runtime adapter.

One worker process = one runtime type.
Run multiple workers on the same host if you want multiple runtimes there.

Isolation spectrum in docs:
docker -> kCTF -> kata -> kata-firecracker

Actual worker runtime values in code:
docker | kctf | kata | kata-firecracker
"""
import asyncio
import httpx
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from adapters import get_adapter
from adapters.base import LaunchRequest
from config import settings

log = structlog.get_logger()
adapter = get_adapter(settings.runtime)


class LaunchPayload(BaseModel):
    instance_id: str
    challenge_id: str
    runtime: str
    kernel_image: Optional[str] = None
    rootfs_image: Optional[str] = None
    image: Optional[str] = None
    cpu_count: int = 1
    memory_mb: int = 512
    port: int = 8888
    flag: str
    extra_config: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _register()
    task = asyncio.create_task(_heartbeat_loop())
    yield
    task.cancel()
    await _deregister()


app = FastAPI(title=f"IsolateX Worker ({settings.runtime})", lifespan=lifespan)


@app.post("/launch")
async def launch(payload: LaunchPayload):
    req = LaunchRequest(**payload.model_dump())
    try:
        result = await adapter.launch(req)
        log.info("launched", instance_id=payload.instance_id, port=result.port)
        return {"port": result.port, "metadata": result.metadata}
    except Exception as e:
        log.error("launch failed", instance_id=payload.instance_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/destroy/{instance_id}")
async def destroy(instance_id: str):
    try:
        await adapter.destroy(instance_id)
        log.info("destroyed", instance_id=instance_id)
        return {"status": "ok"}
    except Exception as e:
        log.error("destroy failed", instance_id=instance_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "runtime": settings.runtime, "worker_id": settings.worker_id}


# ---------------------------------------------------------------------------
# Orchestrator registration and heartbeat
# ---------------------------------------------------------------------------

async def _register():
    payload = {
        "id": settings.worker_id,
        "address": _self_address(),
        "agent_port": settings.listen_port,
        "runtime": settings.runtime,
        "max_instances": 50,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.orchestrator_url}/workers",
                json=payload,
                headers={"x-api-key": settings.orchestrator_api_key},
            )
            resp.raise_for_status()
            log.info("registered with orchestrator", worker_id=settings.worker_id)
    except Exception as e:
        log.error("registration failed", error=str(e))


async def _deregister():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.delete(
                f"{settings.orchestrator_url}/workers/{settings.worker_id}",
                headers={"x-api-key": settings.orchestrator_api_key},
            )
    except Exception:
        pass


async def _heartbeat_loop():
    while True:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{settings.orchestrator_url}/workers/{settings.worker_id}/heartbeat",
                    headers={"x-api-key": settings.orchestrator_api_key},
                )
        except Exception as e:
            log.warning("heartbeat failed", error=str(e))
        await asyncio.sleep(settings.heartbeat_interval_seconds)


def _self_address() -> str:
    if settings.advertise_address:
        return settings.advertise_address

    import socket
    return socket.gethostbyname(socket.gethostname())
