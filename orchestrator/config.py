from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal
import secrets


class Settings(BaseSettings):
    # Server
    listen_host: str = "0.0.0.0"
    listen_port: int = 8080
    debug: bool = False
    log_level: str = "INFO"

    # Security
    secret_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    api_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    ctfd_api_key: str = ""
    ctfd_url: str = "http://ctfd:8000"

    # Database
    database_url: str = "postgresql+asyncpg://isolatex:isolatex@postgres:5432/isolatex"
    redis_url: str = "redis://redis:6379/0"

    # Instance defaults
    default_ttl_seconds: int = 3600
    max_instances_per_team: int = 1
    reap_interval_seconds: int = 30
    worker_heartbeat_timeout_seconds: int = 60

    # Gateway
    gateway_type: Literal["traefik", "nginx"] = "traefik"
    base_domain: str = "ctf.osiris.sh"
    tls_enabled: bool = True

    # Flag derivation
    flag_prefix: str = "flag"
    flag_hmac_secret: str = Field(default_factory=lambda: secrets.token_hex(32))

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
