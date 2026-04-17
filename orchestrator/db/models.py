from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, Enum as SAEnum, ForeignKey
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
    docker           = "docker"           # weak isolation, fast, cheap
    kctf             = "kctf"             # medium isolation, standard k8s
    kata             = "kata"             # strong isolation, k8s + guest kernel
    firecracker      = "firecracker"      # strongest isolation, direct microVM
    cloud_hypervisor = "cloud_hypervisor" # strong isolation alternative to Firecracker
    # Extend here for future runtimes — see docs/adding-a-runtime.md


class Instance(Base):
    __tablename__ = "instances"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id      = Column(String, nullable=False, index=True)
    challenge_id = Column(String, ForeignKey("challenges.id"), nullable=False)
    worker_id    = Column(String, ForeignKey("workers.id"), nullable=True)
    runtime      = Column(SAEnum(RuntimeType), nullable=False)
    status       = Column(SAEnum(InstanceStatus), nullable=False, default=InstanceStatus.pending)
    endpoint     = Column(String, nullable=True)
    flag         = Column(String, nullable=True)
    expires_at   = Column(DateTime(timezone=True), nullable=False)
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


class Challenge(Base):
    __tablename__ = "challenges"

    id           = Column(String, primary_key=True)
    name         = Column(String, nullable=False)
    runtime      = Column(SAEnum(RuntimeType), nullable=False)
    # microVM fields
    kernel_image = Column(String, nullable=True)
    rootfs_image = Column(String, nullable=True)
    # container fields
    image        = Column(String, nullable=True)
    # resource limits
    cpu_count    = Column(Integer, default=1)
    memory_mb    = Column(Integer, default=512)
    port         = Column(Integer, nullable=False, default=8888)
    ttl_seconds  = Column(Integer, default=3600)
    flag_salt    = Column(String, nullable=False)
    # raw extra config passed through to the runtime adapter
    extra_config = Column(Text, nullable=True)
