from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


class SetupAutomationTests(unittest.TestCase):
    def test_setup_script_uses_single_runtime_command(self):
        text = read("setup.sh")
        self.assertNotIn("--kctf", text)
        self.assertNotIn("--kata-fc", text)
        self.assertNotIn("--all", text)

    def test_setup_script_supports_external_ctfd_flags(self):
        text = read("setup.sh")
        self.assertIn("--external-ctfd", text)
        self.assertIn("--external-ctfd-path", text)
        self.assertIn("--external-ctfd-container", text)
        self.assertIn("--external-ctfd-url", text)
        self.assertIn("--isolatex-url-for-ctfd", text)

    def test_setup_script_can_run_core_only_stack_for_external_ctfd(self):
        text = read("setup.sh")
        self.assertIn("docker compose up -d postgres redis orchestrator worker-docker", text)
        self.assertIn("integrate_external_ctfd()", text)
        self.assertIn("ISOLATEX_CAP_KCTF_ENABLED", text)
        self.assertIn("ISOLATEX_CAP_KATA_FIRECRACKER_ENABLED", text)

    def test_plugin_supports_file_based_connection_config(self):
        text = read("ctfd-plugin/__init__.py")
        self.assertIn("PLUGIN_ENV_PATH", text)
        self.assertIn("def _plugin_file_settings()", text)
        self.assertIn('_setting("isolatex_url", "ISOLATEX_URL"', text)
        self.assertIn('_setting("isolatex_api_key", "ISOLATEX_API_KEY"', text)
        self.assertIn('@blueprint.route("/admin/runtime-capabilities", methods=["GET"])', text)

    def test_admin_ui_disables_unavailable_runtimes(self):
        text = read("ctfd-plugin/templates/admin.html")
        self.assertIn("runtime-cap-notice", text)
        self.assertIn("loadRuntimeCapabilities()", text)
        self.assertIn("runtimeEnabled(r.value)", text)

    def test_disabled_runtime_reason_includes_enablement_guidance(self):
        setup_text = read("setup.sh")
        plugin_text = read("ctfd-plugin/__init__.py")
        self.assertIn("This cannot be enabled from the IsolateX page.", setup_text)
        self.assertIn("This cannot be enabled from the IsolateX page.", plugin_text)

    def test_generic_import_script_skips_existing_challenge_names(self):
        generic_import = read("scripts/import-challenges.py")
        self.assertIn("already exists in CTFd", generic_import)
        self.assertIn("skip", generic_import)

    def test_docs_and_admin_reference_generic_import_script(self):
        readme = read("README.md")
        setup_doc = read("docs/setup.md")
        admin_template = read("ctfd-plugin/templates/admin.html")
        self.assertIn("scripts/import-challenges.sh", readme)
        self.assertIn("scripts/import-challenges.sh", setup_doc)
        self.assertIn("scripts/import-challenges.sh", admin_template)

    def test_setup_script_does_not_print_api_key_in_manual_fallback(self):
        text = read("setup.sh")
        self.assertNotIn('echo "         ISOLATEX_API_KEY=${api_key}"', text)
        self.assertIn("ISOLATEX_API_KEY=<copy API_KEY from IsolateX .env>", text)

    def test_security_smoke_script_exists(self):
        text = read("scripts/security-smoke.sh")
        self.assertIn("Security smoke summary", text)
        self.assertIn("/traefik/config", text)
        self.assertIn('has("flag")', text)

    def test_bundled_ctfd_image_bakes_isolatex_plugin(self):
        dockerfile = read("ctfd/Dockerfile")
        compose = read("docker-compose.yml")
        self.assertIn("COPY ctfd-plugin /opt/CTFd/CTFd/plugins/isolatex", dockerfile)
        self.assertIn("context: .", compose)
        self.assertIn("dockerfile: ctfd/Dockerfile", compose)


if __name__ == "__main__":
    unittest.main()
