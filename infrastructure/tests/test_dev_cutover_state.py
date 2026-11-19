"""Behavioural tests for the DEV service-env cutover state machine.

The real infrastructure/scripts/dev-deploy.sh runs in a throwaway Git copy of
the deployment files. `docker` is a stub that delegates `compose config` and
`compose version` to the real CLI (no daemon needed) and simulates every
container operation, optionally failing at a chosen step; `curl`, `sleep` and
the runtime validator are stubbed too. Each Docker call records the cutover
state it observed, so tests assert exactly when transitions happen. Every value
is synthetic; nothing touches a real container, volume or host.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "infrastructure" / "scripts"))
import service_env_contract as contract  # noqa: E402
import synthetic_dev_config as synthetic  # noqa: E402

FAKE_DOCKER = r"""#!/bin/sh
state=$(sed -n '1p' "$FAKE_STATE_FILE" 2>/dev/null || true)
printf '%s | state=%s\n' "$*" "${state:-none}" >>"$FAKE_LOG"
case "$*" in
  info*) exit 0 ;;
  "network inspect mykhaya_edge")
    [ -n "${FAKE_NETWORK_DRIFT:-}" ] && exit 1
    echo '[{"Driver":"bridge","Internal":false,"IPAM":{"Config":[{"Subnet":"10.77.0.0/24"}]}}]'; exit 0 ;;
  "network inspect mykhaya_app")
    echo '[{"Driver":"bridge","Internal":true,"IPAM":{"Config":[{"Subnet":"10.77.1.0/24"}]}}]'; exit 0 ;;
  "network inspect mykhaya_data")
    echo '[{"Driver":"bridge","Internal":true,"IPAM":{"Config":[]}}]'; exit 0 ;;
  "compose version"*|*" config "*|*" config") exec "$REAL_DOCKER" "$@" ;;
  port*) exit 1 ;;
  inspect*)
    last=$(eval "printf '%s' \"\${$#}\"")
    if [ -n "${FAKE_UNHEALTHY:-}" ] && [ "$last" = "$FAKE_UNHEALTHY-id" ]; then echo unhealthy; else echo healthy; fi
    exit 0 ;;
esac
if [ -n "${FAKE_FAIL_ON:-}" ]; then
  case "$*" in *"$FAKE_FAIL_ON"*) exit "${FAKE_FAIL_CODE:-1}" ;; esac
fi
case "$*" in
  *" ps "*" -q "*|*" ps -q "*)
    last=$(eval "printf '%s' \"\${$#}\"")
    printf '%s-id\n' "$last" ;;
esac
exit 0
"""

FAKE_PYTHON = r"""#!/bin/sh
case "${1:-}" in
  *validate_backend_config.py)
    state=$(sed -n '1p' "$FAKE_STATE_FILE" 2>/dev/null || true)
    printf 'validate_backend_config | state=%s\n' "${state:-none}" >>"$FAKE_LOG"
    exit "${FAKE_VALIDATOR_EXIT:-0}" ;;
