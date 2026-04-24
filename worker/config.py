from pydantic_settings import BaseSettings
from pydantic import Field
import secrets
import os


class WorkerSettings(BaseSettings):
    worker_id: str = Field(default_factory=lambda: secrets.token_hex(8))
    listen_host: str = "0.0.0.0"
    listen_port: int = 9090
    orchestrator_url: str = "http://orchestrator:8080"
    orchestrator_api_key: str = ""
    # Prefer ADVERTISE_ADDRESS; keep WORKER_ADVERTISE_ADDRESS for backward compatibility.
    advertise_address: str = Field(
        default_factory=lambda: (
            os.getenv("ADVERTISE_ADDRESS")
            or os.getenv("WORKER_ADVERTISE_ADDRESS", "")
        )
    )

    # Which runtime this worker handles
    # Each worker process handles exactly ONE runtime type.
    # Run separate worker processes for separate runtimes.
    # Isolation spectrum in docs: docker -> kCTF -> kata -> kata-firecracker
    # Actual runtime strings here: docker | kctf | kata | kata-firecracker
    runtime: str = "docker"

    # kCTF / Kubernetes
    kubeconfig: str = ""
    kctf_namespace: str = "kctf"
    kctf_domain: str = ""

    # Docker
    docker_network: str = "isolatex_challenges"
    docker_network_prefix: str = "isolatex_chal_"
    # Reverse proxy container that should be attached to per-instance networks.
    # If empty, the worker auto-detects a compose service named "traefik".
    docker_gateway_container: str = ""
    docker_label_prefix: str = "isolatex"
    # Kept for compatibility with older configs; secure mode avoids host publishing.
    docker_bind_host: str = "127.0.0.1"

    # Port allocation
    port_range_start: int = 30000
    port_range_end: int = 40000

    # Heartbeat
    heartbeat_interval_seconds: int = 15

    class Config:
        env_file = ".env"


settings = WorkerSettings()
