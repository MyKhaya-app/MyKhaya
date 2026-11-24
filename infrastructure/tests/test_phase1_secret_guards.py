"""Static guards for the MK-SEC-001 v1.2 Phase 1 secret-handling architecture.

These pin what must not regress while credentials move from environment
variables to file secrets: no new credential interpolated into Compose, no
password on a command line, the PostgreSQL bootstrap's log and argument
protections, a password-free Alembic configuration, migrations that import no
application code, every file-backed secret documented, and CI running the
disposable-container checks (infrastructure/scripts/check-phase1-secrets.sh).
Application-side guards (registry, role grants) live in apps/api/tests.
"""

import re
import subprocess
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Credential values interpolated into Compose files today (legacy delivery).
# The Docker Secrets cutover removes these; it must never add to them. A
# change here needs MK-SEC-001 review: use a *_FILE variable and a file secret.
LEGACY_COMPOSE_CREDENTIAL_INTERPOLATION = Counter(
    {
        ("compose.yml", "MYKHAYA_DB_PASSWORD"): 4,
        ("compose.yml", "MYKHAYA_MIGRATION_DB_PASSWORD"): 2,
        ("compose.yml", "MYKHAYA_POSTGRES_ADMIN_PASSWORD"): 1,
        ("compose.yml", "MYKHAYA_APNS_PRIVATE_KEY"): 1,
        ("compose.dev.yml", "MYKHAYA_DB_PASSWORD"): 1,
        ("compose.dev.yml", "MYKHAYA_APNS_PRIVATE_KEY"): 1,
        ("compose.production.yml", "MYKHAYA_FCM_PRIVATE_KEY"): 1,
        ("compose.test.yml", "MYKHAYA_DB_PASSWORD"): 2,
        ("compose.test.yml", "MYKHAYA_MIGRATION_DB_PASSWORD"): 2,
        ("compose.test.yml", "MYKHAYA_POSTGRES_ADMIN_PASSWORD"): 1,
    }
)
CREDENTIAL_NAME = r"[A-Z0-9_]*(?:PASSWORD|SECRET|PRIVATE_KEY|API_KEY|_KEYS|TOKEN)(?![A-Z0-9_]*_FILE)"
COMPOSE_INTERPOLATION = re.compile(r"\$\{(" + CREDENTIAL_NAME + r")(?::?[-?+][^}]*)?\}")
# Compose keys whose values become a process's arguments.
COMPOSE_COMMAND_KEY = re.compile(r"^\s*(?:command|entrypoint|test)\s*:|\bCMD(?:-SHELL)?\b")
# A credential expansion handed to a program as an argument: psql variables,
# docker -e NAME=$VALUE, --password, inline PGPASSWORD and the like.
COMMAND_LINE_CREDENTIAL = re.compile(
    r"(?:--set[= ]\s*\w*=?|--variable[= ]\s*\w*=?|-v\s+\w+=|-e\s+\w+=|--env\s+\w+=|"
    r"--password[= ]|PGPASSWORD=|://[^\s:@]*:)\s*[\"']?\$\{?" + CREDENTIAL_NAME
)


def _tracked(*patterns: str) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", *patterns], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise unittest.SkipTest("git metadata is not available")
    return [ROOT / name for name in result.stdout.splitlines()]


def _logical_lines(text: str) -> list[str]:
    """Join backslash continuations so a multi-line command is one line."""
    return re.sub(r"\\\r?\n", " ", text).splitlines()


def command_line_credentials(text: str) -> list[str]:
    return [line.strip() for line in _logical_lines(text) if COMMAND_LINE_CREDENTIAL.search(line)]


