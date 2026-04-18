"""
GET  /settings     Return current runtime-configurable orchestrator settings
PATCH /settings    Update settings (admin only, requires API key)
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from orchestrator.db.session import get_db
from orchestrator.db.models import OrchestratorSetting
from orchestrator.api.deps import require_api_key
from orchestrator.config import settings

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    default_ttl_seconds: int


class SettingsUpdate(BaseModel):
    default_ttl_seconds: Optional[int] = None


async def _get_setting(db: AsyncSession, key: str, default: int) -> int:
    result = await db.execute(
        select(OrchestratorSetting).where(OrchestratorSetting.key == key)
    )
    row = result.scalar_one_or_none()
    return int(row.value) if row else default


async def _set_setting(db: AsyncSession, key: str, value: int):
    result = await db.execute(
        select(OrchestratorSetting).where(OrchestratorSetting.key == key)
    )
    row = result.scalar_one_or_none()
    if row:
        row.value = str(value)
    else:
        db.add(OrchestratorSetting(key=key, value=str(value)))
    await db.commit()


@router.get("", response_model=SettingsResponse, dependencies=[Depends(require_api_key)])
async def get_settings(db: AsyncSession = Depends(get_db)):
    return SettingsResponse(
        default_ttl_seconds=await _get_setting(db, "default_ttl_seconds", settings.default_ttl_seconds),
    )


@router.patch("", response_model=SettingsResponse, dependencies=[Depends(require_api_key)])
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    if body.default_ttl_seconds is not None:
        await _set_setting(db, "default_ttl_seconds", body.default_ttl_seconds)
    return await get_settings(db)
