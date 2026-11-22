#!/usr/bin/env python3
"""One-command PROD service-specific configuration migration (F-03).

Run through infrastructure/scripts/prod-service-env-migrate.sh on the
production host, from the approved release checkout, as the deployment
account. See docs/operations/prod-service-config-migration.md.

    --check          read-only readiness check; changes no container, volume,
                     credential or configuration file (it writes a report)
    --backup-config  age-encrypted backup of the deployment configuration
    --apply          the cutover; refuses on any unresolved finding
    --status         state, snapshot and latest report
    --rollback-check whether a deliberate rollback is possible, and how

Nothing here prints, logs or reports a credential: values are compared in
memory and only variable names, file names and metadata are reported. Key
material is never opened (metadata only, through the locked-down probe).
Nothing here removes a volume, downgrades a migration or rolls anything back.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import io
import json
import os
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import service_env_contract as contract

P = "MYKHAYA_"
PROFILE = contract.PROD
PROJECT = "mykhaya"
APP_SERVICES = ("api", "worker", "scheduler")
# Services whose container must not change: their resolved configuration is
# identical in both modes, so Compose does not recreate them.
UNCHANGED_SERVICES = ("postgres", "redis", "web", "caddy")
IMAGE_SERVICES = ("api", "worker", "scheduler", "migrate", "web")
MAX_BACKUP_AGE = dt.timedelta(hours=2)
IN_FLIGHT_STATUSES = ("uploaded", "importing")
MIN_COMPOSE = (2, 24, 4)
SNAPSHOT_NAME = ".cutover-snapshot.json"
SERVICE_FILES = tuple(c.name for c in PROFILE.contracts)
DEFAULT_MIN_FREE_MB = {"docker": 4096, "other": 256}
SAFE_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def run(args: list[str], *, env: dict[str, str] | None = None, input_bytes: bytes | None = None,
        timeout: float = 600, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a command, capturing output. Output is parsed, never echoed."""
    try:
        if input_bytes is not None:
            return subprocess.run(args, input=input_bytes, capture_output=True, check=False,
                                  timeout=timeout, env=env, cwd=cwd)
        return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout,
                              env=env, cwd=cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, 127, "", f"{type(exc).__name__}")


# --- Paths and findings -------------------------------------------------------


@dataclass(frozen=True)
class Paths:
    repo: Path
    state: Path
    marker: Path
    reports: Path
    config_backups: Path
    dev_state: Path

    @property
    def root(self) -> Path:
        return self.state.parent

    @property
    def legacy_env(self) -> Path:
        return self.repo / ".env"

    @property
    def snapshot(self) -> Path:
        return self.root / SNAPSHOT_NAME

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> Paths:
        environ = dict(os.environ if environ is None else environ)
        return cls(
            repo=SCRIPTS.parents[1],
            state=Path(environ.get("MYKHAYA_PROD_SERVICE_ENV_STATE")
                       or "/etc/mykhaya/prod/.service-env-state"),
            marker=Path(environ.get("MYKHAYA_BACKUP_MARKER") or "/var/lib/mykhaya/last-backup.ok"),
            reports=Path(environ.get("MYKHAYA_PROD_MIGRATION_REPORT_DIR")
                         or "/var/lib/mykhaya/migration-reports"),
            config_backups=Path(environ.get("MYKHAYA_PROD_CONFIG_BACKUP_DIR")
                                or "/var/lib/mykhaya/config-backups"),
            dev_state=Path(environ.get("MYKHAYA_DEV_SERVICE_ENV_STATE")
                           or "/etc/mykhaya/dev/.service-env-state"),
        )


@dataclass
class Findings:
    items: list[tuple[str, str, str]] = field(default_factory=list)
    quiet: bool = False

    def _add(self, level: str, phase: str, message: str) -> None:
        self.items.append((level, phase, message))
        if not self.quiet:
            stream = sys.stderr if level == "FAIL" else sys.stdout
            print(f"[{level}] {phase}: {message}", file=stream, flush=True)

    def ok(self, phase: str, message: str) -> None:
        self._add("PASS", phase, message)

    def error(self, phase: str, message: str) -> None:
        self._add("FAIL", phase, message)

    def warn(self, phase: str, message: str) -> None:
        self._add("WARN", phase, message)

    def info(self, phase: str, message: str) -> None:
        self._add("INFO", phase, message)

    @property
    def errors(self) -> list[str]:
        return [f"{phase}: {message}" for level, phase, message in self.items if level == "FAIL"]

    def failed_since(self, mark: int) -> bool:
        return any(level == "FAIL" for level, _, _ in self.items[mark:])


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp() -> str:
    return now_utc().strftime("%Y%m%dT%H%M%SZ")


