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
    expires_at: datetime
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
    kernel_image: Optional[str] = None
    rootfs_image: Optional[str] = None
    image: Optional[str] = None
    cpu_count: int = 1
    memory_mb: int = 512
    port: int = 8888
    ttl_seconds: int = 3600
    flag_salt: str = Field(default_factory=lambda: __import__("secrets").token_hex(16))
    extra_config: Optional[str] = None


class ChallengeResponse(BaseModel):
    id: str
    name: str
    runtime: RuntimeType
    cpu_count: int
    memory_mb: int
    port: int
    ttl_seconds: int

    class Config:
        from_attributes = True


class TraefikRouteConfig(BaseModel):
    """Schema returned by /traefik/config for Traefik HTTP provider polling."""
    http: dict
