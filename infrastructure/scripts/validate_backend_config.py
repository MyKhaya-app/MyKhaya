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
MARKER = "MYKHAYA_RUNTIME_CONFIG="
PROBE_PROJECT_PREFIX = "mykhaya-config-probe"


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


@dataclass(frozen=True)
class ProbeContext:
    project_name: str
    compose_args: tuple[str, ...]
    override_path: Path


def probe_project_name() -> str:
    """Return a valid, per-process Compose project name.

    A unique project prevents a validator run from joining or removing the
    persistent ``mykhaya`` networks and one-off containers. The PID also keeps
    concurrent local validation runs independent without leaving a fixed,
    reusable project name behind.
    """
    return f"{PROBE_PROJECT_PREFIX}-{os.getpid()}"


def compose_command(project_name: str | None = None) -> list[str]:
    command = list(COMPOSE_FILES)
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
    )


def resolved_service_images() -> dict[str, str]:
    """Resolve images from the normal merged project without printing config."""
    result = subprocess.run(
        [*compose_command(), "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise compose_failure("Compose configuration inspection", result)
    try:
        resolved = json.loads(result.stdout)
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


def create_probe_context() -> ProbeContext:
    """Create an isolated project override that reuses freshly built images."""
    project_name = probe_project_name()
    images = resolved_service_images()
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
    override_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ProbeContext(
        project_name=project_name,
        compose_args=(*compose_command(project_name), "-f", str(override_path)),
        override_path=override_path,
    )


def cleanup_probe(context: ProbeContext) -> None:
    """Remove only resources belonging to this validator's project."""
    result = subprocess.run(
        [*context.compose_args, "down", "--remove-orphans", "--volumes"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            "Warning: isolated backend-config probe cleanup failed: "
            + sanitize_diagnostics(f"{result.stdout}\n{result.stderr}"),
            file=sys.stderr,
        )
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
        "'apns_delivery_configured':s.apns_delivery_configured}))"
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
    )
    if result.returncode != 0:
        raise compose_failure(f"{service} backend configuration probe", result)
    return parse_config(service, result.stdout)


def validate(configs: list[RuntimeConfig]) -> list[str]:
    by_service = {item.service: item for item in configs}
    errors: list[str] = []
    api = by_service["api"]

    for service in ("api", "scheduler", "migrate"):
        if by_service[service].apns_delivery_configured:
            errors.append(f"{service} APNs delivery must be disabled")

    for service in ("worker", "scheduler"):
        item = by_service[service]
        if item.database_hash != api.database_hash or item.database_length != api.database_length:
            errors.append(f"{service} database_url differs from api")
        if item.redis_hash != api.redis_hash or item.redis_length != api.redis_length:
            errors.append(f"{service} redis_url differs from api")
        if item.secret_hash != api.secret_hash or item.secret_length != api.secret_length:
            errors.append(f"{service} session secret differs from api")
        if (item.smtp_host, item.smtp_port) != (api.smtp_host, api.smtp_port):
            errors.append(f"{service} SMTP connection differs from api")

    migrate = by_service["migrate"]
    # Migrations intentionally use the least-privileged migrator role, so the
    # full database URL fingerprint differs from the runtime app URL. The
    # actual database target must still be identical, and Redis/SMTP must match.
    if migrate.database_target != api.database_target:
        errors.append("migrate database target differs from api")
    if migrate.redis_hash != api.redis_hash or migrate.redis_length != api.redis_length:
        errors.append("migrate redis_url differs from api")
    if migrate.secret_hash != api.secret_hash or migrate.secret_length != api.secret_length:
        errors.append("migrate session secret differs from api")
    if (migrate.smtp_host, migrate.smtp_port) != (api.smtp_host, api.smtp_port):
        errors.append("migrate SMTP connection differs from api")
    return errors


def main() -> int:
    context: ProbeContext | None = None
    try:
        context = create_probe_context()
        configs = [container_probe(service, context) for service in SERVICES]
        errors = validate(configs)
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
