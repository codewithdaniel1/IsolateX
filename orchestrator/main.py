import asyncio
from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from orchestrator.db.session import init_db
from orchestrator.core.scheduler import run_reaper
from orchestrator.api import instances, workers, challenges, traefik
from orchestrator.config import settings

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        __import__("logging").getLevelName(settings.log_level)
    )
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("database ready")
    reaper_task = asyncio.create_task(run_reaper())
    log.info("ttl reaper started")
    yield
    reaper_task.cancel()
    try:
        await reaper_task
    except asyncio.CancelledError:
        pass
    log.info("shutdown complete")


app = FastAPI(
    title="IsolateX Orchestrator",
    version="1.0.0",
    description="Per-team challenge isolation platform for CTFd",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(instances.router)
app.include_router(workers.router)
app.include_router(challenges.router)
app.include_router(traefik.router)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health():
    return {"status": "ok"}
