from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, Enum as SAEnum, ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func
import enum
import uuid


class Base(DeclarativeBase):
    pass


class InstanceStatus(str, enum.Enum):
    pending   = "pending"
    running   = "running"
    expired   = "expired"
    destroyed = "destroyed"
    error     = "error"


class RuntimeType(str, enum.Enum):
    # Isolation spectrum (weakest → strongest):
    #   docker  →  kctf  →  kata  →  kata-firecracker
    #
    # docker          standard container, weakest isolation
    # kctf            Kubernetes pod + nsjail
    # kata            kCTF + Kata Containers (default hypervisor: QEMU)
    # kata_firecracker kCTF + Kata Containers (Firecracker as Kata hypervisor backend)
    docker           = "docker"
    kctf             = "kctf"
    kata             = "kata"
    kata_firecracker = "kata-firecracker"


class Instance(Base):
    __tablename__ = "instances"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id      = Column(String, nullable=False, index=True)
    challenge_id = Column(String, ForeignKey("challenges.id"), nullable=False)
    worker_id    = Column(String, ForeignKey("workers.id"), nullable=True)
    runtime      = Column(SAEnum(RuntimeType), nullable=False)
    status       = Column(SAEnum(InstanceStatus), nullable=False, default=InstanceStatus.pending)
    endpoint     = Column(String, nullable=True)
    backend_port = Column(Integer, nullable=True)
    flag         = Column(String, nullable=True)
    # TTL fields
    expires_at   = Column(DateTime(timezone=True), nullable=False)
    started_at   = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Worker(Base):
    __tablename__ = "workers"

    id            = Column(String, primary_key=True)
    address       = Column(String, nullable=False)
    agent_port    = Column(Integer, nullable=False, default=9090)
    runtime       = Column(SAEnum(RuntimeType), nullable=False)
    max_instances = Column(Integer, nullable=False, default=50)
    active        = Column(Boolean, default=True)
    last_seen     = Column(DateTime(timezone=True), server_default=func.now())


class OrchestratorSetting(Base):
    """Simple key-value store for runtime-configurable orchestrator settings."""
    __tablename__ = "orchestrator_settings"

    key   = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class Challenge(Base):
    __tablename__ = "challenges"

    id           = Column(String, primary_key=True)
    name         = Column(String, nullable=False)
    runtime      = Column(SAEnum(RuntimeType), nullable=False)
    image        = Column(String, nullable=True)   # container image (docker/kctf/kata)
    cpu_count    = Column(Float, default=1.0)
    memory_mb    = Column(Integer, default=512)
    port         = Column(Integer, nullable=False, default=8888)
    # TTL: None means use global default (settings.default_ttl_seconds = 1800)
    # Per-challenge override in seconds. Max enforced at renew time: 7200 (2 hours).
    ttl_seconds  = Column(Integer, nullable=True)
    flag_salt    = Column(String, nullable=False)
    extra_config = Column(Text, nullable=True)
