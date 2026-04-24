from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


class SecurityRegressionTests(unittest.TestCase):
    def test_instance_response_never_exposes_flag(self):
        text = read("orchestrator/api/schemas.py")
        block = re.search(
            r"class InstanceResponse\(BaseModel\):(?P<body>[\s\S]*?)\n\nclass WorkerRegister",
            text,
        )
        self.assertIsNotNone(block, "InstanceResponse class block not found")
        self.assertNotIn("flag:", block.group("body"))

    def test_ctfd_player_instance_routes_require_auth(self):
        text = read("ctfd-plugin/__init__.py")
        expected = [
            (
                '@blueprint.route("/instance/<challenge_id>", methods=["GET"])\n@authed_only\ndef get_instance',
                "GET /instance route must require authenticated user",
            ),
            (
                '@blueprint.route("/instance/<challenge_id>", methods=["POST"])\n@authed_only\ndef launch_instance',
                "POST /instance route must require authenticated user",
            ),
            (
                '@blueprint.route("/instance/<challenge_id>", methods=["DELETE"])\n@authed_only\ndef stop_instance',
                "DELETE /instance route must require authenticated user",
            ),
            (
                '@blueprint.route("/instance/<challenge_id>/restart", methods=["POST"])\n@authed_only\ndef restart_instance',
                "POST /restart route must require authenticated user",
            ),
            (
                '@blueprint.route("/instance/<challenge_id>/renew", methods=["POST"])\n@authed_only\ndef renew_instance',
                "POST /renew route must require authenticated user",
            ),
        ]
        for marker, message in expected:
            self.assertIn(marker, text, message)

        self.assertNotIn("@bypass_csrf_protection", text)

    def test_ctfd_frontend_has_no_csrf_bypass_token(self):
        text = read("ctfd-plugin/assets/isolatex.js")
        self.assertNotIn("Token isolatex-bypass", text)

    def test_ctfd_plugin_sanitizes_instance_payload(self):
        text = read("ctfd-plugin/__init__.py")
        self.assertIn("def _sanitize_instance_payload(payload: dict) -> dict:", text)
        self.assertIn("redacted.pop(\"flag\", None)", text)
        self.assertIn("def _is_admin_user() -> bool:", text)
        self.assertIn("if not is_admin and inst.get(\"team_id\") != tid:", text)

    def test_worker_control_endpoints_require_api_key_dependency(self):
        text = read("worker/main.py")
        self.assertIn('@app.post("/launch", dependencies=[Depends(require_worker_api_key)])', text)
        self.assertIn('@app.get("/ready/{instance_id}", dependencies=[Depends(require_worker_api_key)])', text)
        self.assertIn('@app.delete("/destroy/{instance_id}", dependencies=[Depends(require_worker_api_key)])', text)
        self.assertIn('@app.get("/detect-protocol", dependencies=[Depends(require_worker_api_key)])', text)
        self.assertIn("if resp.status_code == 404:", text)
        self.assertIn("await _register()", text)

    def test_worker_docker_launch_surfaces_runtime_errors(self):
        text = read("worker/adapters/docker.py")
        self.assertIn("await _run(*cmd, capture=True)", text)
        self.assertNotIn("network_name,\n            check=False,", text)

    def test_orchestrator_worker_calls_forward_api_key(self):
        inst = read("orchestrator/api/instances.py")
        chal = read("orchestrator/api/challenges.py")
        sched = read("orchestrator/core/scheduler.py")

        self.assertIn('headers={"x-api-key": settings.api_key}', inst)
        self.assertIn('headers={"x-api-key": settings.api_key}', chal)
        self.assertIn('headers={"x-api-key": settings.api_key}', sched)
        self.assertIn('"expose_tcp_port": (', inst)
        self.assertIn('record.endpoint = f"tcp://{public_host}:{public_port}"', inst)
        self.assertIn("async def _wait_for_http_route(", inst)
        self.assertIn("if challenge.protocol != \"tcp\":", inst)

    def test_traefik_config_endpoint_requires_api_key(self):
        text = read("orchestrator/api/traefik.py")
        self.assertIn('@router.get("/config")', text)
        self.assertIn("if not (settings.base_domain == \"localhost\" and not settings.tls_enabled):", text)
        self.assertIn("await require_api_key(x_api_key=x_api_key)", text)
        self.assertIn("localhost_dev = settings.base_domain == \"localhost\" and not settings.tls_enabled", text)
        self.assertIn("route_middlewares = [] if localhost_dev else [auth_key]", text)
        self.assertIn("if route_middlewares:", text)
        self.assertIn("if middlewares:", text)
        self.assertIn("InstanceStatus.pending", text)

    def test_orchestrator_has_no_wildcard_cors(self):
        text = read("orchestrator/main.py")
        self.assertNotIn("allow_origins=[\"*\"]", text)

    def test_compose_has_no_hardcoded_dev_secrets(self):
        text = read("docker-compose.yml")
        self.assertNotIn("dev-secret-change-in-prod", text)
        self.assertNotIn("dev-api-key-change-in-prod", text)
        self.assertNotIn("dev-flag-secret-change-in-prod", text)

        self.assertIn("SECRET_KEY: ${SECRET_KEY:?SECRET_KEY must be set in .env}", text)
        self.assertIn("API_KEY: ${API_KEY:?API_KEY must be set in .env}", text)
        self.assertIn(
            "FLAG_HMAC_SECRET: ${FLAG_HMAC_SECRET:?FLAG_HMAC_SECRET must be set in .env}",
            text,
        )
        self.assertIn("ISOLATEX_API_KEY: ${API_KEY:?API_KEY must be set in .env}", text)

    def test_worker_port_not_published_to_host(self):
        text = read("docker-compose.yml")
        block = re.search(r"worker-docker:(?P<body>[\s\S]*?)\n\s*# ── CTFd", text)
        self.assertIsNotNone(block, "worker-docker section not found")
        self.assertNotIn("ports:", block.group("body"))

    def test_helper_scripts_do_not_default_to_known_api_key(self):
        for path in (
            "scripts/import-challenges.py",
            "scripts/import-challenges.sh",
            "scripts/build-ctfd-with-fallback.sh",
            "scripts/upload-challenge-files.py",
            "docs/setup.md",
        ):
            self.assertNotIn("dev-api-key-change-in-prod", read(path), path)

    def test_secret_files_are_protected_and_ignored(self):
        setup_text = read("setup.sh")
        gitignore_text = read(".gitignore")
        self.assertIn("chmod 600 .env", setup_text)
        self.assertIn("chmod 600 \"$target_file\"", setup_text)
        self.assertIn("ctfd-plugin/.isolatex.env", gitignore_text)


if __name__ == "__main__":
    unittest.main()
