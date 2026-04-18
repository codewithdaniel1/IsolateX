from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID
from orchestrator.db.models import InstanceStatus, RuntimeType


class InstanceCreate(BaseModel):
    team_id: str
    challenge_id: str


class InstanceResponse(BaseModel):
    id: UUID
    team_id: str
    challenge_id: str
    runtime: RuntimeType
    status: InstanceStatus
    endpoint: Optional[str] = None
    flag: Optional[str] = None
    expires_at: datetime
    started_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WorkerRegister(BaseModel):
    id: str
    address: str
    agent_port: int = 9090
    runtime: RuntimeType
    max_instances: int = 50


class WorkerResponse(BaseModel):
    id: str
    address: str
    runtime: RuntimeType
    max_instances: int
    active: bool
    last_seen: datetime

    class Config:
        from_attributes = True


class ChallengeCreate(BaseModel):
    id: str
    name: str
    runtime: RuntimeType
    image: Optional[str] = None
    cpu_count: float = 1.0
    memory_mb: int = 512
    port: int = 8888
    # Optional TTL override in seconds. If omitted, global default (1800s) is used.
    # Players can renew instances but never past 2 hours from current time.
    ttl_seconds: Optional[int] = None
    flag_salt: str = Field(default_factory=lambda: __import__("secrets").token_hex(16))
    extra_config: Optional[str] = None


class ChallengeResponse(BaseModel):
    id: str
    name: str
    runtime: RuntimeType
    cpu_count: float
    memory_mb: int
    port: int
    ttl_seconds: Optional[int] = None

    class Config:
        from_attributes = True


class ChallengeUpdate(BaseModel):
    name: Optional[str] = None
    cpu_count: Optional[float] = None
    memory_mb: Optional[int] = None
    ttl_seconds: Optional[int] = None
    extra_config: Optional[str] = None


class RenewResponse(BaseModel):
    expires_at: datetime
    seconds_added: int


class TraefikRouteConfig(BaseModel):
    http: dict
