"""Security assertions for the standalone F-03 Stage 2 Compose stack.

The Compose model is inspected in memory. The test never prints the resolved
configuration, and it does not read the populated repository .env files.
"""

import json
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.isolated.yml"
PROJECT = "mykhaya-f03-isolated"
# Explicit synthetic interpolation file: stops Compose loading the root .env.
INTERPOLATION = ROOT / "infrastructure" / "tests" / "isolated-compose.env"

BOOTSTRAP = {
    "POSTGRES_PASSWORD",
    "MYKHAYA_POSTGRES_ADMIN_PASSWORD",
    "MYKHAYA_MIGRATION_DB_PASSWORD",
    "MYKHAYA_DB_PASSWORD",
}
PROVIDER_SECRETS = {
    "MYKHAYA_SMTP_PASSWORD",
    "MYKHAYA_FCM_PRIVATE_KEY",
    "MYKHAYA_VAPID_PRIVATE_KEY",
    "MYKHAYA_APNS_PRIVATE_KEY",
    "MYKHAYA_APPLE_PRIVATE_KEY",
    "MYKHAYA_GOOGLE_CLIENT_SECRET",
    "MYKHAYA_STRIPE_SECRET_KEY",
    "MYKHAYA_STRIPE_WEBHOOK_SECRET",
    "MYKHAYA_DVLA_UAT_API_KEY",
    "MYKHAYA_DVLA_PRODUCTION_API_KEY",
    "MYKHAYA_DVSA_CLIENT_SECRET",
    "MYKHAYA_DVSA_API_KEY",
}


def model() -> dict:
    result = subprocess.run(
        [
            "docker", "compose", "-p", PROJECT, "--env-file", str(INTERPOLATION),
            "-f", str(COMPOSE), "--profile", "tests", "config", "--format", "json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class IsolatedServiceConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.services = model()["services"]
        cls.source_services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]

    def env_names(self, service: str) -> set[str]:
        return set(self.services[service].get("environment", {}).keys())

    def test_all_runtime_services_have_explicit_env_files(self):
        expected = {"postgres", "migrate", "api", "worker", "scheduler", "test"}
        for service in expected:
            self.assertTrue(self.source_services[service].get("env_file"), service)

    def test_no_service_references_the_root_dotenv(self):
        for service in self.source_services.values():
            for entry in service.get("env_file", []):
                self.assertNotEqual(Path(entry).name, ".env")

    def test_bootstrap_credentials_are_only_in_postgres(self):
        for name in ("api", "worker", "scheduler", "migrate", "test"):
            self.assertFalse(self.env_names(name) & BOOTSTRAP, name)
        self.assertTrue(self.env_names("postgres") & BOOTSTRAP)

    def test_provider_credentials_are_not_in_migration_test_or_data_services(self):
        for name in ("migrate", "test", "postgres", "redis", "mailpit"):
            self.assertFalse(self.env_names(name) & PROVIDER_SECRETS, name)

    def test_application_services_have_only_their_contract_files(self):
        for name in ("api", "worker", "scheduler", "migrate"):
            files = {Path(path).name for path in self.source_services[name]["env_file"]}
            self.assertNotIn(".env", files)
            self.assertIn("isolated-common.env", files)
            self.assertIn(f"isolated-{name}.env", files)

    def test_no_production_secret_mounts_or_published_ports_exist(self):
        for name, service in self.services.items():
            for mount in service.get("volumes", []):
                rendered = str(mount)
                self.assertNotIn("/run/secrets/mykhaya", rendered)
                self.assertNotIn("/etc/mykhaya/prod", rendered)
            self.assertFalse(service.get("ports"), name)

    def test_services_use_the_dedicated_internal_network(self):
        for name, service in self.services.items():
            networks = service.get("networks", {})
            self.assertIn("f03-data", networks, name)

    def test_network_is_internal_and_project_name_is_explicit(self):
        self.assertTrue(model()["networks"]["f03-data"].get("internal"))
        self.assertEqual(yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["name"], PROJECT)

    def test_interpolation_file_assigns_nothing(self):
        lines = INTERPOLATION.read_text(encoding="utf-8").splitlines()
        self.assertFalse([line for line in lines if line.strip() and not line.startswith("#")])

    def test_worker_and_scheduler_disable_the_api_http_healthcheck(self):
        # Mirrors compose.yml: the image HEALTHCHECK probes the API port, which
        # worker and scheduler never serve, so it would report them unhealthy.
        for name in ("worker", "scheduler"):
            self.assertTrue(self.services[name].get("healthcheck", {}).get("disable"), name)

    def test_isolated_common_values_satisfy_settings_validation_rules(self):
        common = (ROOT / "infrastructure" / "tests" / "isolated-common.env").read_text(encoding="utf-8")
        # Non-localhost development URLs require secure cookies (config.py
        # secure_shared_development_defaults); build_channel is a Literal.
        self.assertIn("MYKHAYA_COOKIE_SECURE=true\n", common)
        self.assertIn("MYKHAYA_ADMIN_MFA_REQUIRED=true\n", common)
        self.assertIn("MYKHAYA_BUILD_CHANNEL=development\n", common)


if __name__ == "__main__":
    unittest.main()
