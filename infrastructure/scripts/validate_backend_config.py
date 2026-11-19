#!/usr/bin/env python3
"""Validate merged Compose backend runtime settings before a dev update.

The check deliberately runs ``mykhaya.config.Settings`` inside fresh containers
created from the fully merged base/dev Compose files. It reports only hashes and
metadata, never connection strings or secret values.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

COMPOSE_FILES = (
    "docker",
    "compose",
    "-f",
    "compose.yml",
    "-f",
    "compose.production.yml" if os.environ.get("MYKHAYA_PRODUCTION") == "1" else "compose.dev.yml",
)
SERVICES = ("api", "worker", "scheduler", "migrate")
# The APNs topic must be the bundle ID of the app the backend serves. Each
# backend serves one iOS app, and production serves the PROD app
# (docs/mobile/ios-environments.md). A topic for the wrong app is rejected by
# APNs, and the worker then disables that device's registration.
PRODUCTION_APNS_BUNDLE_ID = "app.mykhaya.mobile.prod"
MARKER = "MYKHAYA_RUNTIME_CONFIG="
PROBE_PROJECT_PREFIX = "mykhaya-config-probe"
SERVICE_ENV_OVERLAY = "compose.dev.service-env.yml"
# compose.yml/compose.dev.yml interpolate these secrets; the service-env overlay
# removes the keys, and the validator forces them blank so no shell value leaks.
BLANKED_INTERPOLATION = (
    "MYKHAYA_DB_PASSWORD",
    "MYKHAYA_MIGRATION_DB_PASSWORD",
    "MYKHAYA_POSTGRES_ADMIN_PASSWORD",
    "MYKHAYA_APNS_PRIVATE_KEY",
)


def is_production() -> bool:
    return os.environ.get("MYKHAYA_PRODUCTION") == "1"


def service_env_root() -> str | None:
    """The explicitly selected DEV configuration root, or None (legacy/PROD)."""
    if is_production():
        return None
    return os.environ.get("MYKHAYA_DEV_CONFIG_ROOT") or None


def base_compose_args() -> list[str]:
    root = service_env_root()
    if root is None:
        return list(COMPOSE_FILES)
    return [
        "docker", "compose", "--env-file", f"{root.rstrip('/')}/compose.env",
        "-f", "compose.yml", "-f", "compose.dev.yml", "-f", SERVICE_ENV_OVERLAY,
    ]


def compose_environment() -> dict[str, str] | None:
    if service_env_root() is None:
        return None
    env = dict(os.environ)
    env.update({name: "" for name in BLANKED_INTERPOLATION})
    return env


@dataclass(frozen=True)
class RuntimeConfig:
    service: str
    database_hash: str
    database_length: int
    database_target: str
    redis_hash: str
    redis_length: int
    secret_hash: str
    secret_length: int
    smtp_host: str
    smtp_port: int
    apns_delivery_configured: bool
    environment: str = ""
    apns_bundle_id: str = ""
    email_delivery_configured: bool = False


@dataclass(frozen=True)
class ProbeContext:
    project_name: str
    compose_args: tuple[str, ...]
    override_path: Path


class ProbeIsolationError(RuntimeError):
    """The probe cannot be proven to own every resource it would create."""


def probe_project_name() -> str:
    """Return a valid, unique, collision-resistant Compose project name.

    A unique project prevents a validator run from joining or removing the
    persistent ``mykhaya`` networks, volumes and one-off containers. The PID
    keeps concurrent runs apart and the random suffix rules out reuse of a
    stale project left by an earlier process with the same PID.
    """
    return f"{PROBE_PROJECT_PREFIX}-{os.getpid()}-{secrets.token_hex(4)}"


def compose_command(project_name: str | None = None) -> list[str]:
    command = base_compose_args()
    if project_name is not None:
        command[2:2] = ["-p", project_name]
    return command


def sanitize_diagnostics(output: str, limit: int = 4000) -> str:
    """Keep Compose failures useful without echoing connection credentials."""
    sanitized = re.sub(
        r"(?i)(postgres(?:ql)?(?:\+[^:/\s]+)?://)[^\s'\"]+",
        r"\1<redacted>",
        output,
    )
    sanitized = re.sub(r"(?i)(redis://)[^\s'\"]+", r"\1<redacted>", sanitized)
    sanitized = re.sub(
        r"(?i)(password|secret|token|private[_-]?key)(\s*[=:]\s*)[^\s,;]+",
        r"\1\2<redacted>",
        sanitized,
    )
    sanitized = sanitized.strip()
    if len(sanitized) > limit:
        return sanitized[:limit] + "…"
    return sanitized or "(no diagnostic output)"


def compose_failure(action: str, result: subprocess.CompletedProcess[str]) -> RuntimeError:
    details = sanitize_diagnostics("\n".join(part for part in (result.stdout, result.stderr) if part))
    return RuntimeError(f"{action} failed with exit code {result.returncode}: {details}")


def fingerprint(value: object) -> tuple[str, int]:
    raw = str(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16], len(raw)


def database_target(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = parsed.port or ""
    return f"{parsed.scheme}://{host}:{port}{parsed.path}"


def parse_config(service: str, output: str) -> RuntimeConfig:
    line = next((item for item in output.splitlines() if item.startswith(MARKER)), None)
    if line is None:
        raise ValueError(f"{service} did not return a runtime configuration record")
    data = json.loads(line.removeprefix(MARKER))
    return RuntimeConfig(
        service=service,
        database_hash=data["database_hash"],
        database_length=data["database_length"],
        database_target=data["database_target"],
        redis_hash=data["redis_hash"],
        redis_length=data["redis_length"],
        secret_hash=data["secret_hash"],
        secret_length=data["secret_length"],
        smtp_host=data["smtp_host"],
        smtp_port=data["smtp_port"],
        apns_delivery_configured=data["apns_delivery_configured"],
        environment=data.get("environment", ""),
        apns_bundle_id=data.get("apns_bundle_id", ""),
        email_delivery_configured=data.get("email_delivery_configured", False),
    )


def resolved_model() -> dict:
    """The merged Compose model, held in memory only and never printed."""
    result = subprocess.run(
        [*compose_command(), "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        env=compose_environment(),
    )
    if result.returncode != 0:
        raise compose_failure("Compose configuration inspection", result)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Compose configuration was not valid JSON: {exc}") from exc


def probe_owned_volumes(resolved: dict) -> list[str]:
    """Every declared volume key, each to be renamed into the probe project.

    The probe must never own or reference an application data volume. Compose
    deletes any non-external volume a project declares on `down --volumes`,
    even one created by another project, as soon as no container (running or
    stopped) still holds it. compose.dev.yml and compose.production.yml pin
    home_migration_data to a fixed name, and an explicit name can also equal
    the default `<project>_<key>` pattern, so every volume is renamed
    unconditionally rather than detecting "fixed" names.

    An external volume is by definition an existing real volume that cannot be
    renamed, so its presence fails validation closed instead of letting the
    probe mount it.
    """
    volumes = resolved.get("volumes") or {}
    external = sorted(key for key, volume in volumes.items() if (volume or {}).get("external"))
    if external:
        raise ProbeIsolationError(
            "external volumes cannot be isolated from the configuration probe: "
            + ", ".join(external)
        )
    return sorted(volumes)


def resolved_service_images(resolved: dict | None = None) -> dict[str, str]:
    """Resolve images from the normal merged project without printing config."""
    if resolved is None:
        resolved = resolved_model()
    try:
        services = resolved["services"]
        project_name = resolved.get("name") or os.environ.get("COMPOSE_PROJECT_NAME", "mykhaya")
        images = {
            service: services[service].get("image") or f"{project_name}-{service}"
            for service in SERVICES
        }
        if any("build" not in services[service] and "image" not in services[service] for service in SERVICES):
            raise KeyError("a probe service has neither image nor build")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Compose configuration did not resolve probe images: {exc}") from exc
    return images


def create_probe_context(resolved: dict | None = None) -> ProbeContext:
    """Create an isolated project override that reuses freshly built images."""
    project_name = probe_project_name()
    if resolved is None:
        resolved = resolved_model()
    images = resolved_service_images(resolved)
    # DEV and PROD: rename every declared volume into the probe project, so the
    # probe never references an application volume.
    rescoped = probe_owned_volumes(resolved)
    temporary_directory = Path(tempfile.mkdtemp(prefix="mykhaya-config-probe-"))
    override_path = temporary_directory / "images.yml"
    # This is YAML because Compose's !reset tag is needed to remove the
    # persistent dev stack's fixed 10.77.x IPAM pools. The override changes
    # only image selection and probe networking; all service environment,
    # volumes and commands remain from the merged Compose files.
    lines = ["services:"]
    for service, image in images.items():
        lines.extend([f"  {service}:", f"    image: {json.dumps(image)}"])
    lines.extend(
        [
            "networks:",
            "  edge:",
            "    ipam:",
            "      config: !reset []",
            "  app:",
            "    ipam:",
            "      config: !reset []",
            "  data:",
            "    ipam:",
            "      config: !reset []",
        ]
    )
    if rescoped:
        lines.append("volumes:")
        for key in rescoped:
            lines.extend([f"  {key}:", f"    name: {json.dumps(f'{project_name}_{key}')}"])
    override_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ProbeContext(
        project_name=project_name,
        compose_args=(*compose_command(project_name), "-f", str(override_path)),
        override_path=override_path,
    )


def docker_volume_exists(name: str) -> bool:
    result = subprocess.run(
        ["docker", "volume", "inspect", name], capture_output=True, text=True, check=False
    )
    return result.returncode == 0


def verify_probe_isolation(context: ProbeContext) -> None:
    """Prove, before any probe container exists, that the probe owns everything.

    Every volume and network in the effective probe model must carry the probe
    project's own name prefix, none may be external, and no probe volume may
    exist yet. Otherwise validation fails closed without creating anything.
    """
    result = subprocess.run(
        [*context.compose_args, "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        env=compose_environment(),
    )
    if result.returncode != 0:
        raise compose_failure("Probe isolation inspection", result)
    try:
        model = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeIsolationError(f"probe model was not valid JSON: {exc}") from exc
    prefix = f"{context.project_name}_"
    problems = []
    for kind in ("volumes", "networks"):
        for key, resource in (model.get(kind) or {}).items():
            resource = resource or {}
            if resource.get("external"):
                problems.append(f"{kind[:-1]} {key} is external")
            elif not str(resource.get("name", "")).startswith(prefix):
                problems.append(f"{kind[:-1]} {key} is not probe-scoped")
            elif kind == "volumes" and docker_volume_exists(resource["name"]):
                problems.append(f"volume {key} already exists")
    if problems:
        raise ProbeIsolationError(
            "configuration probe isolation cannot be guaranteed: " + "; ".join(problems)
        )


def probe_owned_existing_volumes(project_name: str) -> list[str]:
    """Volumes demonstrably created by this probe: Compose's project label for
    this probe AND the probe's own name prefix. Application volumes carry
    their own project's label and can never match."""
    result = subprocess.run(
        ["docker", "volume", "ls", "-q", "--filter",
         f"label=com.docker.compose.project={project_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return sorted(
        name for name in result.stdout.split() if name.startswith(f"{project_name}_")
    )


def cleanup_probe(context: ProbeContext) -> None:
    """Remove only resources belonging to this validator's project.

    Containers and networks go with `down` (no --volumes); volumes are then
    removed one by one, and only when they carry this probe's project label
    and name prefix.
    """
    warnings = []
    result = subprocess.run(
        [*context.compose_args, "down", "--remove-orphans"],
        capture_output=True,
        text=True,
        check=False,
        env=compose_environment(),
    )
    if result.returncode != 0:
        warnings.append(sanitize_diagnostics("\n".join((result.stdout, result.stderr))))
    for name in probe_owned_existing_volumes(context.project_name):
        removed = subprocess.run(
            ["docker", "volume", "rm", name], capture_output=True, text=True, check=False
        )
        if removed.returncode != 0:
            warnings.append(f"probe volume {name} was not removed")
    for warning in warnings:
        print(f"Warning: isolated backend-config probe cleanup: {warning}", file=sys.stderr)
    try:
        context.override_path.unlink(missing_ok=True)
        context.override_path.parent.rmdir()
    except OSError:
        pass


def container_probe(service: str, context: ProbeContext) -> RuntimeConfig:
    code = (
        "import hashlib, json; "
        "from mykhaya.config import get_settings; "
        "s=get_settings(); "
        "db=str(s.database_url); redis=str(s.redis_url); "
        "secret=s.secret_key.get_secret_value(); "
        "h=lambda v: {'hash': hashlib.sha256(v.encode()).hexdigest()[:16], 'length': len(v)}; "
        "print('MYKHAYA_RUNTIME_CONFIG='+json.dumps({" 
        "'database_hash':h(db)['hash'], 'database_length':h(db)['length'], "
        "'database_target': __import__('urllib.parse', fromlist=['urlsplit']).urlsplit(db).scheme+'://'+(__import__('urllib.parse', fromlist=['urlsplit']).urlsplit(db).hostname or '')+':'+str(__import__('urllib.parse', fromlist=['urlsplit']).urlsplit(db).port or '')+__import__('urllib.parse', fromlist=['urlsplit']).urlsplit(db).path, "
        "'redis_hash':h(redis)['hash'], 'redis_length':h(redis)['length'], "
        "'secret_hash':h(secret)['hash'], 'secret_length':h(secret)['length'], "
        "'smtp_host':s.smtp_host, 'smtp_port':s.smtp_port, "
        "'apns_delivery_configured':s.apns_delivery_configured, "
        "'environment':s.environment, "
        "'apns_bundle_id':getattr(s, 'apns_bundle_id', ''), "
        "'email_delivery_configured':s.email_delivery_configured}))"
    )
    result = subprocess.run(
        [
            *context.compose_args,
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            service,
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=compose_environment(),
    )
    if result.returncode != 0:
        raise compose_failure(f"{service} backend configuration probe", result)
    return parse_config(service, result.stdout)


def validate(configs: list[RuntimeConfig], *, service_env: bool = False) -> list[str]:
    """Cross-service consistency of the probed runtime settings.

    service_env: the DEV service-specific layout, where migrate receives no
    Redis/SMTP settings and the scheduler receives SMTP only when monitoring an
    environment-configured relay, so those are compared only where supplied.
    """
    by_service = {item.service: item for item in configs}
    errors: list[str] = []
    api = by_service["api"]

    for service in ("api", "scheduler", "migrate"):
        if by_service[service].apns_delivery_configured:
            errors.append(f"{service} APNs delivery must be disabled")

    worker = by_service["worker"]
    if (
        worker.environment == "production"
        and worker.apns_delivery_configured
        and worker.apns_bundle_id != PRODUCTION_APNS_BUNDLE_ID
    ):
        errors.append(
            f"worker APNs topic (MYKHAYA_APNS_BUNDLE_ID) is '{worker.apns_bundle_id}', "
            f"expected '{PRODUCTION_APNS_BUNDLE_ID}' for the production app"
        )

    for service in ("worker", "scheduler"):
        item = by_service[service]
        if item.database_hash != api.database_hash or item.database_length != api.database_length:
            errors.append(f"{service} database_url differs from api")
        if item.redis_hash != api.redis_hash or item.redis_length != api.redis_length:
            errors.append(f"{service} redis_url differs from api")
        if item.secret_hash != api.secret_hash or item.secret_length != api.secret_length:
            errors.append(f"{service} session secret differs from api")
        compare_smtp = not (
            service_env and service == "scheduler" and not item.email_delivery_configured
        )
        if compare_smtp and (item.smtp_host, item.smtp_port) != (api.smtp_host, api.smtp_port):
            errors.append(f"{service} SMTP connection differs from api")

    migrate = by_service["migrate"]
    # Migrations intentionally use the least-privileged migrator role, so the
    # full database URL fingerprint differs from the runtime app URL. The
    # actual database target must still be identical, and Redis/SMTP must match.
    if migrate.database_target != api.database_target:
        errors.append("migrate database target differs from api")
    if not service_env and (
        migrate.redis_hash != api.redis_hash or migrate.redis_length != api.redis_length
    ):
        errors.append("migrate redis_url differs from api")
    if migrate.secret_hash != api.secret_hash or migrate.secret_length != api.secret_length:
        errors.append("migrate session secret differs from api")
    if not service_env and (migrate.smtp_host, migrate.smtp_port) != (api.smtp_host, api.smtp_port):
        errors.append("migrate SMTP connection differs from api")
    return errors


def contract_errors(resolved: dict) -> list[str]:
    """Names-only allow-list and provenance checks of the service-env model."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import service_env_contract
    finally:
        sys.path.pop(0)
    root = service_env_root()
    assert root is not None
    return service_env_contract.check_resolved_model(
        resolved, Path(__file__).resolve().parents[2]
    ) + service_env_contract.check_provenance(resolved, Path(root))


def main() -> int:
    context: ProbeContext | None = None
    service_env = service_env_root() is not None
    try:
        resolved = resolved_model()
        if service_env:
            errors = contract_errors(resolved)
            if errors:
                print("Merged DEV Compose model violates the service contract:", file=sys.stderr)
                for error in errors:
                    print(f"- {error}", file=sys.stderr)
                return 1
        context = create_probe_context(resolved)
        verify_probe_isolation(context)
        configs = [container_probe(service, context) for service in SERVICES]
        errors = validate(configs, service_env=service_env)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Backend runtime configuration validation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if context is not None:
            cleanup_probe(context)
    if errors:
        print("Backend runtime configuration validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    for item in configs:
        print(
            f"{item.service}: database_url=<redacted sha256:{item.database_hash} "
            f"len:{item.database_length}>, "
            f"redis_url=<redacted sha256:{item.redis_hash} len:{item.redis_length}>"
        )
    print("Backend runtime configuration validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
