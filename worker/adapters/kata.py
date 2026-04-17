"""
Kata Containers adapter (via Kubernetes RuntimeClass).

Handles both kata and kata-firecracker runtimes. The only difference between
them is which Kubernetes RuntimeClass is selected:

  runtime="kata"             → RuntimeClass "kata"  (default hypervisor: QEMU / Cloud Hypervisor)
  runtime="kata-firecracker" → RuntimeClass "kata-firecracker"  (Firecracker as Kata backend)

In both cases Kubernetes is the orchestrator and Kata creates a lightweight VM
per pod. The hypervisor is a Kata configuration detail, not an IsolateX detail.

See docs/kata-setup.md for cluster setup.
"""
import asyncio
import structlog
from kubernetes import client as k8s_client, config as k8s_config
from kubernetes.client.rest import ApiException

from worker.adapters.base import RuntimeAdapter, LaunchRequest, LaunchResult
from worker.config import settings

log = structlog.get_logger()

KCTF_NAMESPACE = settings.kctf_namespace

# RuntimeClass names must exist in the cluster before launching instances.
# See docs/kata-setup.md for how to create them.
RUNTIME_CLASS_MAP = {
    "kata":             "kata",
    "kata-firecracker": "kata-firecracker",
}


class KataAdapter(RuntimeAdapter):
    def __init__(self, runtime: str = "kata"):
        self._runtime_class = RUNTIME_CLASS_MAP.get(runtime, "kata")
        self._instances: dict[str, dict] = {}
        self._load_kube_config()

    def _load_kube_config(self):
        try:
            if settings.kubeconfig:
                k8s_config.load_kube_config(config_file=settings.kubeconfig)
            else:
                k8s_config.load_incluster_config()
        except Exception as e:
            log.warning("kube config load warning", error=str(e))

    async def launch(self, req: LaunchRequest) -> LaunchResult:
        if req.instance_id in self._instances:
            return LaunchResult(
                port=self._instances[req.instance_id]["host_port"],
                metadata=self._instances[req.instance_id],
            )

        name = f"isolatex-{req.instance_id[:16]}"
        host_port = _allocate_port(req.instance_id)

        await asyncio.to_thread(self._create_pod, req, name, host_port)
        await asyncio.to_thread(self._create_service, req, name, host_port)

        metadata = {"host_port": host_port, "pod_name": name, "runtime_class": self._runtime_class}
        self._instances[req.instance_id] = metadata
        log.info("kata instance launched", instance_id=req.instance_id,
                 pod=name, runtime_class=self._runtime_class)
        return LaunchResult(port=host_port, metadata=metadata)

    async def destroy(self, instance_id: str) -> None:
        meta = self._instances.pop(instance_id, None)
        name = meta["pod_name"] if meta else f"isolatex-{instance_id[:16]}"
        await asyncio.to_thread(self._delete_pod, name)
        await asyncio.to_thread(self._delete_service, name)
        log.info("kata instance destroyed", instance_id=instance_id, pod=name)

    # ------------------------------------------------------------------
    # Kubernetes operations (sync — called via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _create_pod(self, req: LaunchRequest, name: str, host_port: int):
        v1 = k8s_client.CoreV1Api()
        pod = k8s_client.V1Pod(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                namespace=KCTF_NAMESPACE,
                labels={
                    "app": "isolatex-challenge",
                    "instance-id": req.instance_id[:63],
                    "challenge-id": req.challenge_id[:63],
                },
            ),
            spec=k8s_client.V1PodSpec(
                restart_policy="Never",
                automount_service_account_token=False,
                runtime_class_name=self._runtime_class,
                security_context=k8s_client.V1PodSecurityContext(
                    run_as_non_root=True,
                    run_as_user=65534,
                    seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
                ),
                containers=[
                    k8s_client.V1Container(
                        name="challenge",
                        image=req.image,
                        env=[
                            k8s_client.V1EnvVar(name="ISOLATEX_FLAG", value=req.flag),
                            k8s_client.V1EnvVar(name="ISOLATEX_PORT", value=str(req.port)),
                        ],
                        ports=[k8s_client.V1ContainerPort(container_port=req.port)],
                        resources=k8s_client.V1ResourceRequirements(
                            limits={
                                "cpu": str(req.cpu_count),
                                "memory": f"{req.memory_mb}Mi",
                            },
                            requests={
                                "cpu": "100m",
                                "memory": f"{req.memory_mb // 2}Mi",
                            },
                        ),
                        security_context=k8s_client.V1SecurityContext(
                            allow_privilege_escalation=False,
                            read_only_root_filesystem=True,
                            capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
                        ),
                    )
                ],
            ),
        )
        try:
            v1.create_namespaced_pod(namespace=KCTF_NAMESPACE, body=pod)
        except ApiException as e:
            if e.status != 409:
                raise

    def _create_service(self, req: LaunchRequest, name: str, host_port: int):
        v1 = k8s_client.CoreV1Api()
        svc = k8s_client.V1Service(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=KCTF_NAMESPACE),
            spec=k8s_client.V1ServiceSpec(
                type="NodePort",
                selector={"app": "isolatex-challenge", "instance-id": req.instance_id[:63]},
                ports=[
                    k8s_client.V1ServicePort(
                        port=req.port,
                        target_port=req.port,
                        node_port=host_port,
                    )
                ],
            ),
        )
        try:
            v1.create_namespaced_service(namespace=KCTF_NAMESPACE, body=svc)
        except ApiException as e:
            if e.status != 409:
                raise

    def _delete_pod(self, name: str):
        v1 = k8s_client.CoreV1Api()
        try:
            v1.delete_namespaced_pod(name=name, namespace=KCTF_NAMESPACE)
        except ApiException as e:
            if e.status != 404:
                log.warning("pod delete error", name=name, status=e.status)

    def _delete_service(self, name: str):
        v1 = k8s_client.CoreV1Api()
        try:
            v1.delete_namespaced_service(name=name, namespace=KCTF_NAMESPACE)
        except ApiException as e:
            if e.status != 404:
                log.warning("service delete error", name=name, status=e.status)


def _allocate_port(instance_id: str) -> int:
    span = settings.port_range_end - settings.port_range_start
    return settings.port_range_start + (int(instance_id.replace("-", ""), 16) % span)