def file_metadata(path: Path) -> dict[str, int] | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    return {"inode": info.st_ino, "size": info.st_size, "mtime_ns": info.st_mtime_ns,
            "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file_name(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and set(name) <= SAFE_NAME_CHARS


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# --- Compose ------------------------------------------------------------------


@dataclass
class Release:
    tag: str = ""
    head: str = ""
    build_time: str = ""


def compose_command(paths: Paths, mode: str, root: Path | None = None,
                    release: Release | None = None) -> tuple[list[str], dict[str, str]]:
    """The exact Compose invocation prod-config-mode.sh uses, plus the release
    metadata prod-deploy.sh exports, so rendered models match what runs."""
    env = {k: v for k, v in os.environ.items()}
    if release is not None:
        env.update({P + "VERSION": release.tag, P + "COMMIT_SHA": release.head,
                    P + "BUILD_CHANNEL": "stable", P + "BUILD_TIME": release.build_time})
    files = ["-f", str(paths.repo / "compose.yml"), "-f", str(paths.repo / "compose.production.yml")]
    if mode == "legacy":
        env.pop("MYKHAYA_PROD_CONFIG_ROOT", None)
        return ["docker", "compose", *files], env
    root = root or paths.root
    for name in (P + "DB_PASSWORD", P + "MIGRATION_DB_PASSWORD", P + "POSTGRES_ADMIN_PASSWORD"):
        env.pop(name, None)
    env.update({P + "APNS_PRIVATE_KEY": "", P + "FCM_PRIVATE_KEY": "",
                "MYKHAYA_PROD_CONFIG_ROOT": str(root)})
    return ["docker", "compose", "--env-file", str(root / "compose.env"),
            "--env-file", str(root / "postgres.env"), *files,
            "-f", str(paths.repo / "compose.production.service-env.yml")], env


def render_model(paths: Paths, mode: str, root: Path | None, release: Release,
                 *, tools: bool = False) -> dict | None:
    command, env = compose_command(paths, mode, root, release)
    extra = ["--profile", "tools"] if tools else []
    result = run([*command, *extra, "config", "--format", "json"], env=env, cwd=paths.repo)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def service_hash(paths: Paths, mode: str, root: Path | None, release: Release,
                 service: str) -> str | None:
    command, env = compose_command(paths, mode, root, release)
    result = run([*command, "config", f"--hash={service}"], env=env, cwd=paths.repo)
    if result.returncode != 0:
        return None
    parts = result.stdout.split()
    return parts[-1] if len(parts) >= 2 and parts[0] == service else None


def model_env(model: dict, service: str) -> dict[str, str]:
    env = ((model.get("services") or {}).get(service) or {}).get("environment") or {}
    return {k: ("" if v is None else str(v).replace("$$", "$")) for k, v in env.items()}


def model_mounts(model: dict, service: str) -> dict[str, str]:
    """target -> source, with named volumes resolved to their real names."""
    volumes = model.get("volumes") or {}
    mounts = ((model.get("services") or {}).get(service) or {}).get("volumes") or []
    resolved: dict[str, str] = {}
    for mount in mounts:
        source = str(mount.get("source", ""))
        if mount.get("type") == "volume":
            source = (volumes.get(source) or {}).get("name") or f"{model.get('name')}_{source}"
        resolved[str(mount.get("target"))] = source
    return resolved


def image_name(model: dict, service: str) -> str:
    definition = (model.get("services") or {}).get(service) or {}
    return definition.get("image") or f"{model.get('name', PROJECT)}-{service}"


# --- Docker state ---------------------------------------------------------------


def docker_json(args: list[str]) -> object | None:
    result = run(["docker", *args])
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def project_containers(project: str = PROJECT) -> dict[str, list[dict]]:
    """Long-running containers of the project, by service (one-offs excluded)."""
    result = run(["docker", "ps", "-a", "-q", "--filter", f"label=com.docker.compose.project={project}"])
    ids = result.stdout.split() if result.returncode == 0 else []
    if not ids:
        return {}
    data = docker_json(["inspect", *ids]) or []
    by_service: dict[str, list[dict]] = {}
    for container in data if isinstance(data, list) else []:
        labels = (container.get("Config") or {}).get("Labels") or {}
        if labels.get("com.docker.compose.oneoff") == "True":
            continue
        service = labels.get("com.docker.compose.service")
        if service:
            by_service.setdefault(service, []).append(container)
    return by_service


def container_env(container: dict) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in (container.get("Config") or {}).get("Env") or []:
        name, _, value = str(item).partition("=")
        env[name] = value
    return env


def container_mounts(container: dict) -> dict[str, str]:
    return {str(m.get("Destination")): str(m.get("Name") or m.get("Source"))
            for m in container.get("Mounts") or []}


def image_details(name: str) -> dict | None:
    data = docker_json(["image", "inspect", name])
    if isinstance(data, list) and data:
        return data[0]
    return None


def image_env(details: dict | None) -> dict[str, str]:
    return container_env(details or {})


def psql(container_id: str, sql: str) -> tuple[bool, str]:
    """A read-only query in the running PostgreSQL container."""
    result = run(["docker", "exec", container_id, "psql", "-U", "postgres", "-d", "mykhaya",
                  "-v", "ON_ERROR_STOP=1", "-AtX", "-c", sql], timeout=60)
    return result.returncode == 0, result.stdout.strip()


# --- Static checks ----------------------------------------------------------------


def alembic_heads(versions: Path) -> set[str]:
    """Heads of the migration graph, from the revision files (no container)."""
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted(versions.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target, value = node.target, node.value
            else:
                continue
            if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                values[target.id] = ast.literal_eval(value)
        revision = values.get("revision")
        if isinstance(revision, str):
            revisions.add(revision)
            down = values.get("down_revision")
            parents.update(d for d in (down if isinstance(down, (tuple, list)) else (down,))
                           if isinstance(d, str))
    return revisions - parents


def parse_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def parse_timestamp(text: str) -> dt.datetime | None:
    if not text.strip().endswith("Z"):
        return None
    try:
        return dt.datetime.strptime(text.strip()[:-1] + "+0000", "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def is_age_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(21).startswith(b"age-encryption.org/v1")
    except OSError:
        return False


def compose_version_ok(text: str) -> bool:
    try:
        parts = tuple(int(p) for p in text.strip().lstrip("v").split("-")[0].split(".")[:3])
    except ValueError:
        return False
    return parts >= MIN_COMPOSE


def host_matches(expected: str) -> bool:
    expected = expected.strip().lower().rstrip(".")
    if not expected:
        return False
    names = {socket.gethostname().lower(), socket.getfqdn().lower()}
    return expected in names or expected in {n.split(".")[0] for n in names}


# --- The migration ------------------------------------------------------------------


class Migration:
    def __init__(self, paths: Paths, args: argparse.Namespace, findings: Findings) -> None:
        self.paths = paths
        self.args = args
        self.f = findings
        self.release = Release(tag=os.environ.get("MYKHAYA_RELEASE_TAG", ""))
        self.state = "unknown"
        self.legacy: dict[str, str] = {}
        self.files: dict[str, dict[str, str]] = {}
        self.split_report: dict[str, list[str]] = {}
        self.containers: dict[str, list[dict]] = {}
        self.candidate: dict | None = None
        self.target_root: Path | None = None
        self.staging: Path | None = None
        self.probe = None
        self.manifest_name = ""
        self.backup_dir: Path | None = None
        self.alembic_revision = ""
        self.images: dict[str, dict] = {}
        self.home_volume = ""

    # -- helpers --------------------------------------------------------------

    def postgres_id(self) -> str | None:
        found = self.containers.get("postgres") or []
        return found[0].get("Id") if len(found) == 1 else None

    def read_state(self) -> str:
        state_file = self.paths.state
        if state_file.is_symlink():
            return "linked"
        if not state_file.exists():
            return "legacy"
        lines = state_file.read_text(encoding="utf-8").splitlines()
        value = lines[0].strip() if lines else ""
        return value if value in {"legacy", "pending", "active", "rollback-pending"} else "unrecognised"

    def write_state(self, value: str) -> bool:
        """Through cutover-state.sh, the one implementation of the state file."""
        script = ('die() { printf "%s\\n" "$*" >&2; exit 1; }; . "$1"; '
                  'cutover_write_state "$2" "$3"')
        result = run(["sh", "-c", script, "sh", str(SCRIPTS / "cutover-state.sh"),
                      str(self.paths.state), value], cwd=self.paths.repo)
        return result.returncode == 0

    def mode_for_state(self) -> str:
        return "service-env" if self.state in {"pending", "active"} else "legacy"

    # -- phase: host -----------------------------------------------------------

    def check_host(self, *, for_apply: bool) -> None:
        f, phase = self.f, "host"
        if os.environ.get("MYKHAYA_PRODUCTION") != "1":
            f.error(phase, "MYKHAYA_PRODUCTION=1 is not set")
        if not host_matches(self.args.expect_host or ""):
            f.error(phase, "this host's name does not match --expect-host; refusing to touch an "
                           "unconfirmed host")
        else:
            f.ok(phase, "host name matches --expect-host")
        euid = os.geteuid() if hasattr(os, "geteuid") else -1
        if euid == 0:
            f.error(phase, "running as root; use the deployment account")
        elif euid == contract.SERVICE_UID:
            f.error(phase, f"running as the container service account ({contract.SERVICE_UID})")
        if self.paths.dev_state.exists() or self.paths.dev_state.is_symlink() or \
                self.paths.dev_state.parent.is_dir():
            f.error(phase, "the DEV configuration exists on this host; this is not the PROD host")
        for name in ("COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_PROFILES",
                     "COMPOSE_ENV_FILES", "DOCKER_HOST", "DOCKER_CONTEXT",
                     "MYKHAYA_DEV_CONFIG_ROOT", "MYKHAYA_PROD_LEGACY_ENV_ROLLBACK",
                     "MYKHAYA_PROD_SERVICE_ENV_CUTOVER"):
            if os.environ.get(name):
                f.error(phase, f"{name} is set in the environment; unset it")
        root_override = os.environ.get("MYKHAYA_PROD_CONFIG_ROOT")
        if root_override and Path(root_override) != self.paths.root:
            f.error(phase, "MYKHAYA_PROD_CONFIG_ROOT differs from the cutover state directory")
        if (self.paths.repo / "compose.override.yml").exists():
            f.error(phase, "compose.override.yml exists in the checkout; production never "
                           "loads it, and backup tooling would")
        env_meta = file_metadata(self.paths.legacy_env)
        if env_meta is None or self.paths.legacy_env.is_symlink() or \
                not self.paths.legacy_env.is_file():
            f.error(phase, "the legacy production .env is missing or not a regular file "
                           "(it is the source of every value and the rollback source)")
        else:
            names, _ = contract.parse_env_file(self.paths.legacy_env)
            for name in sorted(n for n in names if n.startswith(("COMPOSE_", "DOCKER_"))):
                f.error(phase, f"legacy .env sets {name}, which changes the Compose project or "
                               "Docker daemon; this cannot be migrated automatically")
            if env_meta["mode"] & 0o007:
                f.error(phase, f".env is accessible to other users (mode {env_meta['mode']:04o})")
            elif env_meta["mode"] & 0o070:
                f.warn(phase, f".env is accessible to its group (mode {env_meta['mode']:04o}); "
                              "0600 is documented")
        root = self.paths.root
        if not str(root).startswith("/"):
            f.error(phase, "the PROD configuration root must be an absolute path")
        if root.is_symlink() or not root.is_dir():
            f.error(phase, f"the PROD configuration root {root} does not exist; create it once: "
                           f"sudo install -d -m 0750 -o \"$USER\" -g \"$USER\" {root}")
        else:
            meta = file_metadata(root) or {}
            if meta.get("uid") != euid:
                f.error(phase, "the PROD configuration root is not owned by the deployment account")
            if meta.get("mode", 0) & 0o027:
                f.error(phase, f"the PROD configuration root mode {meta.get('mode', 0):04o} must be "
                               "0750 or 0700")
        self.state = self.read_state()
        if self.state in {"linked", "unrecognised"}:
            f.error(phase, f"the cutover state file is {self.state}; inspect it before continuing")
        else:
            f.info(phase, f"cutover state: {self.state}")
        info = docker_json(["info", "--format", "{{json .}}"])
        if not isinstance(info, dict):
            f.error(phase, "the Docker daemon is not reachable")
            return
        options = " ".join(str(o) for o in info.get("SecurityOptions") or [])
        if "userns" in options or "rootless" in options:
            f.error(phase, "Docker user-namespace remapping or rootless mode is not supported "
                           "(service ownership could not be verified)")
        version = run(["docker", "compose", "version", "--short"])
        if version.returncode != 0 or not compose_version_ok(version.stdout):
            f.error(phase, "Docker Compose 2.24.4 or later is required")
        else:
            f.ok(phase, f"Docker Compose {version.stdout.strip()}")
        self.check_disk(str(info.get("DockerRootDir") or "/var/lib/docker"))
        if for_apply:
            self.check_report_dir()

    def check_disk(self, docker_root: str) -> None:
        f, phase = self.f, "host"
        try:
            docker_mb = int(os.environ.get("MYKHAYA_PROD_MIN_FREE_MB_DOCKER",
                                           DEFAULT_MIN_FREE_MB["docker"]))
            other_mb = int(os.environ.get("MYKHAYA_PROD_MIN_FREE_MB", DEFAULT_MIN_FREE_MB["other"]))
        except ValueError:
            f.error(phase, "free-space thresholds must be whole numbers of MiB")
            return
        targets = [("Docker data", Path(docker_root), docker_mb),
                   ("checkout", self.paths.repo, other_mb),
                   ("configuration root", self.paths.root, other_mb),
                   ("reports", self.paths.reports.parent, other_mb)]
        for label, path, minimum in targets:
            probe = path
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            try:
                free = shutil.disk_usage(probe).free // (1024 * 1024)
            except OSError:
                if label == "Docker data":
                    free = shutil.disk_usage(self.paths.repo).free // (1024 * 1024)
                    f.warn(phase, "Docker data directory not readable; measured the checkout's "
                                  "file system instead")
                else:
                    f.error(phase, f"cannot measure free space for the {label}")
                    continue
            if free < minimum:
                f.error(phase, f"only {free} MiB free for the {label}; at least {minimum} MiB required")
            else:
                f.ok(phase, f"{free} MiB free for the {label}")

    def check_report_dir(self) -> None:
        try:
            self.paths.reports.mkdir(mode=0o700, parents=False, exist_ok=True)
            probe = self.paths.reports / f".probe-{os.getpid()}"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError:
            self.f.error("host", f"the report directory {self.paths.reports} is not writable")

    # -- phase: release --------------------------------------------------------

    def check_release(self) -> None:
        f, phase, repo = self.f, "release", self.paths.repo
        tag = self.release.tag
        if not tag:
            f.error(phase, "set MYKHAYA_RELEASE_TAG to the deployed, approved release tag")
            return

        def git(*args: str) -> subprocess.CompletedProcess:
            return run(["git", "-C", str(repo), *args])

        if git("check-ref-format", f"refs/tags/{tag}").returncode != 0:
            f.error(phase, "the release tag name is invalid")
            return
        fetch = git("fetch", "origin", "main", f"refs/tags/{tag}:refs/tags/{tag}")
        if fetch.returncode != 0:
            f.error(phase, "fetching origin/main and the release tag failed (has the tag moved?)")
            return
        tag_commit = git("rev-parse", f"refs/tags/{tag}^{{commit}}").stdout.strip()
        head = git("rev-parse", "HEAD").stdout.strip()
        if not tag_commit or tag_commit != head:
            f.error(phase, "HEAD is not the release tag; check out the deployed release first")
        elif git("merge-base", "--is-ancestor", tag_commit, "origin/main").returncode != 0:
            f.error(phase, "the release tag is not contained in origin/main")
        elif tag not in git("tag", "--points-at", "HEAD").stdout.split():
            f.error(phase, "HEAD is not exactly the release tag")
        else:
            f.ok(phase, f"HEAD is the approved release {tag} on origin/main")
        self.release.head = head
        if git("status", "--porcelain", "--untracked-files=all").stdout.strip():
            f.error(phase, "the checkout has uncommitted or untracked changes")
        version = run(["python3", str(SCRIPTS / "validate_version.py"), tag], cwd=repo)
        if version.returncode != 0:
            f.error(phase, "validate_version.py rejected the release tag")
        heads = alembic_heads(repo / "apps" / "api" / "migrations" / "versions")
        if len(heads) != 1:
            f.error(phase, f"the release has {len(heads)} Alembic heads; exactly one is required")
        self.alembic_head = next(iter(heads), "")

    # -- phase: stack ----------------------------------------------------------

    def check_stack(self) -> None:
        f, phase = self.f, "stack"
        mark = len(f.items)
        self.containers = project_containers()
        for service in (*APP_SERVICES, *UNCHANGED_SERVICES):
            found = self.containers.get(service) or []
            if len(found) != 1:
                f.error(phase, f"{service}: expected exactly one container in project "
                               f"{PROJECT}, found {len(found)}")
                continue
            if not (found[0].get("State") or {}).get("Running"):
                f.error(phase, f"{service}: is not running")
        if not self.containers:
            return
        model = render_model(self.paths, "legacy", None, self.release)
        if model is None:
            f.error(phase, "the legacy production Compose model could not be rendered")
            return
        if model.get("name") != PROJECT:
            f.error(phase, f"the Compose project name is not {PROJECT}")
        build_times = set()
        for service in IMAGE_SERVICES:
            details = image_details(image_name(model, service))
            if details is None:
                f.error(phase, f"{service}: image {image_name(model, service)} is not present; "
                               "it is never rebuilt or pulled for this migration")
                continue
            labels = (details.get("Config") or {}).get("Labels") or {}
            if labels.get("org.opencontainers.image.version") != self.release.tag or \
                    labels.get("org.opencontainers.image.revision") != self.release.head:
                f.error(phase, f"{service}: image was not built from the release checkout")
            build_times.add(labels.get("org.opencontainers.image.created", ""))
            self.images[service] = details
            running = self.containers.get(service) or []
            if running and running[0].get("Image") != details.get("Id"):
                f.error(phase, f"{service}: the running container does not use the release image")
        if len(build_times) == 1 and "" not in build_times:
            self.release.build_time = build_times.pop()
        elif self.images:
            f.error(phase, "the application images do not come from a single release build")
        for service in APP_SERVICES:
            running = self.containers.get(service) or []
            env = container_env(running[0]) if running else {}
            if env.get(P + "ENVIRONMENT") != "production" or env.get(P + "BUILD_CHANNEL") != "stable":
                f.error(phase, f"{service}: is not running the production stable channel")
        if not f.failed_since(mark):
            f.ok(phase, f"stack runs release {self.release.tag} from images built at "
                        f"{self.release.build_time}")
        pg = self.postgres_id()
        if pg:
            ok, current = psql(pg, "select version_num from alembic_version")
            if not ok:
                f.error(phase, "the database migration revision could not be read")
            elif current != getattr(self, "alembic_head", ""):
                f.error(phase, "the database is not at the release's Alembic head; deploy the "
                               "release normally before the configuration cutover")
            else:
                self.alembic_revision = current
                f.ok(phase, "database is at the release's single Alembic head")

    # -- phase: backup ---------------------------------------------------------

    def check_backup(self, *, for_apply: bool) -> None:
        f, phase = self.f, "backup"
        env = dict(os.environ)
        preflight = run(["sh", str(SCRIPTS / "backup-preflight.sh")], env=env, cwd=self.paths.repo)
        if preflight.returncode != 0:
            f.error(phase, "backup preflight failed (run it directly for details)")
        else:
            f.ok(phase, "backup preflight passed")
        source = self.paths.root / "compose.env" if self.mode_for_state() == "service-env" \
            else self.paths.legacy_env
        backup_dir = os.environ.get(P + "BACKUP_DIR") or self.env_file_value(source, P + "BACKUP_DIR") \
            or str(self.paths.repo / "backups")
        self.backup_dir = Path(backup_dir)
        if not self.paths.marker.is_file():
            f.error(phase, "the verified backup marker is missing; take a backup first "
                           "(make prod-backup)")
            return
        marker_text = self.paths.marker.read_text(encoding="utf-8").strip()
        created = parse_timestamp(marker_text)
        if created is None:
            f.error(phase, "the backup marker is not a timestamp")
            return
        age = now_utc() - created
        if age > MAX_BACKUP_AGE:
            f.error(phase, f"the last backup is {int(age.total_seconds() // 60)} minutes old; "
                           "the migration requires one taken within 2 hours")
        elif age < dt.timedelta(minutes=-5):
            f.error(phase, "the backup marker is in the future")
        else:
            f.ok(phase, f"last backup completed {int(age.total_seconds() // 60)} minutes ago")
        manifest = None
        try:
            candidates = sorted(self.backup_dir.glob("mykhaya-*.manifest"))
        except OSError:
            candidates = []
        for path in candidates:
            values = parse_manifest(path)
            if values.get("created_at") == marker_text:
                manifest, data = path, values
        if manifest is None:
            f.error(phase, "no backup manifest matches the backup marker")
            return
        self.manifest_name = manifest.name
        if data.get("encryption") != "age":
            f.error(phase, "the latest backup is not age-encrypted")
        for kind in ("database", "files"):
            name = data.get(kind, "")
            artefact = self.backup_dir / name
            if not safe_file_name(name) or not artefact.is_file():
                f.error(phase, f"the {kind} artefact named by the manifest is missing")
                continue
            if not is_age_file(artefact):
                f.error(phase, f"the {kind} artefact is not age-encrypted")
            elif sha256_file(artefact) != data.get(f"{kind}_sha256"):
                f.error(phase, f"the {kind} artefact does not match its manifest checksum")
        pg = self.postgres_id()
        if pg:
            ok, row = psql(pg, "select succeeded::text || '|' || to_char(started_at at time zone "
                               "'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') from backup_runs "
                               "order by started_at desc limit 1")
            if not ok or row != f"true|{marker_text}":
                f.error(phase, "the latest recorded backup run is not the successful run the "
                               "marker describes")
        f.info(phase, f"latest backup manifest: {manifest.name}")
        if for_apply:
            if self.args.confirm_offhost_backup != manifest.name:
                f.error(phase, "--confirm-offhost-backup must name this manifest after its "
                               "artefacts were copied off-host and verified there "
                               f"({manifest.name})")
            else:
                f.ok(phase, "operator confirmed the off-host copy of this backup")

    @staticmethod
    def env_file_value(path: Path, name: str) -> str:
        if not path.is_file():
            return ""
        values, _ = contract.parse_env_file(path)
        return values.get(name, "")

    # -- phase: Home Migration --------------------------------------------------

    def check_home_migration(self) -> None:
        f, phase = self.f, "home-migration"
        model = render_model(self.paths, "legacy", None, self.release)
        name = ((model or {}).get("volumes") or {}).get("home_migration_data", {}).get("name", "")
        self.home_volume = name
        if not name:
            f.error(phase, "the Home Migration volume name could not be resolved")
            return
        details = docker_json(["volume", "inspect", name])
        if not isinstance(details, list) or not details:
            f.error(phase, f"the Home Migration volume {name} does not exist")
        users = run(["docker", "ps", "-a", "-q", "--filter", f"volume={name}"]).stdout.split()
        if not users:
            f.error(phase, f"no container references {name}; refusing to continue")
        pg = self.postgres_id()
        if not pg:
            f.error(phase, "PostgreSQL is not available to check for in-flight migrations")
            return
        statuses = ",".join(f"'{s}'" for s in IN_FLIGHT_STATUSES)
        ok, count = psql(pg, f"select count(*) from home_migration_packages where status in ({statuses})")
        if not ok or not count.isdigit():
            f.error(phase, "in-flight Home Migration packages could not be counted")
        elif int(count):
            f.error(phase, f"{count} Home Migration package(s) are uploaded or importing; finish or "
                           "discard them first (no override exists)")
        else:
            f.ok(phase, "no Home Migration package is in flight; the volume is present and in use")

    # -- phase: configuration -----------------------------------------------------

    def check_configuration(self, *, for_apply: bool) -> None:
        f, phase = self.f, "configuration"
        legacy, problems = contract.parse_env_file(self.paths.legacy_env)
        for problem in problems:
            f.error(phase, f"legacy .env: {problem}")
        if problems:
            return
        self.legacy = legacy
        files, report = contract.split_legacy_env(legacy, PROFILE)
        self.files, self.split_report = files, report
        accepted = set(filter(None, (self.args.accept_dropped or "").split(",")))
        for name in report.get(contract.UNCLASSIFIED_HEADING, []):
            if name.startswith(("COMPOSE_", "DOCKER_")):
                continue
            if name in accepted:
                f.warn(phase, f"{name} is not used by any service and is dropped (accepted)")
            else:
                f.error(phase, f"{name} is not part of the PROD contract; review it, then pass "
                               f"--accept-dropped {name} to drop it explicitly")
        for heading, names in report.items():
            if heading != contract.UNCLASSIFIED_HEADING:
                f.info(phase, f"{heading}: {', '.join(names) if names else 'none'}")
        present = [n for n in SERVICE_FILES if (self.paths.root / n).exists()]
        if present and len(present) != len(SERVICE_FILES):
            f.error(phase, f"the PROD root holds only some service files ({', '.join(present)}); "
                           "inspect them: a partial set is never completed automatically")
            return
        if present:
            self.target_root = self.paths.root
            for name in SERVICE_FILES:
                values, _ = contract.parse_env_file(self.paths.root / name)
                if values != files[name]:
                    differing = sorted(set(values) ^ set(files[name])
                                       | {k for k in set(values) & set(files[name])
                                          if values[k] != files[name][k]})
                    f.error(phase, f"{name} differs from what the legacy .env produces "
                                   f"(names: {', '.join(differing)}); the legacy .env or the "
                                   "file changed since generation. Resolve before continuing")
            f.info(phase, "validating the existing PROD service files")
        else:
            if not self.paths.root.is_dir():
                return
            self.staging = self.paths.root / f".check-{secrets.token_hex(6)}"
            self.staging.mkdir(mode=0o700)
            contract.write_split(files, self.staging, PROFILE)
            self.target_root = self.staging
            f.info(phase, "validating the generated files in a private staging directory "
                          "(removed afterwards)")
        self.validate_target()

    def validate_target(self) -> None:
        f, phase = self.f, "configuration"
        root = self.target_root
        assert root is not None
        api = self.images.get("api")
        model = render_model(self.paths, "legacy", None, self.release)
        image = image_name(model, "api") if model else f"{PROJECT}-api"
        if api is None:
            f.error(phase, "the API image is required for the key-directory probe")
            return
        try:
            self.probe = contract.docker_key_dir_probe(image)
        except contract.ProbeFailure as exc:
            f.error(phase, f"key-directory probe: {exc}")
            return
        report = contract.validate_root(root, repo_root=self.paths.repo, check_perms=True,
                                        probe=self.probe, profile=PROFILE)
        for warning in report.warnings:
            f.warn(phase, warning)
        for error in report.errors:
            f.error(phase, error)
        if report.errors:
            return
        f.ok(phase, f"PROD contract passed ({len(SERVICE_FILES)} files, permissions, separation, "
                    "key directories)")
        candidate = render_model(self.paths, "service-env", root, self.release, tools=True)
        if candidate is None:
            f.error(phase, "the service-specific Compose model could not be rendered")
            return
        self.candidate = candidate
        errors = contract.check_resolved_model(candidate, self.paths.repo, PROFILE) + \
            contract.check_provenance(candidate, root, PROFILE)
        for error in errors:
            f.error(phase, error)
        if not errors:
            f.ok(phase, "merged model: per-service allow-lists, provenance and bootstrap-password "
                        "isolation passed")
        _, env = compose_command(self.paths, "service-env", root, self.release)
        env["MYKHAYA_PRODUCTION"] = "1"
        runtime = run(["python3", str(SCRIPTS / "validate_backend_config.py")], env=env,
                      cwd=self.paths.repo, timeout=900)
        if runtime.returncode != 0:
            f.error(phase, "runtime Settings validation in throwaway probe containers failed "
                           "(run prod-deploy.sh validate after cutover for details)")
        else:
            f.ok(phase, "runtime Settings accepted by every service in throwaway probe containers")
        self.check_parity(root)

    def check_parity(self, root: Path) -> None:
        """The cutover changes isolation only: every value a service keeps must
        equal what the running container has now, and unchanged services must
        keep their Compose hash (so they are not recreated)."""
        f, phase = self.f, "parity"
        candidate = self.candidate or {}
        legacy_model = render_model(self.paths, "legacy", None, self.release)
        mark = len(f.items)
        for service in (*APP_SERVICES, *UNCHANGED_SERVICES):
            running = self.containers.get(service) or []
            if not running:
                continue
            current = container_env(running[0])
            wanted = model_env(candidate, service)
            for name in sorted(wanted):
                if name not in current:
                    f.error(phase, f"{service}: would newly receive {name}")
                elif current[name] != wanted[name]:
                    f.error(phase, f"{service}: {name} would change value (values not shown)")
            dropped = sorted(n for n in current if n.startswith((P, "POSTGRES_")) and n not in wanted
                             and n not in image_env(self.images.get(service)))
            if dropped:
                f.info(phase, f"{service}: will no longer receive {', '.join(dropped)}")
            mounts, now = model_mounts(candidate, service), container_mounts(running[0])
            for target, source in sorted(mounts.items()):
                if now.get(target) != source:
                    f.error(phase, f"{service}: mount {target} would change source")
        if legacy_model:
            for name, value in sorted(model_env(candidate, "migrate").items()):
                if model_env(legacy_model, "migrate").get(name) != value:
                    f.error(phase, f"migrate: {name} differs from the legacy model")
        for service in UNCHANGED_SERVICES:
            running = self.containers.get(service) or []
            label = ((running[0].get("Config") or {}).get("Labels") or {}).get(
                "com.docker.compose.config-hash") if running else None
            new = service_hash(self.paths, "service-env", root, self.release, service)
            if new is None or label != new:
                old = service_hash(self.paths, "legacy", None, self.release, service)
                why = "the running container already differs from the legacy model (drift since " \
                      "the last deployment)" if old != label else "the migration changes it"
                f.error(phase, f"{service}: would be recreated; {why}")
        if not f.failed_since(mark):
            f.ok(phase, "every retained value equals the running stack; postgres, redis, web and "
                        "caddy keep their configuration hash and will not be recreated")

    def cleanup_staging(self) -> None:
        if self.staging is not None and self.staging.parent == self.paths.root:
            for child in self.staging.iterdir():
                child.unlink()
            self.staging.rmdir()
            self.staging = None

    # -- snapshot and verification ---------------------------------------------

    def key_listings(self) -> dict[str, list[list]]:
        compose_values = self.files.get("compose.env", {})
        listings: dict[str, list[list]] = {}
        for key in contract.KEY_DIRS:
            path = compose_values.get(key, "")
            if not path or self.probe is None:
                continue
            listing = self.probe(path)
            entries = [listing.root, *(listing.entries or ())] if listing.root else []
            listings[key] = [[e.name, e.kind, e.mode, e.uid, e.gid, e.inode, e.size, e.mtime_ns]
                             for e in entries]
        return listings

    def project_volumes(self) -> dict[str, str]:
        result = run(["docker", "volume", "ls", "-q", "--filter",
                      f"label=com.docker.compose.project={PROJECT}"])
        names = set(result.stdout.split()) | ({self.home_volume} if self.home_volume else set())
        volumes: dict[str, str] = {}
        for name in sorted(names):
            data = docker_json(["volume", "inspect", name])
            if isinstance(data, list) and data:
                volumes[name] = str(data[0].get("CreatedAt", ""))
        return volumes

    def take_snapshot(self) -> dict:
        return {
            "created_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "release": self.release.tag, "commit": self.release.head,
            "build_time": self.release.build_time, "alembic": self.alembic_revision,
            "legacy_env": file_metadata(self.paths.legacy_env),
            "keys": self.key_listings(),
            "containers": {s: (self.containers.get(s) or [{}])[0].get("Id", "")
                           for s in UNCHANGED_SERVICES},
            "volumes": self.project_volumes(),
            "images": {s: d.get("Id", "") for s, d in self.images.items()},
            "backup_manifest": self.manifest_name,
        }

    def verify_cutover(self, snapshot: dict) -> None:
        f, phase = self.f, "verify"
        self.containers = project_containers()
        candidate = render_model(self.paths, "service-env", self.paths.root, self.release,
                                 tools=True) or {}
        expected_env_files = f"{self.paths.root / 'compose.env'},{self.paths.root / 'postgres.env'}"
        for service in UNCHANGED_SERVICES:
            running = self.containers.get(service) or [{}]
            if running[0].get("Id") != snapshot["containers"].get(service):
                f.error(phase, f"{service}: the container was recreated or replaced")
            # Drift: a later edit to postgres.env or compose.env changes the
            # model, so the next prod-deploy.sh update would recreate it.
            label = ((running[0].get("Config") or {}).get("Labels") or {}).get(
                "com.docker.compose.config-hash")
            wanted = service_hash(self.paths, "service-env", self.paths.root, self.release, service)
            if wanted is None or label != wanted:
                f.error(phase, f"{service}: its running configuration differs from the PROD root; "
                               "the next update would recreate it (configuration drift)")
        for service in APP_SERVICES:
            running = self.containers.get(service) or []
            if len(running) != 1 or not (running[0].get("State") or {}).get("Running"):
                f.error(phase, f"{service}: is not running")
                continue
            container = running[0]
            env = container_env(container)
            from_image = image_env(self.images.get(service))
            wanted = model_env(candidate, service)
            names = {n for n in env if n.startswith((P, "POSTGRES_"))}
            for name in sorted(names - set(wanted) - set(from_image)):
                f.error(phase, f"{service}: receives {name} from outside the PROD root")
            for name in sorted(set(wanted) - names):
                f.error(phase, f"{service}: does not receive {name}")
            for name in sorted(set(wanted) & names):
                if env[name] != wanted[name]:
                    f.error(phase, f"{service}: {name} differs from its service file")
            allowed = PROFILE.resolved_allowed[service]
            for name in sorted(set(wanted) - allowed):
                f.error(phase, f"{service}: receives {name}, which is outside its contract")
            for name in sorted(PROFILE.must_be_blank.get(service, set()) & set(env)):
                if env[name]:
                    f.error(phase, f"{service}: {name} must be blank")
            labels = (container.get("Config") or {}).get("Labels") or {}
            # Provenance evidence: Compose records the --env-file paths it used.
            # Fail closed: absent, malformed or different all mean the source
            # of this container's configuration cannot be proven.
            env_files = labels.get("com.docker.compose.project.environment_file")
            if env_files is None:
                f.error(phase, f"{service}: has no com.docker.compose.project.environment_file "
                               "label, so its configuration source cannot be proven")
            elif env_files != expected_env_files:
                f.error(phase, f"{service}: was not created from the PROD root's interpolation files")
            mounts = container_mounts(container)
            if set(mounts) != PROFILE.expected_mounts[service]:
                f.error(phase, f"{service}: mounts differ from the contract")
            if env.get(P + "ENVIRONMENT") != "production" or env.get(P + "BUILD_CHANNEL") != "stable":
                f.error(phase, f"{service}: is not production/stable")
            if service != "worker" and (env.get(P + "VERSION") != self.release.tag
                                        or env.get(P + "COMMIT_SHA") != self.release.head):
                f.error(phase, f"{service}: reports the wrong release metadata")
            if container.get("Image") != snapshot["images"].get(service):
                f.error(phase, f"{service}: does not run the release image it ran before")
        pg = self.postgres_id()
        ok, revision = psql(pg, "select version_num from alembic_version") if pg else (False, "")
        if not ok or revision != snapshot.get("alembic"):
            f.error(phase, "the database migration revision changed")
        if self.key_listings() != snapshot.get("keys"):
            f.error(phase, "key directory metadata changed during the cutover")
        if file_metadata(self.paths.legacy_env) != snapshot.get("legacy_env"):
            f.error(phase, "the legacy .env changed during the cutover")
        volumes = self.project_volumes()
        for name, created in snapshot.get("volumes", {}).items():
            if volumes.get(name) != created:
                f.error(phase, f"volume {name} is missing or was re-created")
        health = run(["sh", str(SCRIPTS / "prod-health.sh")], cwd=self.paths.repo)
        if health.returncode != 0:
            f.error(phase, "production health checks failed")
        if not f.errors:
            f.ok(phase, "running services match the PROD contract; data services, keys, volumes, "
                        "schema and release metadata are unchanged; health checks pass")

    # -- report -----------------------------------------------------------------

    def write_report(self, action: str) -> Path | None:
        lines = [
            f"MyKhaya F-03 PROD service configuration migration: {action}",
            f"time={now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"release={self.release.tag} commit={self.release.head}",
            f"cutover_state={self.read_state()}",
            "values=never recorded (names and metadata only)",
            "",
        ]
        lines += [f"[{level}] {phase}: {message}" for level, phase, message in self.f.items]
        lines += ["", f"result={'FAILED' if self.f.errors else 'PASSED'}",
                  ("manual gates (operator): off-host backup restore rehearsal, off-host "
                   "configuration backup recovery test, key escrow, live provider acceptance "
                   "(see docs/operations/prod-service-config-migration.md)")]
        try:
            self.paths.reports.mkdir(mode=0o700, exist_ok=True)
            path = self.paths.reports / f"f03-prod-{action}-{stamp()}.txt"
            atomic_write(path, "\n".join(lines) + "\n")
            return path
        except OSError:
            print("WARNING: the report could not be written", file=sys.stderr)
            return None


# --- Actions ---------------------------------------------------------------------


def readiness(m: Migration, *, for_apply: bool) -> None:
    m.check_host(for_apply=for_apply)
    if m.f.errors:
        return
    m.check_release()
    m.check_stack()
    if m.f.errors:
        return
    m.check_backup(for_apply=for_apply)
    m.check_home_migration()
    try:
        m.check_configuration(for_apply=for_apply)
    finally:
        if not for_apply or m.f.errors:
            m.cleanup_staging()


def action_check(m: Migration) -> int:
    if m.read_state() == "active":
        m.f.info("state", "the cutover is already active; checking the running services instead")
        return action_verify_active(m)
    readiness(m, for_apply=False)
    path = m.write_report("check")
    print(f"\nReport: {path}" if path else "")
    if m.f.errors:
        print(f"\nNOT READY: {len(m.f.errors)} finding(s) must be resolved. Nothing was changed.",
              file=sys.stderr)
        return 1
    print("\nAutomated checks passed. Nothing was changed.\n"
          "Before --apply the operator must also: copy the backup and an encrypted configuration "
          "backup off-host and verify them there, and confirm key escrow. --apply requires those "
          "confirmations explicitly.")
    return 0


def action_verify_active(m: Migration) -> int:
    m.check_host(for_apply=False)
    if not m.f.errors:
        m.check_release()
        m.check_stack()
    snapshot = load_snapshot(m.paths)
    if snapshot and not m.f.errors:
        m.files = {"compose.env": contract.parse_env_file(m.paths.root / "compose.env")[0]}
        m.probe = contract.docker_key_dir_probe(f"{PROJECT}-api")
        m.verify_cutover(snapshot)
    path = m.write_report("verify")
    print(f"\nReport: {path}" if path else "")
    return 1 if m.f.errors else 0


def load_snapshot(paths: Paths) -> dict | None:
    try:
        return json.loads(paths.snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_config_backup(m: Migration) -> None:
    f, phase = m.f, "config-backup"
    name = m.args.confirm_offhost_config_backup or ""
    if not safe_file_name(name):
        f.error(phase, "--confirm-offhost-config-backup must name a file created by --backup-config "
                       "after it was copied off-host and verified there")
        return
    artefact = m.paths.config_backups / name
    sidecar = m.paths.config_backups / f"{name}.manifest.json"
    try:
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        f.error(phase, "the configuration backup or its manifest is missing")
        return
    if not artefact.is_file() or not is_age_file(artefact) or \
            sha256_file(artefact) != manifest.get("sha256"):
        f.error(phase, "the configuration backup does not match its manifest")
        return
    if manifest.get("legacy_env") != file_metadata(m.paths.legacy_env):
        f.error(phase, "the legacy .env changed after the configuration backup; take a new one")
        return
    f.ok(phase, "operator confirmed the off-host copy of the encrypted configuration backup")
    if not m.args.confirm_key_escrow:
        f.error("keys", "--confirm-key-escrow is required: confirm the field keyrings (if "
                        "provisioned) and the Apple key are recoverable from escrow. The migration "
                        "never reads, copies or changes key material")
    else:
        f.ok("keys", "operator confirmed key escrow")


def action_apply(m: Migration) -> int:
    state = m.read_state()
    if state == "active":
        print("The service-specific PROD configuration is already active; nothing to do.")
        return 0
    readiness(m, for_apply=True)
    if not m.f.errors:
        check_config_backup(m)
    if m.f.errors:
        m.cleanup_staging()
        path = m.write_report("apply-refused")
        print(f"\nREFUSED: {len(m.f.errors)} finding(s). Nothing was changed. Report: {path}",
              file=sys.stderr)
        return 1
    f = m.f
    # Snapshot first. While a cutover or rollback is unfinished the original
    # snapshot is kept, so verification compares with the state before the
    # first attempt; with nothing in flight (legacy) it is retaken.
    snapshot = load_snapshot(m.paths) if state in {"pending", "rollback-pending"} else None
    if snapshot is None:
        snapshot = m.take_snapshot()
        atomic_write(m.paths.snapshot, json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        f.info("apply", "pre-cutover snapshot recorded (metadata only)")
    elif snapshot.get("release") != m.release.tag or snapshot.get("commit") != m.release.head:
        f.error("apply", "the unfinished cutover used a different release; deploy that release "
                         "or roll back before retrying")
    if m.staging is not None and not f.errors:
        contract.write_split(m.files, m.paths.root, PROFILE)
        m.cleanup_staging()
        report = contract.validate_root(m.paths.root, repo_root=m.paths.repo, check_perms=True,
                                        probe=m.probe, profile=PROFILE)
        for error in report.errors:
            f.error("apply", error)
        if not report.errors:
            f.ok("apply", "service files written (never overwriting) and validated in place")
    if f.errors:
        path = m.write_report("apply-refused")
        print(f"\nREFUSED before any container change. Report: {path}", file=sys.stderr)
        return 1
    print("\n==> Configuration-only cutover through prod-deploy.sh (release images reused)",
          flush=True)
    env = {k: v for k, v in os.environ.items()}
    env.update({"MYKHAYA_PRODUCTION": "1", "MYKHAYA_RELEASE_TAG": m.release.tag,
                "MYKHAYA_PROD_SERVICE_ENV_CUTOVER": "1", "MYKHAYA_PROD_REUSE_IMAGES": "1"})
    deploy = subprocess.run(["sh", str(SCRIPTS / "prod-deploy.sh"), "update"], env=env,
                            cwd=m.paths.repo, check=False)
    if deploy.returncode != 0:
        f.error("cutover", f"prod-deploy.sh stopped (exit {deploy.returncode}); nothing was rolled "
                           f"back. Cutover state: {m.read_state()}")
        path = m.write_report("apply-interrupted")
        print(f"\nINTERRUPTED. Diagnose with --status and the report ({path}); fix the cause and "
              "rerun the same --apply command, or roll back deliberately.", file=sys.stderr)
        return 1
    m.verify_cutover(snapshot)
    if f.errors:
        path = m.write_report("apply-unverified")
        print(f"\nThe cutover ran but verification failed; the state stays pending and nothing was "
              f"rolled back. Report: {path}", file=sys.stderr)
        return 1
    if not m.write_state("active"):
        f.error("apply", "the verified cutover could not be recorded as active")
        m.write_report("apply-unrecorded")
        return 1
    path = m.write_report("apply")
    print(f"\nCutover complete and verified. State: active. Report: {path}\n"
          "Keep the legacy .env unchanged; it is the rollback source. Run live provider "
          "acceptance now (runbook).")
    return 0


def action_backup_config(m: Migration) -> int:
    f, phase = m.f, "config-backup"
    m.check_host(for_apply=False)
    if f.errors:
        return 1
    m.state = m.read_state()
    source = m.paths.root / "compose.env" if m.mode_for_state() == "service-env" else m.paths.legacy_env
    recipients = Path(os.environ.get(P + "BACKUP_AGE_RECIPIENTS_FILE")
                      or Migration.env_file_value(source, P + "BACKUP_AGE_RECIPIENTS_FILE")
                      or "/etc/mykhaya/backup-recipients.txt")
    backup_dir = Path(os.environ.get(P + "BACKUP_DIR")
                      or Migration.env_file_value(source, P + "BACKUP_DIR")
                      or str(m.paths.repo / "backups"))
    preflight = run(["sh", str(SCRIPTS / "backup-preflight.sh")], cwd=m.paths.repo)
    if preflight.returncode != 0:
        f.error(phase, "backup preflight failed: age and public recipients are required")
        return 1
    out = m.paths.config_backups
    for forbidden, label in ((backup_dir, "the backup directory (copied off-host with database backups)"),
                             (m.paths.repo, "the repository checkout")):
        try:
            out.resolve().relative_to(forbidden.resolve())
            f.error(phase, f"the configuration backup directory must not be inside {label}")
            return 1
        except ValueError:
            pass
    out.mkdir(mode=0o700, parents=False, exist_ok=True)
    if stat.S_IMODE(out.stat().st_mode) & 0o077:
        f.error(phase, f"{out} must be mode 0700")
        return 1
    members = [("legacy.env", m.paths.legacy_env)]
    members += [(f"prod/{n}", m.paths.root / n) for n in SERVICE_FILES
                if (m.paths.root / n).is_file()]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for arcname, path in members:
            data = path.read_bytes()
            info = tarfile.TarInfo(arcname)
            info.size, info.mode, info.mtime = len(data), 0o600, 0
            archive.addfile(info, io.BytesIO(data))
    name = f"mykhaya-config-{stamp()}-{secrets.token_hex(3)}.tar.age"
    partial = out / f".{name}.partial"
    sealed = run(["age", "-R", str(recipients), "-o", str(partial)], input_bytes=buffer.getvalue())
    buffer.close()
    if sealed.returncode != 0 or not is_age_file(partial):
        partial.unlink(missing_ok=True)
        f.error(phase, "encryption failed; nothing was written")
        return 1
    os.chmod(partial, 0o600)
    final = out / name
    os.replace(partial, final)
    manifest = {"created_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), "file": name,
                "sha256": sha256_file(final), "encryption": "age",
                "members": [a for a, _ in members],
                "legacy_env": file_metadata(m.paths.legacy_env),
                "release": os.environ.get("MYKHAYA_RELEASE_TAG", "")}
    atomic_write(out / f"{name}.manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(f"Encrypted configuration backup: {final}\nSHA-256: {manifest['sha256']}\n"
          f"Members: {', '.join(manifest['members'])} (key material is never included)\n"
          "Next: copy it off-host through the approved encrypted channel, verify the checksum and a "
          "test decryption there (runbook), then pass "
          f"--confirm-offhost-config-backup {name} to --apply.")
    return 0


def action_status(m: Migration) -> int:
    state = m.read_state()
    print(f"Cutover state: {state}")
    if m.paths.state.is_file():
        lines = m.paths.state.read_text(encoding="utf-8").splitlines()
        if len(lines) > 1:
            print(lines[1])
    snapshot = load_snapshot(m.paths)
    if snapshot:
        print(f"Pre-cutover snapshot: release {snapshot.get('release')} at "
              f"{snapshot.get('created_at')} (alembic {snapshot.get('alembic')})")
    present = [n for n in SERVICE_FILES if (m.paths.root / n).exists()]
    print(f"Service files present: {len(present)}/{len(SERVICE_FILES)}")
    try:
        reports = sorted(m.paths.reports.glob("f03-prod-*.txt"))
    except OSError:
        reports = []
    if reports:
        print(f"Latest report: {reports[-1]}")
    guidance = {
        "legacy": "Not started (or rolled back). Next: --check.",
        "pending": "A cutover started but is not verified. Legacy deployments are refused. "
                   "Rerun the same --apply command to resume, or roll back deliberately "
                   "(--rollback-check).",
        "active": "Complete. make prod-update and prod-health use the service files automatically.",
        "rollback-pending": "A rollback started but did not finish. Rerun it with "
                            "MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1, or resume the cutover with --apply.",
    }
    print(guidance.get(state, "The state file needs inspection before anything else runs."))
    return 0


def action_rollback_check(m: Migration) -> int:
    f, phase = m.f, "rollback"
    state = m.read_state()
    if state not in {"pending", "active", "rollback-pending"}:
        print(f"Cutover state is {state}; there is nothing to roll back.")
        return 1
    snapshot = load_snapshot(m.paths) or {}
    if not m.paths.legacy_env.is_file():
        f.error(phase, "the legacy .env is missing; a configuration rollback is impossible")
    elif snapshot and file_metadata(m.paths.legacy_env) != snapshot.get("legacy_env"):
        f.warn(phase, "the legacy .env changed since the cutover started; review it first")
    else:
        f.ok(phase, "the legacy .env is present and unchanged")
    head = run(["git", "-C", str(m.paths.repo), "rev-parse", "HEAD"]).stdout.strip()
    tag = snapshot.get("release", "")
    if snapshot and head != snapshot.get("commit"):
        f.error(phase, "the checkout is no longer the release the cutover used")
    if f.errors:
        return 1
    print("\nEligible. The rollback restores only the configuration mapping (legacy root .env); it "
          "never touches data, schemas, credentials, keys or volumes, and reuses the release "
          "images. Run it only with Owner approval:\n\n"
          f"  MYKHAYA_PRODUCTION=1 MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1 MYKHAYA_PROD_REUSE_IMAGES=1 \\\n"
          f"    MYKHAYA_RELEASE_TAG={tag or '<deployed tag>'} sh infrastructure/scripts/prod-deploy.sh update\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    for flag in ("--check", "--apply", "--backup-config", "--status", "--rollback-check"):
        action.add_argument(flag, action="store_true")
    parser.add_argument("--expect-host", help="this host's name, as confirmed by the Owner")
    parser.add_argument("--accept-dropped", default="",
                        help="comma-separated legacy .env names reviewed and accepted as unused")
    parser.add_argument("--confirm-offhost-backup", default="",
                        help="the backup manifest name, after its artefacts were copied off-host "
                             "and verified there")
    parser.add_argument("--confirm-offhost-config-backup", default="",
                        help="the --backup-config file name, after it was copied off-host and "
                             "test-decrypted there")
    parser.add_argument("--confirm-key-escrow", action="store_true",
                        help="the field keyrings (if provisioned) and the Apple key are escrowed")
    args = parser.parse_args(argv)
    paths = Paths.from_environment()
    migration = Migration(paths, args, Findings())
    if (args.check or args.apply or args.backup_config) and not args.expect_host:
        parser.error("--expect-host is required")
    try:
        if args.check:
            return action_check(migration)
        if args.apply:
            return action_apply(migration)
        if args.backup_config:
            return action_backup_config(migration)
        if args.status:
            return action_status(migration)
        return action_rollback_check(migration)
    except contract.ProbeFailure as exc:
        print(f"ERROR: key-directory probe: {exc}", file=sys.stderr)
        return 1
    finally:
        migration.cleanup_staging()


if __name__ == "__main__":
    raise SystemExit(main())
