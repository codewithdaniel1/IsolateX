from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from orchestrator.db.session import get_db
from orchestrator.db.models import Challenge, Worker
from orchestrator.api.schemas import ChallengeCreate, ChallengeResponse, ChallengeUpdate
from orchestrator.api.deps import require_api_key

router = APIRouter(prefix="/challenges", tags=["challenges"])


@router.post("", response_model=ChallengeResponse, status_code=201,
             dependencies=[Depends(require_api_key)])
async def create_challenge(body: ChallengeCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Challenge).where(Challenge.id == body.id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="challenge already exists")
    challenge = Challenge(**body.model_dump())
    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)
    return challenge


@router.get("", response_model=list[ChallengeResponse],
            dependencies=[Depends(require_api_key)])
async def list_challenges(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Challenge))
    return result.scalars().all()


@router.get("/detect-protocol", dependencies=[Depends(require_api_key)])
async def detect_protocol(image: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Ask any available worker to inspect the image and return http or tcp."""
    result = await db.execute(select(Worker).where(Worker.active == True))
    worker = result.scalars().first()
    if not worker:
        return {"protocol": "http", "image": image}
    url = f"http://{worker.address}:{worker.agent_port}/detect-protocol"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params={"image": image})
            return resp.json()
    except Exception:
        return {"protocol": "http", "image": image}


@router.get("/{challenge_id}", response_model=ChallengeResponse,
            dependencies=[Depends(require_api_key)])
async def get_challenge(challenge_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="not found")
    return c


@router.patch("/{challenge_id}", response_model=ChallengeResponse,
              dependencies=[Depends(require_api_key)])
async def update_challenge(challenge_id: str, body: ChallengeUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="not found")
    non_nullable = {"cpu_count", "memory_mb", "port"}
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field in non_nullable:
            continue
        setattr(c, field, value)
    await db.commit()
    await db.refresh(c)
    return c


@router.delete("/{challenge_id}", status_code=204,
               dependencies=[Depends(require_api_key)])
async def delete_challenge(challenge_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="not found")
    await db.delete(c)
    await db.commit()
