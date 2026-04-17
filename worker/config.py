from pydantic_settings import BaseSettings
from pydantic import Field
import secrets


class WorkerSettings(BaseSettings):
    worker_id: str = Field(default_factory=lambda: secrets.token_hex(8))
    listen_host: str = "0.0.0.0"
    listen_port: int = 9090
    orchestrator_url: str = "http://orchestrator:8080"
    orchestrator_api_key: str = ""

    # Which runtime this worker handles
    # Each worker process handles exactly ONE runtime type.
    # Run separate worker processes for separate runtimes.
    runtime: str = "docker"  # firecracker | cloud_hypervisor | kctf | docker

    # Firecracker / Cloud Hypervisor
    firecracker_bin: str = "/usr/local/bin/firecracker"
    cloud_hypervisor_bin: str = "/usr/local/bin/cloud-hypervisor"
    jailer_bin: str = "/usr/local/bin/jailer"
    firecracker_run_dir: str = "/run/isolatex/firecracker"
    firecracker_uid: int = 10000
    firecracker_gid: int = 10000
    tap_bridge: str = "isolatex0"

    # kCTF / Kubernetes
    kubeconfig: str = ""
    kctf_namespace: str = "kctf"
    kctf_domain: str = ""

    # Docker
    docker_network: str = "isolatex_challenges"
    docker_label_prefix: str = "isolatex"

    # Port allocation
    port_range_start: int = 30000
    port_range_end: int = 40000

    # Heartbeat
    heartbeat_interval_seconds: int = 15

    class Config:
        env_file = ".env"


settings = WorkerSettings()