class Phase1SecretGuardTests(unittest.TestCase):
    def test_no_new_credential_is_interpolated_into_compose(self) -> None:
        found: Counter[tuple[str, str]] = Counter()
        for path in _tracked("compose*.yml"):
            for match in COMPOSE_INTERPOLATION.finditer(path.read_text(encoding="utf-8")):
                found[(path.name, match.group(1))] += 1
        self.assertEqual(
            dict(found),
            dict(LEGACY_COMPOSE_CREDENTIAL_INTERPOLATION),
            "deliver new credentials as file secrets (*_FILE), not Compose interpolation; "
            "update the allow-list only when a legacy interpolation is removed",
        )

    def test_no_password_is_passed_as_a_command_line_argument(self) -> None:
        offenders = []
        for path in _tracked("*.sh", "Makefile", "*.mk", ".github/workflows/*.yml"):
            for line in command_line_credentials(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(ROOT)}: {line[:120]}")
        # In Compose, only command, entrypoint and healthcheck values become
        # arguments; environment values are covered by the interpolation guard.
        for path in _tracked("compose*.yml"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if COMPOSE_COMMAND_KEY.search(line) and command_line_credentials(line):
                    offenders.append(f"{path.relative_to(ROOT)}: {line.strip()[:120]}")
        self.assertEqual(offenders, [])

    def test_the_command_line_guard_catches_the_old_bootstrap_form(self) -> None:
        old = (
            'psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" \\\n'
            '  --set=migration_password="$MYKHAYA_MIGRATION_DB_PASSWORD" \\\n'
            '  --set=runtime_password="$MYKHAYA_DB_PASSWORD" <<-SQL\n'
        )
        self.assertEqual(len(command_line_credentials(old)), 1)
        for bad in (
            'docker run -e MYKHAYA_DB_PASSWORD="$MYKHAYA_DB_PASSWORD" image',
            "PGPASSWORD=$MYKHAYA_DB_PASSWORD psql -h db",
            'curl "https://user:${MYKHAYA_SMTP_PASSWORD}@example.invalid"',
        ):
            self.assertEqual(len(command_line_credentials(bad)), 1, bad)
        for fine in (
            "docker run -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/db image",
            'psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER"',
        ):
            self.assertEqual(command_line_credentials(fine), [], fine)


class PostgresBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (ROOT / "infrastructure/docker/init-db.sh").read_text(encoding="utf-8")

    def test_passwords_reach_psql_only_through_standard_input(self) -> None:
        self.assertEqual(command_line_credentials(self.script), [])
        self.assertNotRegex(self.script, r"--set=\w*password")
        self.assertIn("\\\\set migration_password", self.script)
        self.assertIn("\\\\set runtime_password", self.script)
        self.assertIn(":'migration_password'", self.script)
        self.assertIn(":'runtime_password'", self.script)

    def test_statement_text_is_never_logged_or_echoed(self) -> None:
        for setting in (
            "SET log_statement = 'none';",
            "SET log_min_error_statement = 'panic';",
            "SET log_min_duration_statement = -1;",
            "SET track_activities = off;",
            "\\set VERBOSITY terse",
            "\\set SHOW_CONTEXT never",
        ):
            self.assertIn(setting, self.script)
        self.assertNotRegex(self.script, r"set -[a-z]*x|--echo|\s-a\s|\s-e\s+psql")

    def test_file_secrets_follow_the_application_reader_rules(self) -> None:
        for rule in (
            "/run/secrets/?*)",
            "is outside the approved secret locations",
            "path contains a symbolic link",
            "is not a regular file",
            "is too large",
            "contains a NUL byte",
            "is not valid UTF-8",
            "must contain a single line",
            "is empty",
            "must not have leading or trailing whitespace",
            "not both",
            "is required",
        ):
            self.assertIn(rule, self.script)

    def test_roles_privileges_and_ownership_are_unchanged(self) -> None:
        for statement in (
            "CREATE ROLE mykhaya_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT",
            "CREATE ROLE mykhaya_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT",
            "ALTER DATABASE mykhaya OWNER TO mykhaya_migrator;",
            "GRANT CONNECT ON DATABASE mykhaya TO mykhaya_app;",
            "GRANT USAGE ON SCHEMA public TO mykhaya_app;",
            "ALTER DEFAULT PRIVILEGES FOR ROLE mykhaya_migrator IN SCHEMA public GRANT SELECT, "
            "INSERT, UPDATE, DELETE ON TABLES TO mykhaya_app;",
            "ALTER DEFAULT PRIVILEGES FOR ROLE mykhaya_migrator IN SCHEMA public GRANT USAGE, "
            "SELECT ON SEQUENCES TO mykhaya_app;",
        ):
            self.assertIn(statement, self.script)


class AlembicConfigurationTests(unittest.TestCase):
    def test_alembic_ini_holds_no_password(self) -> None:
        text = (ROOT / "apps/api/alembic.ini").read_text(encoding="utf-8")
        url = re.search(r"^sqlalchemy\.url\s*=\s*(\S+)", text, re.M)
        assert url is not None
        self.assertNotRegex(url.group(1), r"://[^@/]*:[^@/]*@", "use a password-free placeholder")

    def test_alembic_environment_never_writes_the_url_into_its_configuration(self) -> None:
        env = (ROOT / "apps/api/migrations/env.py").read_text(encoding="utf-8")
        self.assertNotIn("set_main_option", env)
        self.assertNotIn("async_engine_from_config", env)
        self.assertIn("get_migration_settings().database_connect_url()", env)
        self.assertIn("database_url.set(password=None)", env)
        self.assertNotRegex(env, r"get_settings\(|from mykhaya\.db import|import mykhaya\.db\b")

    def test_migration_revisions_import_no_application_code(self) -> None:
        offenders = [
            path.name
            for path in (ROOT / "apps/api/migrations/versions").glob("*.py")
            if re.search(r"^\s*(from|import)\s+mykhaya\b", path.read_text(encoding="utf-8"), re.M)
        ]
        self.assertEqual(offenders, [])


class SecretDocumentationAndCiTests(unittest.TestCase):
    def test_every_file_backed_secret_is_documented(self) -> None:
        registry = (ROOT / "apps/api/mykhaya/secret_registry.py").read_text(encoding="utf-8")
        docs = (ROOT / "docs/operations/service-configuration-contracts.md").read_text(
            encoding="utf-8"
        )
        names = re.findall(r'_spec\("(\w+)", "K-\d\d"', registry)
        self.assertGreaterEqual(len(names), 18)
        for name in names:
            self.assertIn(f"MYKHAYA_{name.upper()}_FILE", docs)
        for name in ("MYKHAYA_DB_PASSWORD_FILE", "MYKHAYA_MIGRATION_DB_PASSWORD_FILE"):
            self.assertIn(name, docs)

    def test_no_settings_class_uses_pydantic_secrets_dir(self) -> None:
        offenders = [
            str(path.relative_to(ROOT))
            for path in (ROOT / "apps/api/mykhaya").rglob("*.py")
            if "secrets_dir" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_ci_runs_the_phase_1_secret_checks(self) -> None:
        quality = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
        self.assertIn("bash infrastructure/scripts/check-phase1-secrets.sh", quality)
        self.assertIn("alembic downgrade base && alembic upgrade head", quality)
        self.assertLess(
            quality.index("docker compose build web api worker scheduler migrate"),
            quality.index("bash infrastructure/scripts/check-phase1-secrets.sh"),
        )
        script = (ROOT / "infrastructure/scripts/check-phase1-secrets.sh").read_text(
            encoding="utf-8"
        )
        for check in (
            "refuses the application key",
            "keyless migrate role",
            "MYKHAYA_DATABASE_PASSWORD_FILE",
            "no password in any psql argument",
            "any process argument",
            "offline SQL renders without credentials",
            "is never re-initialised",
        ):
            self.assertIn(check, script)
        self.assertNotIn("compose down", script)
        self.assertNotRegex(script, r"docker compose\b[^\n]*\b(down|rm|volume)\b")


if __name__ == "__main__":
    unittest.main()
