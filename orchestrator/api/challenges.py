from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from orchestrator.db.session import get_db
from orchestrator.db.models import Challenge
from orchestrator.api.schemas import ChallengeCreate, ChallengeResponse, ChallengeUpdate
from orchestrator.api.deps import require_api_key

router = APIRouter(prefix="/challenges", tags=["challenges"])


@router.post("", response_model=ChallengeResponse, status_code=201,
             dependencies=[Depends(require_api_key)])
async def create_challenge(body: ChallengeCreate, db: AsyncSession = Depends(get_db)):
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
