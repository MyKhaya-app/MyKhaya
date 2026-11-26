#!/usr/bin/env python3
"""PROD security migration orchestrator (MK-SEC-001 v1.2).

Run through prod-security-migrate.sh. Builds on the F-03 migration
(prod_service_env_migration.py), the shared secret provisioning tool
(dev_secrets_migration.py --environment prod) and prod-deploy.sh, which makes
every container change. The stage is read from the protected state files under
the PROD root, never from the shell.

Nothing here prints, logs or reports a credential, removes a volume,
downgrades a schema or rolls anything back automatically.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import prod_service_env_migration as f03
import service_env_contract as contract

P = f03.P
PROFILE = contract.PROD_SECRETS
SNAPSHOT_NAME = ".secrets-snapshot.json"
# Not recreated by the Docker Secrets stage. PostgreSQL is: its environment
# holds three passwords.
UNCHANGED = ("redis", "web", "caddy")
STABLE_SECONDS = 30
F03_PHRASE = "MIGRATE PROD F-03"
SECRETS_PHRASE = "MIGRATE PROD SECRETS"
SECRETS_ROLLBACK_PHRASE = "ROLL BACK PROD SECRETS"
F03_ROLLBACK_PHRASE = "ROLL BACK PROD TO LEGACY"

# (F-03 state, Docker Secrets state) -> stage. Anything else is contradictory.
STAGES = {
    ("legacy", "legacy"): "legacy",
    ("pending", "legacy"): "f03-pending",
    ("rollback-pending", "legacy"): "f03-rollback-pending",
    ("active", "legacy"): "f03-active",
    ("active", "pending"): "secrets-pending",
    ("active", "active"): "secrets-active",
    ("active", "rollback-pending"): "secrets-rollback-pending",
}
F03_STAGES = ("legacy", "f03-pending", "f03-rollback-pending")
SECRETS_STAGES = ("f03-active", "secrets-pending", "secrets-rollback-pending")
BASE_FILES = ["compose.yml", "compose.production.yml"]
OVERLAYS = {
    "legacy": BASE_FILES,
    "f03-active": [*BASE_FILES, "compose.production.service-env.yml"],
    "secrets-active": [*BASE_FILES, "compose.production.service-env.yml",
                       "compose.production.secrets.yml"],
}
NEXT = {
    "legacy": "check, then apply.",
    "f03-pending": "The F-03 cutover started but is not verified: fix the cause and rerun apply, "
                   "or rollback.",
    "f03-rollback-pending": "The F-03 rollback did not finish: rerun rollback (or apply).",
    "f03-active": "check, then apply (provisions, verifies and migrates to Docker Secrets).",
    "secrets-pending": "The Docker Secrets cutover started but is not verified: fix the cause and "
                       "rerun apply, or rollback.",
    "secrets-active": "Complete. Run accept.",
    "secrets-rollback-pending": "The Docker Secrets rollback is not verified: rerun rollback "
                                "(or apply).",
}


def stage_of(f03_state: str, secrets_state: str) -> str:
    return STAGES.get((f03_state, secrets_state), "inconsistent")


def overlays_of(container: dict) -> list[str]:
    labels = (container.get("Config") or {}).get("Labels") or {}
    files = labels.get("com.docker.compose.project.config_files", "")
    return [Path(p).name for p in files.split(",") if p]


def ask(phrase: str) -> bool:
    print(f"\nType {phrase} to continue: ", end="", flush=True)
    return sys.stdin.readline().rstrip("\r\n") == phrase


@contextlib.contextmanager
def exclusive(root: Path):
    """One orchestrator at a time; released by the kernel if this process dies."""
    import fcntl

    fd = os.open(root / ".migration-lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class SecurityMigration(f03.Migration):
    report_prefix = "security-prod"

    @property
    def stage(self) -> str:
        return stage_of(self.read_state(), self.read_state_file(self.paths.secrets_state))

    @property
    def snapshot_path(self) -> Path:
        return self.paths.root / SNAPSHOT_NAME

    def load_snapshot(self) -> dict | None:
        try:
            return json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def approve_transition(self) -> bool:  # the F-03 stage
        print("\nStage 1, F-03 per-service configuration. Recreated: api, worker, scheduler.\n"
              "Not restarted: postgres, redis, web, caddy. Expect the API to be unavailable for "
              "about a minute.")
        return ask(F03_PHRASE)

    # -- checks ---------------------------------------------------------------

    def check_no_operation_running(self) -> None:
        result = f03.run(["docker", "ps", "-q", "--filter",
                          f"label=com.docker.compose.project={f03.PROJECT}",
                          "--filter", "label=com.docker.compose.service=migrate"])
        if result.returncode != 0 or result.stdout.split():
            self.f.error("stack", "a database migration is running, or Docker could not say")

    def check_overlays(self) -> None:
        """The state file and the running containers must tell the same story."""
        wanted = OVERLAYS.get(self.stage)
        if wanted is None:
            return
        for service in f03.APP_SERVICES:
            for container in self.containers.get(service) or []:
                if overlays_of(container) != wanted:
                    self.f.error("stack", f"{service}: was not created from the configuration the "
                                          "migration state names")

    def check_volumes(self, model: dict) -> None:
        """Data volumes keep their names and stay in use. A label mismatch is
        reported and left alone: volumes are never renamed or re-created."""
        f, phase = self.f, "volumes"
        mark = len(f.items)
        for service in ("postgres", "redis", *f03.APP_SERVICES):
            for container in self.containers.get(service) or []:
                actual = f03.container_mounts(container)
                for target, source in f03.model_mounts(model, service).items():
                    if target.startswith("/data") or service in ("postgres", "redis"):
                        if target != "/docker-entrypoint-initdb.d/10-init.sh" and \
                                actual.get(target) != source:
                            f.error(phase, f"{service}: {target} is not the expected volume")
        for key, definition in (model.get("volumes") or {}).items():
            name = (definition or {}).get("name") or f"{f03.PROJECT}_{key}"
            data = f03.docker_json(["volume", "inspect", name])
            if not isinstance(data, list) or not data:
                f.error(phase, f"volume {name} does not exist; it is never created by this migration")
                continue
            labels = data[0].get("Labels") or {}
            if labels.get("com.docker.compose.project") != f03.PROJECT or \
                    labels.get("com.docker.compose.volume") != key:
                f.warn(phase, f"volume {name} has other Compose labels; it is used by name and "
                              "left exactly as it is")
        if not f.failed_since(mark):
            f.ok(phase, "every persistent volume exists and is the one in use")

    def load_f03(self) -> None:
        """The active F-03 files: valid, matching the running stack, convertible."""
        f, phase, root = self.f, "f03", self.paths.root
        mark = len(f.items)
        self.files = {n: contract.parse_env_file(root / n)[0] for n in f03.SERVICE_FILES
                      if (root / n).is_file()}
        self.probe = contract.docker_key_dir_probe(f"{f03.PROJECT}-api")
        report = contract.validate_root(root, repo_root=self.paths.repo, probe=self.probe,
                                        profile=contract.PROD)
        for warning in report.warnings:
            f.warn(phase, warning)
        for error in report.errors:
            f.error(phase, error)
        model = f03.render_model(self.paths, "service-env", root, self.release, tools=True)
        if model is None:
            f.error(phase, "the F-03 Compose model could not be rendered")
            return
        self.candidate = model
        for error in (contract.check_resolved_model(model, self.paths.repo, contract.PROD)
                      + contract.check_provenance(model, root, contract.PROD)):
            f.error(phase, error)
        if not f.failed_since(mark):
            f.ok(phase, "the F-03 files and merged model satisfy the PROD contract")
        self.check_convertible(self.files)
        self.check_volumes(model)
        for service in UNCHANGED:
            self.check_hash(service, "service-env", root)

    def check_convertible(self, files: dict[str, dict[str, str]]) -> None:
        _, values, problems = contract.derive_file_backed(files, contract.PROD)
        for problem in problems:
            self.f.error("conversion", problem)
        if not problems:
            configured = sum(1 for v in values.values() if v)
            self.f.ok("conversion", f"{configured} credentials can move to files unchanged")

    def check_hash(self, service: str, mode: str, root: Path) -> None:
        running = self.containers.get(service) or []
        label = ((running[0].get("Config") or {}).get("Labels") or {}).get(
            "com.docker.compose.config-hash") if running else None
        if label is None or label != f03.service_hash(self.paths, mode, root, self.release, service):
            self.f.error("stack", f"{service}: would be recreated; it must not be")

    def expected_env_files(self, mode: str) -> str:
        if mode == "secrets":
            return str(self.paths.secrets_root / "compose.env")
        return f"{self.paths.root / 'compose.env'},{self.paths.root / 'postgres.env'}"

    def secrets_readiness(self, *, for_apply: bool) -> None:
        self.tolerate_stopped = self.stage != "f03-active"
        self.check_host(for_apply=for_apply)
        if self.f.errors:
            return
        self.check_release()
        self.check_stack()
        if self.f.errors:
            return
        self.check_no_operation_running()
        self.check_backup(for_apply=for_apply)
        self.check_home_migration()
        self.load_f03()
        if self.stage == "f03-active":
            self.check_overlays()
            self.check_app_services(self.candidate or {}, contract.PROD,
                                    self.expected_env_files("service-env"), self.image_ids())
        if self.paths.secrets_root.exists() and not self.f.errors:
            self.validate_file_backed()

    def image_ids(self) -> dict[str, str]:
        return {s: d.get("Id", "") for s, d in self.images.items()}

    def validate_file_backed(self) -> dict | None:
        """Ownership, modes, grants, provenance and runtime Settings."""
        f, phase, root = self.f, "file-backed", self.paths.secrets_root
        mark = len(f.items)
        if not root.is_dir() or root.is_symlink():
            f.error(phase, "the file-backed configuration is missing; run provision")
            return None
        image = f"{f03.PROJECT}-api"
        report = contract.validate_root(
            root, repo_root=self.paths.repo, probe=contract.docker_key_dir_probe(image),
            profile=PROFILE, postgres_probe=contract.docker_key_dir_probe(
                image, user=f"{contract.POSTGRES_UID}:{contract.POSTGRES_GID}"))
        for error in report.errors:
            f.error(phase, error)
        model = f03.render_model(self.paths, "secrets", root, self.release, tools=True)
        if model is None:
            f.error(phase, "the Docker Secrets Compose model could not be rendered")
            return None
        for error in (contract.check_resolved_model(model, self.paths.repo, PROFILE)
                      + contract.check_provenance(model, root, PROFILE)
                      + contract.check_secret_mounts(model, root, PROFILE)):
            f.error(phase, error)
        for service in UNCHANGED:
            self.check_hash(service, "secrets", root)
        if f.failed_since(mark):
            return None
        _, env = f03.compose_command(self.paths, "secrets", root, self.release)
        env.update({"MYKHAYA_PRODUCTION": "1", "MYKHAYA_PROD_SECRETS": "1",
                    "MYKHAYA_PROD_CONFIG_ROOT": str(self.paths.root)})
        runtime = f03.run(["python3", str(SCRIPTS / "validate_backend_config.py")], env=env,
                          cwd=self.paths.repo, timeout=900)
        if runtime.returncode != 0:
            f.error(phase, "runtime Settings refused the file-backed configuration in throwaway "
                           "probe containers")
            return None
        f.ok(phase, "ownership, modes, per-service grants, provenance and runtime Settings pass; "
                    "redis, web and caddy keep their configuration hash")
        return model

    def as_root(self, action: str) -> bool:
        print(f"==> {action} (sudo)", flush=True)
        result = subprocess.run(
            ["sudo", "python3", "-I", "-B", str(SCRIPTS / "dev_secrets_migration.py"), action,
             "--environment", "prod", "--root", str(self.paths.root),
             "--repo-root", str(self.paths.repo)], cwd=self.paths.repo, check=False)
        return result.returncode == 0

    def check_confirmations(self) -> None:
        f = self.f
        f03.check_config_backup(self)
        try:
            manifest = json.loads((self.paths.config_backups / (
                f"{self.args.confirm_offhost_config_backup}.manifest.json")).read_text("utf-8"))
        except (OSError, ValueError):
            manifest = {}
        # Files generated after the backup equal the backed-up legacy .env, which
        # the F-03 stage proved. Files it does hold must not have changed since.
        recorded = manifest.get("service_files") or {}
        if self.stage == "f03-active" and not recorded and not self.same_run:
            f.error("config-backup", "take a new configuration backup: this one does not hold the "
                                     "F-03 service files")
        for name, metadata in recorded.items():
            if f03.file_metadata(self.paths.root / name) != metadata:
                f.error("config-backup", f"{name} changed after the configuration backup; take a "
                                         "new one")
        self.check_restore_evidence()

    same_run = False

    def check_restore_evidence(self) -> None:
        try:
            tested = dt.date.fromisoformat(self.args.confirm_restore_rehearsal or "")
        except ValueError:
            self.f.error("recovery", "--confirm-restore-rehearsal must be the date (YYYY-MM-DD) a "
                                     "PROD backup was last restored and migrated in isolation")
            return
        if tested > f03.now_utc().date():
            self.f.error("recovery", "the restore rehearsal date is in the future")
        else:
            self.f.ok("recovery", f"Owner states an isolated restore succeeded on {tested}")

    # -- baseline ---------------------------------------------------------------

    def api_tool(self, module: str) -> tuple[int, str]:
        api = (self.containers.get("api") or [{}])[0].get("Id", "")
        result = f03.run(["docker", "exec", api, "python", "-m", module], timeout=300)
        return result.returncode, result.stdout

    def fingerprint(self) -> dict:
        """Non-secret facts the migration must not change. Raises on any
        failure: an unreadable fact must never compare as unchanged."""
        pg = self.postgres_id()
        ok, identity = f03.psql(pg, "select system_identifier from pg_control_system()") \
            if pg else (False, "")
        ok2, revision = f03.psql(pg, "select version_num from alembic_version") \
            if pg else (False, "")
        if not ok or not ok2 or not identity or not revision:
            raise RuntimeError("the database identity could not be read")
        _, text = self.api_tool("mykhaya.tools.encrypted_secrets_check")
        try:
            secrets = json.loads(text)
        except ValueError:
            raise RuntimeError("the encrypted-data check could not run") from None
        code, text = self.api_tool("mykhaya.tools.driveway_ciphertext_check")
        fields: dict[str, int] | str = "no-keyring"
        if code != 2:
            try:
                fields = json.loads(text)
            except ValueError:
                raise RuntimeError("the field-encryption check could not run") from None
        return {
            "database": identity, "alembic": revision,
            # Live users add and remove rows, so failures are what must not grow.
            "encrypted_failures": {k: v for k, v in secrets.items() if k.endswith("_failed")},
            "field_failures": fields if isinstance(fields, str) else {
                k: v for k, v in fields.items() if k.endswith(("_mismatch", "_decrypt_failed"))},
            "volumes": self.project_volumes(),
        }

    def project_volumes(self) -> dict[str, str]:
        """Also volumes whose Compose labels differ: everything mounted."""
        names = {str(m.get("Name")) for found in self.containers.values() for c in found
                 for m in c.get("Mounts") or [] if m.get("Type") == "volume"}
        volumes = super().project_volumes()
        for name in sorted(names - set(volumes)):
            data = f03.docker_json(["volume", "inspect", name])
            if isinstance(data, list) and data:
                volumes[name] = str(data[0].get("CreatedAt", ""))
        return volumes

    def compare(self, snapshot: dict) -> None:
        f, phase = self.f, "baseline"
        mark = len(f.items)
        try:
            now = self.fingerprint()
        except RuntimeError as exc:
            f.error(phase, str(exc))
            return
        before = snapshot["fingerprint"]
        same_release = snapshot.get("commit") == self.release.head
        if now["database"] != before["database"]:
            f.error(phase, "this is not the same PostgreSQL database cluster")
        if same_release and now["alembic"] != before["alembic"]:
            f.error(phase, "the database migration revision changed")
        for name, created in before["volumes"].items():
            if now["volumes"].get(name) != created:
                f.error(phase, f"volume {name} is missing or was re-created")
        for key in ("encrypted_failures", "field_failures"):
            old, new = before[key], now[key]
            if isinstance(old, str) or isinstance(new, str):
                worse = old != new
            else:
                worse = any(count > old.get(name, 0) for name, count in new.items()) \
                    or set(old) - set(new)
            if worse:
                f.error(phase, f"{key.replace('_', ' ')}: stored data that could be read before "
                               "can no longer be read, or the check changed")
        if same_release:
            if self.key_listings() != snapshot.get("keys"):
                f.error(phase, "key directory metadata changed")
            for service in UNCHANGED:
                if (self.containers.get(service) or [{}])[0].get("Id") != \
                        snapshot["containers"].get(service):
                    f.error(phase, f"{service}: the container was recreated or replaced")
        if f03.file_metadata(self.paths.legacy_env) != snapshot.get("legacy_env"):
            # Fatal while migrating; later it must not strand a rollback.
            (f.error if self.stage == "secrets-pending" else f.warn)(
                phase, "the legacy .env changed")
        if not f.failed_since(mark):
            f.ok(phase, "database identity, schema, volumes, keys and encrypted data match the "
                        "baseline")

    def record_snapshot(self) -> dict:
        snapshot = {
            "created_at": f03.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "release": self.release.tag, "commit": self.release.head,
            "legacy_env": f03.file_metadata(self.paths.legacy_env), "keys": self.key_listings(),
            "containers": {s: (self.containers.get(s) or [{}])[0].get("Id", "") for s in UNCHANGED},
            "backup_manifest": self.manifest_name, "fingerprint": self.fingerprint(),
        }
        f03.atomic_write(self.snapshot_path, json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        self.f.ok("baseline", "baseline recorded (metadata and counts only)")
        return snapshot

    # -- verification -------------------------------------------------------------

    def verify_running(self, mode: str, snapshot: dict | None) -> None:
        """Independently verify what is running against one configuration mode."""
        f, phase = self.f, "verify"
        self.containers = f03.project_containers()
        root = self.paths.secrets_root if mode == "secrets" else self.paths.root
        profile = PROFILE if mode == "secrets" else contract.PROD
        model = f03.render_model(self.paths, mode, root, self.release, tools=True)
        if model is None:
            f.error(phase, "the expected Compose model could not be rendered")
            return
        stage = "secrets-active" if mode == "secrets" else "f03-active"
        self.check_app_services(model, profile, self.expected_env_files(mode), self.image_ids())
        for service in (*f03.APP_SERVICES, "postgres"):
            for container in self.containers.get(service) or []:
                if overlays_of(container) != OVERLAYS[stage]:
                    f.error(phase, f"{service}: was not created from the expected configuration")
        self.check_stable()
        self.check_volumes(model)
        for service in UNCHANGED:
            self.check_hash(service, mode, root)
        if mode == "secrets":
            self.check_no_environment_credentials()
        if snapshot is None:  # only a rollback gets this far without one
            f.warn(phase, "no baseline exists; compare database identity and data by hand")
        else:
            self.compare(snapshot)
        health = f03.run(["sh", str(SCRIPTS / "prod-health.sh")], cwd=self.paths.repo)
        if health.returncode != 0:
            f.error(phase, "production health checks failed")
        if not f.errors:
            f.ok(phase, f"the running services match the {profile.label} contract; health checks "
                        "pass")

    def check_stable(self) -> None:
        """Nothing restarts while being watched. An earlier restart is only a
        warning here: replacing PostgreSQL can make a service that is not itself
        being replaced reconnect by restarting, and that must not make a rollback
        or a resume impossible to finish. accept treats it as a failure."""
        f, phase = self.f, "stability"
        mark = len(f.items)

        def starts(found: dict[str, list[dict]]) -> dict[str, list[tuple]]:
            return {s: [(c.get("Id"), c.get("RestartCount", 0), (c.get("State") or {}).get("StartedAt"))
                        for c in found.get(s) or []] for s in (*f03.APP_SERVICES, "postgres")}

        before = starts(self.containers)
        time.sleep(STABLE_SECONDS)
        after = starts(f03.project_containers())
        for service, seen in before.items():
            if after[service] != seen:
                f.error(phase, f"{service}: restarted or was replaced during verification")
            elif any(count for _, count, _ in seen):
                (f.error if self.args.action == "accept" else f.warn)(
                    phase, f"{service}: has restarted since it was created")
        if not f.failed_since(mark):
            f.ok(phase, f"no service restarted in {STABLE_SECONDS} seconds")

    def check_no_environment_credentials(self) -> None:
        f, phase = self.f, "exposure"
        mark = len(f.items)
        literals = contract.ALL_LITERALS | contract.BOOTSTRAP_PASSWORDS
        for service, found in self.containers.items():
            for container in found:
                env = f03.container_env(container)
                for name in sorted(n for n in literals if env.get(n)):
                    f.error(phase, f"{service}: still has {name} in its environment")
                parts = contract._db_parts(env.get(P + "DATABASE_URL", ""))
                if parts and parts[2]:
                    f.error(phase, f"{service}: its database URL still holds a password")
        for container in self.containers.get("postgres") or []:
            env, mounts = f03.container_env(container), f03.container_mounts(container)
            for name, secret in contract.POSTGRES_SECRET_ENV.items():
                if env.get(name) != contract.SECRET_TARGET + secret or \
                        contract.SECRET_TARGET + secret not in mounts:
                    f.error(phase, f"postgres: {name} does not use its secret file")
        if not f.failed_since(mark):
            f.ok(phase, "no container environment holds a credential")


# --- Actions ----------------------------------------------------------------------


def finish(m: SecurityMigration, action: str, success: str) -> int:
    path = m.write_report(action)
    print(f"\nReport: {path}" if path else "")
    if m.f.errors:
        print(f"\nFAILED: {len(m.f.errors)} finding(s). State: {m.stage}.", file=sys.stderr)
        return 1
    print(f"\n{success}")
    return 0


def action_status(m: SecurityMigration) -> int:
    stage = m.stage
    print(f"Stage: {stage}\nF-03 state: {m.read_state()}\n"
          f"Docker Secrets state: {m.read_state_file(m.paths.secrets_state)}")
    for path in (m.paths.state, m.paths.secrets_state):
        if path.is_file() and not path.is_symlink():
            print("\n".join(f"  {path.name}: {line}" for line in
                            path.read_text(encoding="utf-8").splitlines()[1:2]))
    print(f"F-03 files: {sum((m.paths.root / n).is_file() for n in f03.SERVICE_FILES)}"
          f"/{len(f03.SERVICE_FILES)}; file-backed: "
          f"{'present' if m.paths.secrets_root.is_dir() else 'absent'}")
    snapshot = m.load_snapshot()
    if snapshot:
        print(f"Baseline: release {snapshot.get('release')} at {snapshot.get('created_at')}")
    wanted = OVERLAYS.get(stage)
    for service, found in sorted(f03.project_containers().items()):
        for container in found:
            state = container.get("State") or {}
            print(f"  {service}: {state.get('Status', 'unknown')}, restarts "
                  f"{container.get('RestartCount', 0)}, {', '.join(overlays_of(container))}")
            if wanted and service in f03.APP_SERVICES and overlays_of(container) != wanted:
                print("    WARNING: not the configuration the migration state names")
    try:
        reports = sorted(m.paths.reports.glob("*-prod-*.txt"), key=lambda p: p.stat().st_mtime)
    except OSError:
        reports = []
    if reports:
        print(f"Latest report: {reports[-1]}")
    print("Next: " + NEXT.get(stage, "the state files are contradictory or unreadable; inspect "
                                     "them before anything else runs."))
    return 1 if stage == "inconsistent" else 0


def action_check(m: SecurityMigration) -> int:
    stage = m.stage
    if stage == "secrets-active":
        return action_accept(m)
    if stage in F03_STAGES:
        m.tolerate_stopped = stage != "legacy"
        f03.readiness(m, for_apply=False)
        if not m.f.errors:
            m.check_no_operation_running()
            m.check_overlays()
            m.check_convertible(m.files)
    else:
        m.secrets_readiness(for_apply=False)
    return finish(m, "check", f"Automatic checks for the next stage passed (now: {stage}). Nothing "
                              "was changed. apply also needs the Owner's confirmations.")


def action_provision(m: SecurityMigration) -> int:
    if m.stage != "f03-active":
        m.f.error("state", f"provisioning needs F-03 active and Docker Secrets not started "
                           f"(now: {m.stage})")
    else:
        m.check_host(for_apply=False)
        if not m.f.errors:
            m.check_release()
            m.check_stack()
        if not m.f.errors:
            m.load_f03()
        if not m.f.errors and not m.as_root("provision"):
            m.f.error("provision", "nothing was provisioned")
    return finish_verify(m, "provision")


def finish_verify(m: SecurityMigration, action: str) -> int:
    if not m.f.errors and not m.as_root("verify"):
        m.f.error("verify", "the provisioned files do not equal the F-03 values")
    if not m.f.errors:
        m.validate_file_backed()
    return finish(m, action, "The file-backed configuration equals the F-03 values and validates. "
                             "No service was changed.")


def action_verify(m: SecurityMigration) -> int:
    if m.stage not in (*SECRETS_STAGES, "secrets-active"):
        m.f.error("state", f"there is nothing to verify (now: {m.stage})")
    else:
        m.tolerate_stopped = m.stage != "f03-active"
        m.check_host(for_apply=False)
        if not m.f.errors:
            m.check_release()
            m.check_stack()
    return finish_verify(m, "verify")


def deploy(m: SecurityMigration, **flags: str) -> bool:
    env = dict(os.environ)
    env.update({"MYKHAYA_PRODUCTION": "1", "MYKHAYA_RELEASE_TAG": m.release.tag,
                "MYKHAYA_PROD_REUSE_IMAGES": "1", **flags})
    print("\n==> prod-deploy.sh (configuration only; release images reused)", flush=True)
    result = subprocess.run(["sh", str(SCRIPTS / "prod-deploy.sh"), "update"], env=env,
                            cwd=m.paths.repo, stdin=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        m.f.error("deploy", f"prod-deploy.sh stopped (exit {result.returncode}); nothing was rolled "
                            f"back. State: {m.stage}")
    return result.returncode == 0


def action_apply(m: SecurityMigration) -> int:
    stage = m.stage
    if stage == "secrets-active":
        print("Docker Secrets are already active; run accept.")
        return 0
    if stage in F03_STAGES:
        m.check_restore_evidence()
        if m.f.errors:
            return finish(m, "apply-refused", "")
        m.tolerate_stopped = stage != "legacy"
        print("==> Stage 1 of 2: F-03 per-service configuration", flush=True)
        if f03.action_apply(m) != 0:
            return 1
        m = SecurityMigration(m.paths, m.args, f03.Findings())
        m.same_run = True
    print("\n==> Stage 2 of 2: file-backed Docker Secrets", flush=True)
    return apply_secrets(m)


def apply_secrets(m: SecurityMigration) -> int:
    f, start = m.f, m.stage
    if start not in SECRETS_STAGES:
        f.error("state", f"Docker Secrets cannot start from {start}")
        return finish(m, "apply-refused", "")
    m.secrets_readiness(for_apply=True)
    if not f.errors:
        m.check_confirmations()
    if f.errors:
        return finish(m, "apply-refused", "")
    if not m.paths.secrets_root.exists():
        if start != "f03-active":
            f.error("provision", "the file-backed configuration has gone; roll back instead")
        elif not m.as_root("provision"):
            f.error("provision", "nothing was provisioned")
    if not f.errors and not m.as_root("verify"):
        f.error("verify", "the provisioned files do not equal the F-03 values")
    if not f.errors:
        m.validate_file_backed()
    if f.errors:
        return finish(m, "apply-refused", "")
    # While a migration is unfinished the original baseline is kept.
    snapshot = m.load_snapshot() if start != "f03-active" else None
    if start != "f03-active" and snapshot is None:
        f.error("baseline", "the original baseline is missing; roll back instead of resuming")
    elif snapshot is not None and snapshot.get("commit") != m.release.head:
        f.error("baseline", "the unfinished migration used a different release; roll back first")
    if f.errors:
        return finish(m, "apply-refused", "")
    print("\nDocker Secrets. Recreated once, in this order: postgres (same volume, same data, no\n"
          "re-initialisation), then api, worker and scheduler. Not restarted: redis, web, caddy.\n"
          "Expect one to two minutes without the API. Credentials, schema, volumes, networks and\n"
          "images do not change.")
    if not ask(SECRETS_PHRASE):
        print("Not approved. No service was changed.", file=sys.stderr)
        return 1
    if snapshot is None:
        try:
            snapshot = m.record_snapshot()
        except RuntimeError as exc:
            f.error("baseline", str(exc))
            return finish(m, "apply-refused", "")
    if not deploy(m, MYKHAYA_PROD_SECRETS_CUTOVER="1"):
        return finish(m, "apply-interrupted", "")
    m.verify_running("secrets", snapshot)
    if not f.errors and not m.as_root("scan"):
        f.error("exposure", "a credential is visible in Docker metadata, arguments or logs")
    if not f.errors and not m.write_state("active", m.paths.secrets_state):
        f.error("state", "the verified migration could not be recorded as active")
    return finish(m, "apply", "Docker Secrets are active and verified. Now run accept, then the "
                              "manual provider checks (docs/operations/"
                              "prod-docker-secrets-migration.md). Keep .env and the F-03 files.")


def action_accept(m: SecurityMigration) -> int:
    f, stage = m.f, m.stage
    snapshot = m.load_snapshot()
    if stage == "f03-active":
        return f03.action_verify_active(m)
    if stage != "secrets-active":
        f.error("state", f"nothing has completed to accept (now: {stage}); rerun apply or rollback")
    elif snapshot is None:
        f.error("baseline", "the baseline recorded before the cutover is missing")
    else:
        m.check_host(for_apply=False)
        if not f.errors:
            m.check_release()
            m.check_stack()
        if not f.errors:
            m.files = {"compose.env": contract.parse_env_file(
                m.paths.secrets_root / "compose.env")[0]}
            m.probe = contract.docker_key_dir_probe(f"{f03.PROJECT}-api")
            m.verify_running("secrets", snapshot)
        if not f.errors and not m.as_root("scan"):
            f.error("exposure", "a credential is visible in Docker metadata, arguments or logs")
    return finish(m, "accept", "Automatic acceptance passed.")


def rollback_target(stage: str) -> str | None:
    if stage in ("secrets-pending", "secrets-active", "secrets-rollback-pending"):
        return "f03"
    if stage in ("f03-pending", "f03-active", "f03-rollback-pending"):
        return "legacy"
    return None


def assess_rollback(m: SecurityMigration) -> bool:
    """Deliberately needs no running application: a rollback is for when it is broken."""
    f, stage, target = m.f, m.stage, rollback_target(m.stage)
    if target is None:
        f.error("rollback", f"there is nothing to roll back (now: {stage})")
        return False
    print("This can restore the configuration only. It never reverses a database schema change, "
          "restores data or changes a credential. Database recovery is a separate, Owner-approved "
          "restore of a verified backup.")
    m.check_host(for_apply=False)
    if not f.errors:
        m.check_release()
    if f.errors:
        return False
    if target == "legacy":
        return f03.action_rollback_check(m) == 0
    snapshot = m.load_snapshot()
    if snapshot is None:
        f.warn("rollback", "the baseline recorded before the cutover is missing; preservation "
                           "cannot be proved automatically afterwards")
    elif snapshot.get("commit") != m.release.head:
        f.warn("rollback", "a later release is deployed than the one that was migrated; the "
                           "rollback keeps the current release")
    root = m.paths.root
    m.files = {n: contract.parse_env_file(root / n)[0] for n in f03.SERVICE_FILES
               if (root / n).is_file()}
    report = contract.validate_root(root, repo_root=m.paths.repo, profile=contract.PROD,
                                    probe=contract.docker_key_dir_probe(f"{f03.PROJECT}-api"))
    for error in report.errors:
        f.error("rollback", error)
    if f.errors:
        return False
    if not m.as_root("verify"):
        f.warn("rollback", "the file-backed values differ from the F-03 files: rolling back uses "
                           "the F-03 values. Make sure no credential was changed only in the files")
    f.ok("rollback", "the F-03 files are complete and valid; a rollback to F-03 is possible. It "
                     "recreates postgres (same volume), api, worker and scheduler")
    return True


def action_rollback_check(m: SecurityMigration) -> int:
    assess_rollback(m)
    return finish(m, "rollback-check", f"Rollback possible from {m.stage}: run rollback. Nothing "
                                       "was changed.")


def action_rollback(m: SecurityMigration) -> int:
    f, target = m.f, rollback_target(m.stage)
    if not assess_rollback(m):
        return finish(m, "rollback-refused", "")
    if not ask(SECRETS_ROLLBACK_PHRASE if target == "f03" else F03_ROLLBACK_PHRASE):
        print("Not approved. Nothing was changed.", file=sys.stderr)
        return 1
    if target == "legacy":
        if deploy(m, MYKHAYA_PROD_LEGACY_ENV_ROLLBACK="1"):
            m.containers = f03.project_containers()
            if m.stage != "legacy":
                f.error("rollback", f"the rollback did not complete (now: {m.stage})")
            m.check_overlays()
        return finish(m, "rollback", "Rolled back to the legacy configuration.")
    if deploy(m, MYKHAYA_PROD_SECRETS_ROLLBACK="1"):
        m.check_stack()
        m.probe = contract.docker_key_dir_probe(f"{f03.PROJECT}-api")
        m.verify_running("service-env", m.load_snapshot())
        if not f.errors and not m.write_state("legacy", m.paths.secrets_state):
            f.error("state", "the verified rollback could not be recorded")
    return finish(m, "rollback", "Rolled back to the F-03 configuration. The file-backed files were "
                                 "left in place.")


ACTIONS = {
    "status": action_status, "check": action_check, "provision": action_provision,
    "verify": action_verify, "apply": action_apply, "accept": action_accept,
    "rollback-check": action_rollback_check, "rollback": action_rollback,
    "backup-config": f03.action_backup_config,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--expect-host", default="", help="this host's name, confirmed by the Owner")
    parser.add_argument("--accept-dropped", default="")
    parser.add_argument("--accept-unresolved-packages", metavar="N", default=None)
    parser.add_argument("--confirm-offhost-backup", default="", metavar="MANIFEST")
    parser.add_argument("--confirm-offhost-config-backup", default="", metavar="FILE")
    parser.add_argument("--confirm-key-escrow", action="store_true",
                        help="MYKHAYA_SECRET_KEY, the field keyrings, the Apple key and the backup "
                             "identity are recoverable from escrow")
    parser.add_argument("--confirm-restore-rehearsal", default="", metavar="YYYY-MM-DD")
    args = parser.parse_args(argv)
    paths = f03.Paths.from_environment()
    m = SecurityMigration(paths, args, f03.Findings())
    if args.action == "status":
        return action_status(m)
    if not args.expect_host:
        parser.error("--expect-host is required")
    if m.stage == "inconsistent":
        print("ERROR: the two migration state files are contradictory or unreadable; inspect them "
              "(status)", file=sys.stderr)
        return 1
    if not paths.root.is_dir():
        print("ERROR: the PROD configuration root does not exist; create it once: "
              f"sudo install -d -m 0750 -o \"$USER\" -g \"$USER\" {paths.root}", file=sys.stderr)
        return 1
    try:
        with exclusive(paths.root):
            return ACTIONS[args.action](m)
    except BlockingIOError:
        print("ERROR: another migration command is running", file=sys.stderr)
        return 1
    except contract.ProbeFailure as exc:
        print(f"ERROR: key-directory probe: {exc}", file=sys.stderr)
        return 1
    finally:
        m.cleanup_staging()


if __name__ == "__main__":
    raise SystemExit(main())
