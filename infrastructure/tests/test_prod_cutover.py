"""End-to-end tests for the one-command PROD migration (F-03).

The real prod-service-env-migrate.sh, prod_service_env_migration.py,
prod-deploy.sh, prod-config-mode.sh, prod-health.sh and backup-preflight.sh
run in a throwaway Git checkout of an approved release tag (cloned from a
local bare `origin`). `docker` is fake_prod_docker.py: Compose's own model,
hashes and environments come from the real CLI, while containers, images,
volumes and PostgreSQL answers are simulated. curl, sleep, age and the two
Python validators that need a real daemon or workspace are stubbed. Every
value is synthetic; nothing touches a real container, volume or host.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import synthetic_prod_config as synthetic

TAG = "v9.9.9"
BUILD_TIME = "2026-11-20T09:00:00Z"
DEPLOYMENT_FILES = (
    "compose.yml", "compose.production.yml", "compose.production.service-env.yml",
    ".env.dev.test.example", ".gitignore", "Makefile", "infrastructure/scripts",
    "infrastructure/caddy", "infrastructure/docker", "apps/api/migrations/versions",
)
HEAD_REVISION = "0999_synthetic_head"
HOME_VOLUME = "mykhaya_prod_home_migration_data"
ENV_FILE_LABEL = "com.docker.compose.project.environment_file"
DESTRUCTIVE = (" down", "volume rm", "prune", "rm -f", " build ", "compose build")

DOCKER_SHIM = '#!/bin/sh\nexec "$REAL_PYTHON" "$FAKE_DOCKER_SCRIPT" "$@"\n'
PYTHON_SHIM = r"""#!/bin/sh
for argument in "$@"; do
  case "$argument" in
    *validate_backend_config.py)
      printf 'validate_backend_config root=%s\n' "${MYKHAYA_PROD_CONFIG_ROOT:-legacy}" >>"$FAKE_LOG"
      exit "${FAKE_VALIDATOR_EXIT:-0}" ;;
    *validate_version.py)
      printf 'validate_version %s\n' "$*" >>"$FAKE_LOG"; exit 0 ;;
  esac