esac
exec "$REAL_PYTHON" "$@"
"""

FAKE_CURL = '#!/bin/sh\n[ "${FAKE_READINESS_FAIL:-0}" = 1 ] && exit 22\nexit 0\n'
FAKE_SLEEP = "#!/bin/sh\nexit 0\n"
DEPLOYMENT_FILES = (
    "compose.yml", "compose.dev.yml", "compose.dev.service-env.yml", "Makefile",
    ".env.dev.example", ".env.dev.test.example", "infrastructure/scripts",
    "infrastructure/caddy", "infrastructure/docker",
)


def posix_with_tools() -> bool:
    return os.name == "posix" and all(shutil.which(t) for t in ("git", "docker", "sh"))


@unittest.skipUnless(posix_with_tools(), "POSIX host with git, sh and the Docker CLI required")
class CutoverStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = Path(tempfile.mkdtemp(prefix="mykhaya-cutover-"))
        cls.repo = cls.base / "repo"
        cls.repo.mkdir()
        for relative in DEPLOYMENT_FILES:
            source = ROOT / relative
            target = cls.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, target)
        git = ["git", "-C", str(cls.repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
        subprocess.run([*git, "init", "-q", "-b", "dev"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "synthetic"], check=True)
        cls.bin = cls.base / "bin"
        cls.bin.mkdir()
        for name, body in (("docker", FAKE_DOCKER), ("python3", FAKE_PYTHON),
                           ("curl", FAKE_CURL), ("sleep", FAKE_SLEEP)):
            path = cls.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        cls.real_docker = shutil.which("docker")
        cls.real_python = sys.executable

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="case-", dir=self.base))
        self.root = synthetic.write_synthetic_root(self.work)
        self.state = self.root / ".service-env-state"
        self.log = self.work / "docker.log"
        # Synthetic legacy root .env built from the same synthetic values.
        legacy: dict[str, str] = {}
        for name in ("compose.env", "common.env", "api.env", "worker.env", "scheduler.env"):
            legacy.update(contract.parse_env_file(self.root / name)[0])
        legacy.pop("MYKHAYA_DATABASE_URL")
        legacy.update({"MYKHAYA_POSTGRES_ADMIN_PASSWORD": synthetic.ADMIN_PASSWORD,
                       "MYKHAYA_MIGRATION_DB_PASSWORD": synthetic.MIGRATION_PASSWORD,
                       "MYKHAYA_DB_PASSWORD": synthetic.RUNTIME_PASSWORD,
                       "MYKHAYA_ADMIN_MFA_REQUIRED": "true"})
        (self.repo / ".env").write_text("".join(f"{k}={v}\n" for k, v in legacy.items()),
                                        encoding="utf-8")

    def tearDown(self) -> None:
        (self.repo / ".env").unlink(missing_ok=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def deploy(self, command: str = "up", *, service_env: bool = True, rollback: bool = False,
               **fake: str) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("MYKHAYA_", "FAKE_", "COMPOSE_"))}
        env.update({
            "PATH": f"{self.bin}{os.pathsep}{env.get('PATH', '')}",
            "REAL_DOCKER": self.real_docker, "REAL_PYTHON": self.real_python,
            "FAKE_LOG": str(self.log), "FAKE_STATE_FILE": str(self.state),
            "MYKHAYA_DEV_SERVICE_ENV_STATE": str(self.state),
        })
        if service_env:
            env["MYKHAYA_DEV_CONFIG_ROOT"] = str(self.root)
        if rollback:
            env["MYKHAYA_DEV_LEGACY_ENV_ROLLBACK"] = "1"
        env.update({f"FAKE_{k.upper()}": v for k, v in fake.items()})
        self.log.write_text("", encoding="utf-8")
        return subprocess.run(["sh", "infrastructure/scripts/dev-deploy.sh", command],
                              cwd=self.repo, env=env, capture_output=True, text=True)

    def state_now(self) -> str:
        return self.state.read_text(encoding="utf-8").splitlines()[0] if self.state.exists() else "absent"

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()

    def first(self, fragment: str) -> str:
        return next(line for line in self.calls() if fragment in line)

    def recreations(self) -> list[str]:
        return [line for line in self.calls()
                if " up -d" in line or " run --rm --no-deps migrate" in line]

    def assertDeployed(self, result) -> None:
        self.assertEqual(result.returncode, 0, result.stdout[-1500:] + result.stderr[-1500:])

    def assertRefused(self, result, fragment: str) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(fragment, result.stderr)

    # --- Successful cutover --------------------------------------------------

    def test_successful_cutover_validates_first_then_pending_then_active(self):
        result = self.deploy()
        self.assertDeployed(result)
        self.assertEqual(self.state_now(), "active")
        self.assertIn("state=none", self.first(" build"))
        self.assertIn("state=none", self.first("validate_backend_config"))
        self.assertIn("state=pending", self.first("up -d --no-build postgres redis"))
        self.assertIn("state=pending", self.first("--force-recreate"))
        mode = stat.S_IMODE(self.state.stat().st_mode)
        self.assertEqual(mode & 0o027, 0, oct(mode))
        self.assertFalse(list(self.root.glob(".service-env-state.tmp.*")))
        self.assertFalse((self.repo / ".service-env-state").exists())

    def test_repeated_service_env_deployments_are_idempotent(self):
        self.assertDeployed(self.deploy())
        self.assertDeployed(self.deploy())
        self.assertEqual(self.state_now(), "active")
        # A routine update never leaves active, even mid-way.
        self.assertIn("state=active", self.first("up -d --no-build postgres redis"))

    def test_failed_update_after_cutover_does_not_downgrade_active(self):
        self.assertDeployed(self.deploy())
        self.assertNotEqual(self.deploy(fail_on="run --rm --no-deps migrate").returncode, 0)
        self.assertEqual(self.state_now(), "active")

    def test_legacy_deployment_is_unchanged_until_deliberate_activation(self):
        result = self.deploy(service_env=False)
        self.assertDeployed(result)
        self.assertIn("Configuration mode: legacy (cutover state: legacy)", result.stdout)
        self.assertFalse(self.state.exists(), "a legacy deployment must never create cutover state")
        compose_calls = [c for c in self.calls()
                         if c.startswith("compose ") and not c.startswith("compose version")]
        self.assertTrue(compose_calls)
        for call in compose_calls:
            self.assertTrue(call.startswith("compose -f compose.yml -f compose.dev.yml "), call)
            self.assertNotIn("service-env", call)
            self.assertNotIn("--env-file", call)

    # --- Failures before any container is recreated ---------------------------

    def test_invalid_configuration_fails_before_state_or_containers_change(self):
        (self.root / "api.env").unlink()
        self.assertRefused(self.deploy(), "DEV service configuration is invalid")
        self.assertEqual(self.state_now(), "absent")
        self.assertEqual(self.recreations(), [])

    def test_failed_runtime_validation_leaves_state_and_containers_untouched(self):
        self.assertRefused(self.deploy(validator_exit="1"), "backend runtime configuration validation failed")
        self.assertEqual(self.state_now(), "absent")
        self.assertEqual(self.recreations(), [])

    def test_network_drift_leaves_state_and_containers_untouched(self):
        self.assertRefused(self.deploy(network_drift="1"), "network drift detected")
        self.assertEqual(self.state_now(), "absent")
        self.assertEqual(self.recreations(), [])

    def test_failed_build_leaves_state_and_containers_untouched(self):
        self.assertRefused(self.deploy(fail_on=" build"), "image build failed")
        self.assertEqual(self.state_now(), "absent")
        self.assertEqual(self.recreations(), [])

    # --- Failures after recreation began: stay pending, legacy blocked ------

    def assert_pending_blocks_legacy_until_resolved(self) -> None:
        self.assertEqual(self.state_now(), "pending")
        refused = self.deploy(service_env=False)
        self.assertRefused(refused, "a service-env cutover was started but has not completed")
        self.assertEqual(self.calls(), [], "legacy refusal must happen before any Docker call")
        self.assertDeployed(self.deploy())
        self.assertEqual(self.state_now(), "active")

    def test_failed_migration_leaves_pending_and_resumes(self):
        self.assertRefused(self.deploy(fail_on="run --rm --no-deps migrate"), "migrations failed")
        self.assert_pending_blocks_legacy_until_resolved()

    def test_partial_service_recreation_leaves_pending_and_resumes(self):
        self.assertRefused(self.deploy(unhealthy="api"), "api became unhealthy")
        self.assert_pending_blocks_legacy_until_resolved()

    def test_failed_readiness_leaves_pending_and_resumes(self):
        self.assertRefused(self.deploy(readiness_fail="1"), "liveness/readiness checks failed")
        self.assert_pending_blocks_legacy_until_resolved()

    def test_interrupted_deployment_leaves_pending_and_resumes(self):
        result = self.deploy(fail_on="up -d --no-build --no-deps web", fail_code="130")
        self.assertNotEqual(result.returncode, 0)
        self.assert_pending_blocks_legacy_until_resolved()

    # --- Explicit rollback ---------------------------------------------------

    def test_active_refuses_implicit_legacy_and_rolls_back_explicitly(self):
        self.assertDeployed(self.deploy())
        self.assertRefused(self.deploy(service_env=False), "the service-specific DEV configuration is active")
        self.assertEqual(self.calls(), [])
        result = self.deploy(service_env=False, rollback=True)
        self.assertDeployed(result)
        self.assertIn("state=active", self.first("validate_backend_config"))
        self.assertIn("state=rollback-pending", self.first("up -d --no-build postgres redis"))
        self.assertEqual(self.state_now(), "legacy")
        # Once rolled back, legacy is the deliberate state and needs no flag.
        self.assertDeployed(self.deploy(service_env=False))
        # Re-cutover is possible from the rolled-back state.
        self.assertDeployed(self.deploy())
        self.assertEqual(self.state_now(), "active")

    def test_failed_rollback_stays_rollback_pending_until_completed(self):
        self.assertDeployed(self.deploy())
        result = self.deploy(service_env=False, rollback=True, fail_on="run --rm --no-deps migrate")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state_now(), "rollback-pending")
        self.assertRefused(self.deploy(service_env=False), "a rollback to the legacy configuration has not completed")
        self.assertDeployed(self.deploy(service_env=False, rollback=True))
        self.assertEqual(self.state_now(), "legacy")

    # --- Fail-closed guards --------------------------------------------------

    def test_ambiguous_mode_is_refused(self):
        self.assertRefused(self.deploy(rollback=True), "choose one")
        self.assertEqual(self.calls(), [])

    def test_unrecognised_or_linked_state_is_refused(self):
        self.state.write_text("bogus\n", encoding="utf-8")
        self.assertRefused(self.deploy(), "is unrecognised")
        self.assertRefused(self.deploy(service_env=False), "is unrecognised")
        self.state.unlink()
        self.state.symlink_to(self.work / "elsewhere")
        self.assertRefused(self.deploy(), "must be a regular file")

    def test_state_must_live_in_the_configuration_root(self):
        result = subprocess.run(
            ["sh", "infrastructure/scripts/dev-deploy.sh", "preflight"], cwd=self.repo,
            capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                 "REAL_DOCKER": self.real_docker, "REAL_PYTHON": self.real_python,
                 "FAKE_LOG": str(self.log), "FAKE_STATE_FILE": str(self.state),
                 "MYKHAYA_DEV_CONFIG_ROOT": str(self.root),
                 "MYKHAYA_DEV_SERVICE_ENV_STATE": str(self.work / "elsewhere.state")})
        self.assertRefused(result, "must be inside MYKHAYA_DEV_CONFIG_ROOT")

    def test_network_migration_requires_a_settled_state(self):
        self.assertRefused(self.deploy(fail_on="run --rm --no-deps migrate"), "migrations failed")
        self.assertRefused(self.deploy("migrate-networks"), "only allowed in a settled state")

    def test_state_init_and_status_never_touch_containers(self):
        init = self.deploy("state-init", service_env=False)
        self.assertDeployed(init)
        self.assertEqual(self.state_now(), "legacy")
        self.assertRefused(self.deploy("state-init", service_env=False), "already exists")
        status = self.deploy("state", service_env=False)
        self.assertIn("Cutover state: legacy", status.stdout)
        self.assertEqual(self.recreations(), [])

    def test_makefile_targets_are_guarded_once_the_state_exists(self):
        guard = ["sh", "infrastructure/scripts/dev-host-guard.sh", "reset"]
        env = {**os.environ, "MYKHAYA_DEV_SERVICE_ENV_STATE": str(self.state)}
        self.assertEqual(subprocess.run(guard, cwd=self.repo, env=env).returncode, 0)
        self.state.write_text("legacy\n", encoding="utf-8")
        refused = subprocess.run(guard, cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("refused on the DEV host", refused.stderr)


if __name__ == "__main__":
    unittest.main()
