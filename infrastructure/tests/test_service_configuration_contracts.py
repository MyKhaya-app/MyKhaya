"""Stage 1 tests for the future service-specific configuration split."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SECRET_NAMES = {
    "MYKHAYA_SECRET_KEY", "MYKHAYA_POSTGRES_ADMIN_PASSWORD", "MYKHAYA_MIGRATION_DB_PASSWORD",
    "MYKHAYA_DB_PASSWORD", "MYKHAYA_SMTP_PASSWORD", "MYKHAYA_FCM_PRIVATE_KEY",
    "MYKHAYA_VAPID_PRIVATE_KEY", "MYKHAYA_APNS_PRIVATE_KEY", "MYKHAYA_APPLE_PRIVATE_KEY",
    "MYKHAYA_GOOGLE_CLIENT_SECRET", "MYKHAYA_STRIPE_SECRET_KEY", "MYKHAYA_STRIPE_WEBHOOK_SECRET",
    "MYKHAYA_DVLA_UAT_API_KEY", "MYKHAYA_DVLA_PRODUCTION_API_KEY",
    "MYKHAYA_DVSA_CLIENT_SECRET", "MYKHAYA_DVSA_API_KEY", "MYKHAYA_FIELD_ENCRYPTION_KEYS",
    "MYKHAYA_BLIND_INDEX_KEYS", "POSTGRES_PASSWORD",
}
PROVIDER_SECRETS = SECRET_NAMES - {
    "MYKHAYA_SECRET_KEY", "MYKHAYA_POSTGRES_ADMIN_PASSWORD", "MYKHAYA_MIGRATION_DB_PASSWORD",
    "MYKHAYA_DB_PASSWORD", "POSTGRES_PASSWORD",
}


def names(path: Path) -> set[str]:
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]+)=", line.strip())
        if match:
            result.add(match.group(1))
    return result


SERVICES = ("common", "api", "worker", "scheduler", "migrate", "postgres", "test")


def template(environment: str, service: str) -> Path:
    return ROOT / f".env.{environment}.{service}.example"


def environments() -> tuple[str, ...]:
    """DEV templates are required. PROD templates are not published until the
    PROD stage reconciles them with the contract; when present they must be a
    complete set and pass every hygiene check below."""
    return ("dev", "prod") if any(template("prod", s).exists() for s in SERVICES) else ("dev",)


class ServiceConfigurationContractTests(unittest.TestCase):
    def path(self, environment: str, service: str) -> Path:
        return template(environment, service)

    def test_template_trees_are_complete(self):
        for environment in environments():
            missing = [s for s in SERVICES if not self.path(environment, s).is_file()]
            self.assertEqual(missing, [], environment)

    def test_templates_contain_no_realistic_secret_or_private_key_material(self):
        forbidden = ("sk_live_", "sk_test_", "-----BEGIN", "AIza", "client_secret=")
        for path in [
            self.path(environment, service)
            for environment in environments()
            for service in SERVICES
        ]:
            self.assertFalse(any(token in path.read_text(encoding="utf-8") for token in forbidden), path)

    def test_postgres_and_migrations_are_not_provider_secret_consumers(self):
        for environment in environments():
            postgres = names(self.path(environment, "postgres"))
            migrate = names(self.path(environment, "migrate"))
            self.assertIn("POSTGRES_PASSWORD", postgres)
            self.assertIn("MYKHAYA_DATABASE_URL", migrate)
            self.assertFalse(postgres & PROVIDER_SECRETS)
            self.assertFalse(migrate & PROVIDER_SECRETS)
            self.assertFalse(migrate & {"MYKHAYA_POSTGRES_ADMIN_PASSWORD", "MYKHAYA_DB_PASSWORD"})

    def test_common_and_application_contracts_exclude_database_bootstrap_passwords(self):
        forbidden = {"MYKHAYA_POSTGRES_ADMIN_PASSWORD", "MYKHAYA_MIGRATION_DB_PASSWORD", "MYKHAYA_DB_PASSWORD"}
        for environment in environments():
            self.assertFalse(names(self.path(environment, "common")) & SECRET_NAMES)
            self.assertFalse(names(self.path(environment, "api")) & forbidden)

    def test_environment_templates_are_explicitly_namespaced(self):
        for environment in environments():
            other = "prod" if environment == "dev" else "dev"
            for service in SERVICES:
                self.assertIn(f".env.{environment}.", str(self.path(environment, service)))
                self.assertNotIn(f".env.{other}.", str(self.path(environment, service)))

    def test_worker_and_scheduler_do_not_receive_database_bootstrap_passwords(self):
        for environment in environments():
            for service in ("worker", "scheduler"):
                service_names = names(self.path(environment, service))
                self.assertNotIn("MYKHAYA_POSTGRES_ADMIN_PASSWORD", service_names)
                self.assertNotIn("MYKHAYA_MIGRATION_DB_PASSWORD", service_names)
                self.assertNotIn("MYKHAYA_DB_PASSWORD", service_names)

    def test_test_templates_are_synthetic_and_do_not_source_dotenv(self):
        for environment in environments():
            path = self.path(environment, "test")
            text = path.read_text(encoding="utf-8")
            self.assertIn("synthetic", text)
            self.assertNotIn(".env", text)
            self.assertFalse(names(path) & PROVIDER_SECRETS)

    def test_common_build_channel_is_a_value_settings_accepts(self):
        # Settings.build_channel is Literal["development", "stable"]; any other
        # value stops every service, including migrations, at import time.
        if "prod" in environments():
            text = self.path("prod", "common").read_text(encoding="utf-8")
            self.assertIn("MYKHAYA_BUILD_CHANNEL=stable\n", text)
        # DEV (Stage 3A): compose.dev.yml pins the channel, so the service file
        # must not carry a value that would silently have no effect.
        self.assertNotIn("MYKHAYA_BUILD_CHANNEL", names(self.path("dev", "common")))

    def test_stage_one_did_not_change_runtime_compose(self):
        compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        self.assertIn("env_file:", compose)
        self.assertIn(".env", compose)


if __name__ == "__main__":
    unittest.main()