done
exec "$REAL_PYTHON" "$@"
"""
CURL_SHIM = ('#!/bin/sh\n[ "${FAKE_HEALTH_FAIL:-0}" = 1 ] && exit 22\n'
             'case "$*" in *health/build*) printf 401 ;; esac\nexit 0\n')
AGE_SHIM = r"""#!/bin/sh
out=
while [ $# -gt 0 ]; do [ "$1" = -o ] && { out=$2; shift; }; shift; done
{ printf 'age-encryption.org/v1\n'; cat; } > "$out"
"""


def posix_with_tools() -> bool:
    return os.name == "posix" and all(shutil.which(t) for t in ("git", "docker", "sh"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(posix_with_tools(), "POSIX host with git, sh and the Docker CLI required")
class ProdCutoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = Path(tempfile.mkdtemp(prefix="mykhaya-prod-cutover-"))
        source = cls.base / "source"
        source.mkdir()
        for relative in DEPLOYMENT_FILES:
            src, dst = ROOT / relative, source / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, dst)
        # A single synthetic revision keeps the static Alembic check meaningful
        # without copying the application's migration history.
        versions = source / "apps/api/migrations/versions"
        for path in versions.glob("*.py"):
            path.unlink()
        (versions / "0999_synthetic_head.py").write_text(
            f'revision = "{HEAD_REVISION}"\ndown_revision = None\n', encoding="utf-8")
        git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
        subprocess.run([*git, "-C", str(source), "init", "-q", "-b", "main"], check=True)
        subprocess.run([*git, "-C", str(source), "add", "-A"], check=True)
        subprocess.run([*git, "-C", str(source), "commit", "-q", "-m", "release"], check=True)
        subprocess.run([*git, "-C", str(source), "tag", TAG], check=True)
        cls.origin = cls.base / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(source), str(cls.origin)], check=True)
        cls.repo = cls.base / "checkout"
        subprocess.run(["git", "clone", "-q", str(cls.origin), str(cls.repo)], check=True)
        subprocess.run(["git", "-C", str(cls.repo), "checkout", "-q", "--detach", TAG], check=True)
        cls.head = subprocess.run(["git", "-C", str(cls.repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        cls.bin = cls.base / "bin"
        cls.bin.mkdir()
        for name, body in (("docker", DOCKER_SHIM), ("python3", PYTHON_SHIM), ("curl", CURL_SHIM),
                           ("sleep", "#!/bin/sh\nexit 0\n"), ("age", AGE_SHIM)):
            path = cls.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        cls.real_docker = shutil.which("docker")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.base, ignore_errors=True)

    # --- per-test synthetic host ------------------------------------------

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="case-", dir=self.base))
        _, self.root, self.field_keys, self.apple = synthetic.write_layout(self.work)
        os.chmod(self.root, 0o750)
        self.env_file = self.repo / ".env"
        self.env_file.write_text(synthetic.legacy_env(self.field_keys, self.apple),
                                 encoding="utf-8", newline="\n")
        os.chmod(self.env_file, 0o600)
        self.state_file = self.root / ".service-env-state"
        self.backups = self.work / "backups"
        self.backups.mkdir(mode=0o700)
        self.recipients = self.work / "recipients.txt"
        self.recipients.write_text("age1" + "q" * 58 + "\n", encoding="utf-8")
        os.chmod(self.recipients, 0o644)
        self.marker = self.work / "last-backup.ok"
        self.reports = self.work / "reports"
        self.config_backups = self.work / "config-backups"
        self.fake_state = self.work / "docker-state.json"
        self.log = self.work / "docker.log"
        self.write_backup(dt.datetime.now(dt.timezone.utc))
        self.fake_state.write_text(json.dumps(self.initial_state()), encoding="utf-8")
        legacy = self.run_cmd(["docker", "compose", "-f", "compose.yml", "-f",
                               "compose.production.yml", "up", "-d", "--no-build", "caddy",
                               "web", "api", "worker", "scheduler"],
                              extra={"MYKHAYA_VERSION": TAG, "MYKHAYA_COMMIT_SHA": self.head,
                                     "MYKHAYA_BUILD_TIME": BUILD_TIME,
                                     "MYKHAYA_BUILD_CHANNEL": "stable"})
        self.assertEqual(legacy.returncode, 0, legacy.stderr[-1500:])
        state = self.docker_state()
        state["recreated"] = []
        self.fake_state.write_text(json.dumps(state), encoding="utf-8")
        self.legacy_ids = {n: c["Id"] for n, c in state["containers"].items()}
        self.env_sha = sha(self.env_file)
        self.log.write_text("", encoding="utf-8")  # only the test's own calls from here

    def tearDown(self) -> None:
        self.env_file.unlink(missing_ok=True)
        for leftover in self.repo.glob("untracked-*"):
            leftover.unlink()
        shutil.rmtree(self.work, ignore_errors=True)

    def initial_state(self) -> dict:
        app_env = {"PATH": "/opt/venv/bin:/usr/bin", "MYKHAYA_VERSION": TAG,
                   "MYKHAYA_COMMIT_SHA": self.head, "MYKHAYA_BUILD_TIME": BUILD_TIME,
                   "MYKHAYA_BUILD_CHANNEL": "stable"}
        labels = {"org.opencontainers.image.version": TAG,
                  "org.opencontainers.image.revision": self.head,
                  "org.opencontainers.image.created": BUILD_TIME}
        images = {f"mykhaya-{s}": {"Id": f"sha256:release-{s}", "Labels": labels, "Env": app_env}
                  for s in ("api", "worker", "scheduler", "migrate", "web")}
        for name in ("postgres:17.5-alpine3.22", "redis:8.0.3-alpine3.21", "caddy:2.10.0-alpine"):
            images[name] = {"Id": f"sha256:{name}", "Labels": {}, "Env": {}}
        return {"containers": {}, "images": images, "volumes": {}, "alembic": HEAD_REVISION,
                "backup_run": f"true|{self.marker_text}", "in_flight": 0}

    def write_backup(self, when: dt.datetime) -> None:
        self.marker_text = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        database = self.backups / "mykhaya-synthetic.sql.gz.age"
        files = self.backups / "mykhaya-synthetic-files.tar.gz.age"
        for path in (database, files):
            path.write_bytes(b"age-encryption.org/v1\nsynthetic ciphertext\n")
        self.manifest = self.backups / "mykhaya-synthetic.manifest"
        self.manifest.write_text(
            f"created_at={self.marker_text}\nencryption=age\ndatabase={database.name}\n"
            f"database_sha256={sha(database)}\nfiles={files.name}\nfiles_sha256={sha(files)}\n",
            encoding="utf-8")
        self.marker.write_text(self.marker_text + "\n", encoding="utf-8")

    def docker_state(self) -> dict:
        return json.loads(self.fake_state.read_text(encoding="utf-8"))

    def set_docker_state(self, **changes) -> None:
        state = self.docker_state()
        state.update(changes)
        self.fake_state.write_text(json.dumps(state), encoding="utf-8")

    def environment(self, extra: dict | None = None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("MYKHAYA_", "FAKE_", "COMPOSE_", "DOCKER_"))}
        env.update({
            "PATH": f"{self.bin}{os.pathsep}{env.get('PATH', '')}",
            "REAL_DOCKER": self.real_docker, "REAL_PYTHON": sys.executable,
            "FAKE_DOCKER_SCRIPT": str(TESTS / "fake_prod_docker.py"),
            "FAKE_STATE": str(self.fake_state), "FAKE_LOG": str(self.log),
            "FAKE_CUTOVER_STATE_FILE": str(self.state_file),
            "FAKE_DOCKER_ROOT": str(self.work),
            "MYKHAYA_PRODUCTION": "1", "MYKHAYA_RELEASE_TAG": TAG,
            "MYKHAYA_PROD_SERVICE_ENV_STATE": str(self.state_file),
            "MYKHAYA_BACKUP_MARKER": str(self.marker),
            "MYKHAYA_BACKUP_DIR": str(self.backups),
            "MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE": str(self.recipients),
            "MYKHAYA_PROD_MIGRATION_REPORT_DIR": str(self.reports),
            "MYKHAYA_PROD_CONFIG_BACKUP_DIR": str(self.config_backups),
            "MYKHAYA_DEV_SERVICE_ENV_STATE": str(self.work / "no-dev" / ".service-env-state"),
            "MYKHAYA_PROD_MIN_FREE_MB_DOCKER": "1", "MYKHAYA_PROD_MIN_FREE_MB": "1",
        })
        env.update(extra or {})
        return env

    def run_cmd(self, command: list[str], extra: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(command, cwd=self.repo, env=self.environment(extra),
                              capture_output=True, text=True, timeout=600, check=False)

    def migrate(self, *args: str, extra: dict | None = None) -> subprocess.CompletedProcess:
        return self.run_cmd(["sh", "infrastructure/scripts/prod-service-env-migrate.sh", *args],
                            extra)

    def check(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        return self.migrate("--check", "--expect-host", socket.gethostname(), *args, extra=extra)

    def backup_config(self) -> str:
        result = self.migrate("--backup-config", "--expect-host", socket.gethostname())
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
        return next(line.split()[-1] for line in result.stdout.splitlines()
                    if line.startswith("Encrypted configuration backup:")).rsplit("/", 1)[-1]

    def apply(self, *, config_backup: str | None = None, **extra: str) -> subprocess.CompletedProcess:
        config_backup = config_backup or self.backup_config()
        return self.migrate("--apply", "--expect-host", socket.gethostname(),
                            "--confirm-offhost-backup", self.manifest.name,
                            "--confirm-offhost-config-backup", config_backup,
                            "--confirm-key-escrow", extra=extra)

    def cutover_state(self) -> str:
        if not self.state_file.exists():
            return "absent"
        return self.state_file.read_text(encoding="utf-8").splitlines()[0]

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def assertOk(self, result) -> None:
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-3000:])

    def assertRefused(self, result, fragment: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout[-2000:])
        self.assertIn(fragment, result.stdout + result.stderr)

    def assertNothingChanged(self) -> None:
        state = self.docker_state()
        self.assertEqual({n: c["Id"] for n, c in state["containers"].items()}, self.legacy_ids)
        self.assertEqual(state.get("recreated"), [])
        self.assertEqual(self.cutover_state(), "absent")
        self.assertFalse([p for p in self.root.iterdir() if p.name.endswith(".env")])
        self.assertEqual(sha(self.env_file), self.env_sha)

    def assertNoDestruction(self) -> None:
        for call in self.calls():
            command = call.split(" | ")[0]
            for fragment in DESTRUCTIVE:
                self.assertNotIn(fragment, f" {command} ", call)
        self.assertFalse(self.docker_state().get("built"), "images must never be rebuilt")

    def seed_artefacts(self) -> dict:
        """Give every volume synthetic content (the Home Migration volume a
        package), so removal or re-creation of a volume is observable."""
        state = self.docker_state()
        self.assertIn(HOME_VOLUME, state["volumes"])
        for name, volume in state["volumes"].items():
            volume["Artefacts"] = [f"{name}/synthetic-artefact"]
        state["volumes"][HOME_VOLUME]["Artefacts"] = ["packages/synthetic-package.mkhaya"]
        self.fake_state.write_text(json.dumps(state), encoding="utf-8")
        return json.loads(json.dumps(state["volumes"]))

    def assertVolumesPreserved(self, before: dict) -> None:
        self.assertEqual(self.docker_state()["volumes"], before)

    def data_ids(self) -> dict[str, str]:
        containers = self.docker_state()["containers"]
        return {s: containers[s]["Id"] for s in ("postgres", "redis")}

    def assertNoSecrets(self, *texts: str) -> None:
        bodies = list(texts) + [p.read_text(encoding="utf-8") for p in self.reports.glob("*.txt")]
        for body in bodies:
            for secret in synthetic.SECRET_VALUES:
                self.assertNotIn(secret, body)

    # --- check -------------------------------------------------------------

    def test_check_passes_and_changes_nothing(self):
        result = self.check()
        self.assertOk(result)
        self.assertIn("Automated checks passed. Nothing was changed.", result.stdout)
        self.assertNothingChanged()
        self.assertNoDestruction()
        self.assertFalse([p for p in self.root.iterdir() if p.name.startswith(".check-")])
        self.assertTrue(any("validate_backend_config root=" + str(self.root) in c
                            for c in self.calls()))
        self.assertNoSecrets(result.stdout, result.stderr)
        self.assertIn("postgres, redis, web and caddy keep their configuration hash",
                      result.stdout)

    def test_missing_secret_is_refused_without_changes(self):
        text = self.env_file.read_text(encoding="utf-8")
        self.env_file.write_text("".join(l for l in text.splitlines(keepends=True)
                                         if not l.startswith("MYKHAYA_SECRET_KEY=")),
                                 encoding="utf-8")
        self.env_sha = sha(self.env_file)
        result = self.check()
        self.assertRefused(result, "required variable MYKHAYA_SECRET_KEY is missing")
        refused = self.apply()
        self.assertRefused(refused, "REFUSED")
        self.assertNothingChanged()

    def test_wrong_permissions_are_refused(self):
        os.chmod(self.env_file, 0o644)
        self.assertRefused(self.check(), ".env is accessible to other users")
        os.chmod(self.env_file, 0o600)
        os.chmod(self.field_keys / "synthetic-placeholder.txt", 0o644)
        self.assertRefused(self.check(), "is readable by other users")
        os.chmod(self.field_keys / "synthetic-placeholder.txt", 0o600)
        os.chmod(self.root, 0o777)
        self.assertRefused(self.check(), "configuration root mode")
        self.assertNothingChanged()

    def test_missing_stale_or_corrupt_backup_is_refused(self):
        self.marker.unlink()
        self.assertRefused(self.check(), "verified backup marker is missing")
        self.write_backup(dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3))
        self.set_docker_state(backup_run=f"true|{self.marker_text}")
        self.assertRefused(self.check(), "within 2 hours")
        self.write_backup(dt.datetime.now(dt.timezone.utc))
        self.set_docker_state(backup_run=f"true|{self.marker_text}")
        (self.backups / "mykhaya-synthetic.sql.gz.age").write_bytes(b"age-encryption.org/v1\nx\n")
        self.assertRefused(self.check(), "does not match its manifest checksum")
        self.write_backup(dt.datetime.now(dt.timezone.utc))
        self.set_docker_state(backup_run=f"false|{self.marker_text}")
        self.assertRefused(self.check(), "latest recorded backup run is not the successful run")
        self.assertNothingChanged()

    def test_local_backup_alone_is_not_cutover_readiness(self):
        result = self.migrate("--apply", "--expect-host", socket.gethostname())
        self.assertRefused(result, "--confirm-offhost-backup must name this manifest")
        name = self.backup_config()
        result = self.migrate("--apply", "--expect-host", socket.gethostname(),
                              "--confirm-offhost-backup", self.manifest.name,
                              "--confirm-offhost-config-backup", name)
        self.assertRefused(result, "--confirm-key-escrow is required")
        self.assertNothingChanged()

    def test_invalid_release_is_refused(self):
        self.assertRefused(self.check(MYKHAYA_RELEASE_TAG="v9.9.8"),
                           "fetching origin/main and the release tag failed")
        (self.repo / "untracked-file").write_text("x", encoding="utf-8")
        self.assertRefused(self.check(), "uncommitted or untracked changes")
        (self.repo / "untracked-file").unlink()
        state = self.docker_state()
        state["images"]["mykhaya-api"]["Labels"]["org.opencontainers.image.revision"] = "0" * 40
        self.fake_state.write_text(json.dumps(state), encoding="utf-8")
        self.assertRefused(self.check(), "api: image was not built from the release checkout")
        self.assertNothingChanged()

    def test_wrong_host_or_dev_host_is_refused(self):
        result = self.migrate("--check", "--expect-host", "not-this-host.invalid")
        self.assertRefused(result, "does not match --expect-host")
        dev = self.work / "no-dev"
        dev.mkdir()
        self.assertRefused(self.check(), "the DEV configuration exists on this host")
        self.assertNothingChanged()

    def test_in_flight_home_migration_blocks_without_override(self):
        self.set_docker_state(in_flight=1)
        self.assertRefused(self.check(), "Home Migration package(s) are uploaded or importing")
        help_text = self.migrate("--help").stdout
        self.assertNotIn("in-flight", help_text.lower())
        self.assertNotIn("accept-in-flight", help_text)
        self.assertNothingChanged()

    def test_unclassified_and_project_changing_names(self):
        with self.env_file.open("a", encoding="utf-8") as handle:
            handle.write("MYKHAYA_SYNTHETIC_UNKNOWN=1\n")
        self.assertRefused(self.check(), "--accept-dropped MYKHAYA_SYNTHETIC_UNKNOWN")
        self.assertOk(self.check("--accept-dropped", "MYKHAYA_SYNTHETIC_UNKNOWN"))
        with self.env_file.open("a", encoding="utf-8") as handle:
            handle.write("COMPOSE_PROJECT_NAME=other\n")
        result = self.check("--accept-dropped", "MYKHAYA_SYNTHETIC_UNKNOWN,COMPOSE_PROJECT_NAME")
        self.assertRefused(result, "COMPOSE_PROJECT_NAME, which changes the Compose project")

    def test_partial_or_drifted_service_files_are_refused(self):
        (self.root / "api.env").write_text("MYKHAYA_REDIS_URL=redis://redis:6379/0\n")
        self.assertRefused(self.check(), "holds only some service files")
        (self.root / "api.env").unlink()

    # --- legacy behaviour --------------------------------------------------

    def test_legacy_update_is_unchanged_before_cutover(self):
        """With no cutover state, make prod-update behaves exactly as before:
        the historical Compose command, a normal image build, no state file."""
        result = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"])
        self.assertOk(result)
        self.assertIn("Configuration mode: legacy", result.stdout)
        self.assertEqual(self.cutover_state(), "absent")
        commands = [c.split(" | ")[0] for c in self.calls()]
        legacy = "compose -f compose.yml -f compose.production.yml"
        for step in ("build web api worker scheduler migrate", "run --rm --no-deps -T migrate",
                     "up -d --no-build caddy web api worker scheduler"):
            self.assertIn(f"{legacy} {step}", commands)
        self.assertFalse([c for c in commands if "--env-file" in c or "service-env" in c])
        self.assertTrue(self.docker_state().get("built"), "a release update still builds")
        # As before: a release update stamps a new build time, so the services
        # that carry it in their environment are recreated; data services and
        # Caddy are not.
        self.assertEqual(sorted(self.docker_state()["recreated"]), ["api", "scheduler", "web"])
        self.assertEqual(sha(self.env_file), self.env_sha)

    # --- apply -------------------------------------------------------------

    def test_successful_migration_end_to_end(self):
        result = self.apply()
        self.assertOk(result)
        self.assertEqual(self.cutover_state(), "active")
        state = self.docker_state()
        # Only the application tier changed; data, web and proxy containers did not.
        self.assertEqual(sorted(state["recreated"]), ["api", "scheduler", "worker"])
        for service in ("postgres", "redis", "web", "caddy"):
            self.assertEqual(state["containers"][service]["Id"], self.legacy_ids[service], service)
        api, worker = state["containers"]["api"], state["containers"]["worker"]
        for service in ("api", "worker", "scheduler"):
            container = state["containers"][service]
            label = container["Labels"]["com.docker.compose.project.environment_file"]
            self.assertEqual(label, f"{self.root}/compose.env,{self.root}/postgres.env")
            for name in ("MYKHAYA_PRODUCTION", "MYKHAYA_DB_PASSWORD", "MYKHAYA_BACKUP_DIR",
                         "MYKHAYA_POSTGRES_ADMIN_PASSWORD", "WEB_DOMAIN"):
                self.assertNotIn(name, container["Env"], f"{service}.{name}")
        self.assertNotIn("MYKHAYA_STRIPE_SECRET_KEY", worker["Env"])
        self.assertEqual(api["Env"]["MYKHAYA_VERSION"], TAG)
        self.assertEqual(api["Env"]["MYKHAYA_BUILD_TIME"], BUILD_TIME)
        self.assertEqual(sorted(m["Destination"] for m in worker["Mounts"]),
                         ["/data/legal-evidence", "/run/secrets/mykhaya"])
        # Preserved: legacy .env, keys, volumes; no rebuild, no destruction.
        self.assertEqual(sha(self.env_file), self.env_sha)
        self.assertNoDestruction()
        # The wrapper runs with umask 077, so even the non-secret files are 0600.
        modes = {p.name: stat.S_IMODE(p.stat().st_mode) for p in self.root.glob("*.env")}
        self.assertEqual(modes, {name: 0o600 for name in (
            "common.env", "compose.env", "api.env", "worker.env", "scheduler.env",
            "migrate.env", "postgres.env")})
        self.assertEqual(stat.S_IMODE((self.root / ".cutover-snapshot.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state_file.stat().st_mode) & 0o027, 0)
        self.assertNoSecrets(result.stdout, result.stderr,
                             (self.root / ".cutover-snapshot.json").read_text(encoding="utf-8"))
        # The state becomes active only after the migration's own verification.
        pending = [c for c in self.calls() if "(recreated) api" in c]
        self.assertTrue(pending and all("state=pending" in c for c in pending))
        # Normal production commands now use the service files automatically.
        state_cmd = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "state"])
        self.assertIn("Configuration mode: service-env", state_cmd.stdout)
        self.log.write_text("", encoding="utf-8")
        update = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"],
                              {"MYKHAYA_PROD_REUSE_IMAGES": "1"})
        self.assertOk(update)
        self.assertEqual(self.cutover_state(), "active")
        self.assertTrue(any(f"--env-file {self.root}/compose.env" in c for c in self.calls()))
        health = self.run_cmd(["sh", "infrastructure/scripts/prod-health.sh"])
        self.assertOk(health)
        self.assertIn("configuration mode: service-env", health.stdout)

    def test_failed_migration_leaves_pending_and_resumes_safely(self):
        result = self.apply(FAKE_FAIL_ON="run --rm --no-deps -T migrate")
        self.assertRefused(result, "INTERRUPTED")
        self.assertEqual(self.cutover_state(), "pending")
        self.assertEqual(self.docker_state()["recreated"], [])
        # Legacy deployments now fail closed; diagnosis still works.
        legacy = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"])
        self.assertRefused(legacy, "has not been verified")
        status = self.migrate("--status")
        self.assertIn("Cutover state: pending", status.stdout)
        self.assertIn("Rerun the same --apply command", status.stdout)
        self.assertOk(self.run_cmd(["sh", "infrastructure/scripts/prod-health.sh"]))
        # Retry resumes the same cutover and completes it.
        self.assertOk(self.apply())
        self.assertEqual(self.cutover_state(), "active")
        self.assertNoDestruction()

    def test_failed_health_check_leaves_pending_without_rollback(self):
        result = self.apply(FAKE_HEALTH_FAIL="1")
        self.assertRefused(result, "INTERRUPTED")
        self.assertEqual(self.cutover_state(), "pending")
        recreated = self.docker_state()["recreated"]
        self.assertEqual(sorted(recreated), ["api", "scheduler", "worker"])
        self.assertOk(self.apply())
        self.assertEqual(self.cutover_state(), "active")
        # The resumed run did not recreate anything again: the config was already applied.
        self.assertEqual(sorted(self.docker_state()["recreated"]), ["api", "scheduler", "worker"])

    def test_unverified_cutover_is_never_marked_active(self):
        key = self.field_keys / "synthetic-placeholder.txt"
        result = self.apply(FAKE_TOUCH_ON_UP=str(key))
        self.assertRefused(result, "key directory metadata changed during the cutover")
        self.assertEqual(self.cutover_state(), "pending")

    def test_rollback_eligibility_and_explicit_rollback(self):
        self.assertOk(self.apply())
        check = self.migrate("--rollback-check")
        self.assertOk(check)
        self.assertIn("MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1", check.stdout)
        postgres = self.docker_state()["containers"]["postgres"]["Id"]
        rollback = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"],
                                {"MYKHAYA_PROD_LEGACY_ENV_ROLLBACK": "1",
                                 "MYKHAYA_PROD_REUSE_IMAGES": "1"})
        self.assertOk(rollback)
        self.assertEqual(self.cutover_state(), "legacy")
        state = self.docker_state()
        self.assertEqual(state["containers"]["postgres"]["Id"], postgres)
        self.assertIn("MYKHAYA_PRODUCTION", state["containers"]["api"]["Env"])  # legacy .env again
        self.assertEqual(state["containers"]["api"]["Labels"][
            "com.docker.compose.project.environment_file"], "")
        self.assertNoDestruction()
        # A later retry after the rollback completes again.
        self.write_backup(dt.datetime.now(dt.timezone.utc))
        self.set_docker_state(backup_run=f"true|{self.marker_text}")
        self.assertOk(self.apply())
        self.assertEqual(self.cutover_state(), "active")

    def test_rollback_from_pending_after_failed_health_check(self):
        volumes = self.seed_artefacts()
        failed = self.apply(FAKE_HEALTH_FAIL="1")
        self.assertRefused(failed, "INTERRUPTED")
        self.assertEqual(self.cutover_state(), "pending")
        self.assertEqual(sorted(self.docker_state()["recreated"]), ["api", "scheduler", "worker"])
        check = self.migrate("--rollback-check")
        self.assertOk(check)
        self.assertIn("MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1", check.stdout)
        rollback = {"MYKHAYA_PROD_LEGACY_ENV_ROLLBACK": "1", "MYKHAYA_PROD_REUSE_IMAGES": "1"}
        # The fault persists: the rollback stops, nothing is undone, and the
        # unfinished rollback blocks every ordinary deployment.
        stuck = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"],
                             {**rollback, "FAKE_HEALTH_FAIL": "1"})
        self.assertRefused(stuck, "health checks failed; nothing was rolled back")
        self.assertEqual(self.cutover_state(), "rollback-pending")
        ordinary = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"])
        self.assertRefused(ordinary, "rollback to the legacy configuration has not completed")
        self.assertOk(self.run_cmd(["sh", "infrastructure/scripts/prod-health.sh"]))
        # Fixed: the same rollback command completes.
        done = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"], rollback)
        self.assertOk(done)
        self.assertEqual(self.cutover_state(), "legacy")
        state = self.docker_state()
        for service in ("api", "worker", "scheduler"):
            container = state["containers"][service]
            self.assertIn("MYKHAYA_PRODUCTION", container["Env"], service)  # root .env again
            self.assertEqual(container["Labels"][ENV_FILE_LABEL], "", service)
        for service in ("postgres", "redis", "web", "caddy"):
            self.assertEqual(state["containers"][service]["Id"], self.legacy_ids[service], service)
        self.assertVolumesPreserved(volumes)
        self.assertEqual(sha(self.env_file), self.env_sha)
        self.assertNoDestruction()

    def test_updates_after_cutover_preserve_postgres_redis_and_volumes(self):
        volumes = self.seed_artefacts()
        self.assertOk(self.apply())
        data = self.data_ids()
        self.assertEqual(data, {s: self.legacy_ids[s] for s in data})
        # A configuration-only update in active mode recreates nothing.
        self.set_docker_state(recreated=[])
        same = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"],
                            {"MYKHAYA_PROD_REUSE_IMAGES": "1"})
        self.assertOk(same)
        self.assertIn("Configuration mode: service-env", same.stdout)
        self.assertEqual(self.docker_state()["recreated"], [])
        self.assertEqual(self.data_ids(), data)
        # A normal release update (images rebuilt, new build time): as in
        # legacy mode, only the services carrying the build time change.
        update = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"])
        self.assertOk(update)
        self.assertEqual(self.cutover_state(), "active")
        self.assertEqual(sorted(self.docker_state()["recreated"]), ["api", "scheduler", "web"])
        self.assertEqual(self.data_ids(), data)
        self.assertVolumesPreserved(volumes)
        self.assertEqual(sha(self.env_file), self.env_sha)

    def test_application_configuration_drift_is_detected(self):
        self.assertOk(self.apply())
        self.assertOk(self.check())
        api_env = self.root / "api.env"
        text = api_env.read_text(encoding="utf-8")
        api_env.write_text(text.replace("MYKHAYA_SMTP_PORT=587", "MYKHAYA_SMTP_PORT=2525"),
                           encoding="utf-8")
        drifted = self.check()
        self.assertRefused(drifted, "api: MYKHAYA_SMTP_PORT differs from its service file")
        self.assertNoSecrets(drifted.stdout, drifted.stderr)

    def test_postgres_configuration_drift_is_detected_not_prevented(self):
        """Editing postgres.env after cutover is detected by --check. It is not
        prevented: a later update recreates PostgreSQL (its data volume
        survives). This records the limit of the guarantee honestly."""
        volumes = self.seed_artefacts()
        self.assertOk(self.apply())
        data = self.data_ids()
        postgres_env = self.root / "postgres.env"
        text = postgres_env.read_text(encoding="utf-8")
        postgres_env.write_text(text.replace(synthetic.ADMIN_PASSWORD,
                                             "synthetic-prod-postgres-admin-rotated"),
                                encoding="utf-8")
        drifted = self.check()
        self.assertRefused(drifted, "postgres: its running configuration differs from the PROD "
                                    "root; the next update would recreate it")
        self.assertNoSecrets(drifted.stdout, drifted.stderr)
        self.set_docker_state(recreated=[])
        update = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"],
                              {"MYKHAYA_PROD_REUSE_IMAGES": "1"})
        self.assertOk(update)
        self.assertIn("postgres", self.docker_state()["recreated"])
        self.assertNotEqual(self.data_ids()["postgres"], data["postgres"])
        self.assertEqual(self.data_ids()["redis"], data["redis"])
        self.assertVolumesPreserved(volumes)

    # --- post-cutover provenance label --------------------------------------

    def assertLabelRefused(self, label: str, fragment: str) -> None:
        result = self.apply(FAKE_ENV_FILE_LABEL=label)
        self.assertRefused(result, fragment)
        self.assertIn("verification failed", result.stdout + result.stderr)
        self.assertEqual(self.cutover_state(), "pending")
        # Retrying cannot launder it: the containers are not recreated again,
        # so the same evidence is still missing and the state stays pending.
        retry = self.apply()
        self.assertRefused(retry, fragment)
        self.assertEqual(self.cutover_state(), "pending")

    def test_missing_environment_file_label_fails_closed(self):
        self.assertLabelRefused("__absent__", f"has no {ENV_FILE_LABEL} label")

    def assertLabelsRefused(self, cases: dict) -> None:
        # Each case builds its label from a fresh synthetic host's paths.
        for index, (name, build) in enumerate(cases.items()):
            with self.subTest(case=name):
                if index:
                    self.setUp_again()
                self.assertLabelRefused(build(), "was not created from the PROD root's interpolation")

    def test_malformed_environment_file_label_fails_closed(self):
        self.assertLabelsRefused({
            "relative paths": lambda: "compose.env,postgres.env",
            "one file only": lambda: f"{self.root}/compose.env",
            "trailing separator": lambda: f"{self.root}/compose.env,{self.root}/postgres.env,",
        })

    def test_unexpected_environment_file_label_fails_closed(self):
        self.assertLabelsRefused({
            "legacy (empty)": lambda: "",
            "another root": lambda: (f"{self.work}/elsewhere/compose.env,"
                                     f"{self.work}/elsewhere/postgres.env"),
            "reversed order": lambda: f"{self.root}/postgres.env,{self.root}/compose.env",
        })

    def setUp_again(self) -> None:
        """A fresh synthetic host for each sub-case."""
        self.tearDown()
        self.setUp()

    def test_legacy_and_unsafe_commands_fail_closed_after_cutover(self):
        self.assertOk(self.apply())
        install = self.run_cmd(["sh", "infrastructure/scripts/prod-install.sh"])
        self.assertRefused(install, "prod-install is for a new host only")
        guard = self.run_cmd(["sh", "infrastructure/scripts/dev-host-guard.sh", "reset"])
        self.assertRefused(guard, "refused on the PROD host")
        both = self.run_cmd(["sh", "infrastructure/scripts/prod-deploy.sh", "update"],
                            {"MYKHAYA_PROD_LEGACY_ENV_ROLLBACK": "1",
                             "MYKHAYA_PROD_SERVICE_ENV_CUTOVER": "1"})
        self.assertRefused(both, "choose one")
        again = self.apply()
        self.assertOk(again)
        self.assertIn("already active; nothing to do", again.stdout)


if __name__ == "__main__":
    unittest.main()
