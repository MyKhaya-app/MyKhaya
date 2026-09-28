"""Best-effort RFC 5424 forwarding for platform observability.

The dispatcher is deliberately bounded and isolated from request processing:
normal application logs are dropped when the queue is full or a destination is
unavailable.  The PCC test endpoint uses the same formatter and transport but
reports only a safe outcome.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from mykhaya.config import Settings

SyslogProtocol = Literal["udp", "tcp", "tls"]
SyslogMinimumLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
MINIMUM_LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
LEVEL_ALIASES = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "NOTICE": "INFO",
    "WARNING": "WARNING",
    "WARN": "WARNING",
    "ERROR": "ERROR",
    "EXCEPTION": "ERROR",
    "CRITICAL": "CRITICAL",
    "ALERT": "CRITICAL",
    "EMERGENCY": "CRITICAL",
}
LEVEL_PRI = {"DEBUG": 7, "INFO": 6, "WARNING": 4, "ERROR": 3, "CRITICAL": 2}
REDACTED = "[REDACTED]"
SENSITIVE_NAMES = {
    "password", "password_hash", "passwd", "secret", "token", "access_token",
    "refresh_token", "session_token", "device_token", "jwt", "cookie", "authorization",
    "api_key", "apikey", "private_key", "client_secret", "webhook_secret", "otp",
    "totp", "totp_secret", "csrf", "csrf_token", "database_url", "encryption_key",
}
PRIVATE_NAMES = {
    "email", "display_name", "name", "nickname", "note", "notes", "description",
    "body", "content", "subject", "title", "filename", "registration", "vehicle_notes",
    "support_message",
}
_SECRET_TEXT_PATTERNS = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[^\s,;]+"), r"\1 [REDACTED]"),
    (
        re.compile(r"(?i)\b(password|passwd|token|secret|api[_-]?key|client_secret)=([^&\s]+)"),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"(?i)(://[^/:\s]+):[^@/\s]+@"), r"\1:[REDACTED]@"),
)
MAX_SYSLOG_PAYLOAD_BYTES = 65536
QUEUE_CAPACITY = 1000


def redact(value: Any, key: str | None = None) -> Any:
    if key and (
        key.casefold() in SENSITIVE_NAMES
        or any(
            marker in key.casefold()
            for marker in ("password", "token", "secret", "api_key", "authorization", "cookie")
        )
    ):
        return REDACTED
    if key and key.casefold() in PRIVATE_NAMES:
        return REDACTED
    if isinstance(value, str):
        for pattern, replacement in _SECRET_TEXT_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


@dataclass(frozen=True)
class SyslogConfig:
    enabled: bool = False
    host: str = ""
    port: int = 6514
    protocol: SyslogProtocol = "tls"
    facility: int = 16  # local0
    environment: str = "development"
    tls_verify: bool = True
    minimum_level: SyslogMinimumLevel = "INFO"
    timeout_seconds: float = 2.0

    @classmethod
    def from_value(cls, value: Any, environment: str) -> SyslogConfig:
        if not isinstance(value, dict):
            return cls(environment=environment)
        protocol = value.get("protocol", "tls")
        if protocol not in {"udp", "tcp", "tls"}:
            raise ValueError("Syslog protocol must be udp, tcp or tls.")
        minimum_level = str(value.get("minimum_level", "INFO")).upper()
        if minimum_level not in MINIMUM_LEVEL_RANK:
            raise ValueError(
                "Syslog minimum level must be DEBUG, INFO, WARNING, ERROR or CRITICAL."
            )
        host = str(value.get("host", "")).strip()
        if any(character.isspace() or ord(character) < 32 for character in host):
            raise ValueError("Syslog host must not contain whitespace or control characters.")
        port = int(value.get("port", 6514))
        facility = int(value.get("facility", 16))
        timeout = float(value.get("timeout_seconds", 2.0))
        if not 1 <= port <= 65535:
            raise ValueError("Syslog port must be between 1 and 65535.")
        if not 0 <= facility <= 23:
            raise ValueError("Syslog facility must be between 0 and 23.")
        if not 0.1 <= timeout <= 10:
            raise ValueError("Syslog timeout must be between 0.1 and 10 seconds.")
        if value.get("enabled") and not host:
            raise ValueError("A syslog host is required when remote syslog is enabled.")
        return cls(
            enabled=bool(value.get("enabled", False)), host=host, port=port,
            protocol=protocol,
            facility=facility,
            environment=str(value.get("environment") or environment)[:80],
            tls_verify=bool(value.get("tls_verify", True)),
            minimum_level=minimum_level, timeout_seconds=timeout,
        )

    def public_dict(
        self,
        *,
        last_success: str | None = None,
        last_error: str | None = None,
        dropped_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "enabled": self.enabled, "configured": bool(self.host), "host": self.host,
            "port": self.port, "protocol": self.protocol, "facility": self.facility,
            "environment": self.environment, "tls_verify": self.tls_verify,
            "minimum_level": self.minimum_level,
            "last_successful_delivery": last_success,
            "last_error": last_error,
            "dropped_count": dropped_count,
        }


def syslog_config_from_platform_value(value: Any, environment: str) -> SyslogConfig:
    """Read the persisted PlatformSetting envelope used by PCC."""
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    return SyslogConfig.from_value(value, environment)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]")


def _sd_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9@:_-]", "_", value)


def normalize_event_level(value: Any) -> str:
    """Return the canonical severity shared by filtering and RFC5424 output."""
    return LEVEL_ALIASES.get(str(value or "INFO").strip().upper(), "INFO")


def format_rfc5424(config: SyslogConfig, event: Mapping[str, Any], *, service: str) -> bytes:
    clean = redact(dict(event))
    level = normalize_event_level(clean.pop("level", "INFO"))
    severity = LEVEL_PRI[level]
    timestamp = str(
        clean.pop(
            "timestamp",
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        )
    )
    event_type = str(clean.pop("event_type", "") or clean.get("event", "") or "application_event")
    message = str(clean.pop("event", clean.pop("message", "")))
    fields = {
        "environment": config.environment,
        "service": service,
        "level": level,
        "event_type": event_type,
        **clean,
    }
    def structured_field(key: str, value: Any) -> str:
        rendered = value if not isinstance(value, (dict, list)) else json.dumps(
            value, separators=(",", ":"), default=str
        )
        return f'{_sd_name(key)}="{_escape(str(rendered))}"'

    structured = " ".join(
        structured_field(key, value)
        for key, value in sorted(fields.items())
        if value is not None
    )
    sd = f'[mykhaya@32473 {structured}]' if structured else "-"
    safe_message = message.replace(chr(10), " ").replace(chr(13), " ")
    payload = (
        f"<{config.facility * 8 + severity}>1 {timestamp} - {service} - "
        f"{sd} {safe_message}\n"
    ).encode()
    if len(payload) <= MAX_SYSLOG_PAYLOAD_BYTES:
        return payload
    fallback_sd = (
        f'[mykhaya@32473 environment="{_escape(config.environment)}" '
        f'service="{_escape(service)}" level="{level}" '
        f'event_type="{_escape(event_type)}" truncated="true"]'
    )
    prefix = f"<{config.facility * 8 + severity}>1 {timestamp} - {service} - {fallback_sd} "
    available = max(
        0, MAX_SYSLOG_PAYLOAD_BYTES - len(prefix.encode()) - len(b" [truncated]\n")
    )
    shortened = safe_message.encode()[:available].decode("utf-8", "ignore")
    return f"{prefix}{shortened} [truncated]\n".encode()


async def send_syslog(
    config: SyslogConfig,
    payload: bytes,
    *,
    debug: Any | None = None,
) -> None:
    stage = "resolving"

    def report(message: str) -> None:
        if debug:
            debug(message)

    try:
        report(f"resolving destination host={config.host} port={config.port}")
        if config.protocol == "udp":
            stage = "udp_connect"
            report("connecting protocol=udp")
            transport, _ = await asyncio.wait_for(
                asyncio.get_running_loop().create_datagram_endpoint(
                    asyncio.DatagramProtocol, remote_addr=(config.host, config.port)
                ), config.timeout_seconds,
            )
            try:
                stage = "udp_write"
                report("writing protocol=udp")
                transport.sendto(payload)
            finally:
                transport.close()
            return
        ssl_context = None
        if config.protocol == "tls":
            ssl_context = ssl.create_default_context()
            if not config.tls_verify:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
        stage = "connect"
        report(f"connecting protocol={config.protocol}")
        if config.protocol == "tls":
            stage = "tls_handshake"
            report(f"TLS handshake verify={config.tls_verify}")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                config.host,
                config.port,
                ssl=ssl_context,
                server_hostname=config.host if ssl_context else None,
            ),
            config.timeout_seconds,
        )
        del reader
    except Exception as exc:
        report(f"delivery failed stage={stage} exception={type(exc).__name__}")
        raise
    try:
        stage = "write"
        report("writing")
        writer.write(payload)
        stage = "drain"
        report("draining")
        await asyncio.wait_for(writer.drain(), config.timeout_seconds)
    except Exception as exc:
        report(f"delivery failed stage={stage} exception={type(exc).__name__}")
        raise
    finally:
        stage = "close"
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), config.timeout_seconds)
        except Exception as exc:
            report(f"delivery failed stage={stage} exception={type(exc).__name__}")
            raise


class _QueuedEvent(dict[str, Any]):
    def __init__(self, event: dict[str, Any], completion: asyncio.Future[bool] | None) -> None:
        super().__init__(event)
        self.completion = completion


class SyslogDispatcher:
    def __init__(
        self, settings: Settings, *, service: str, config_loader: Any | None = None
    ) -> None:
        self.settings = settings
        self.service = service
        self.config_loader = config_loader
        self.queue: asyncio.Queue[_QueuedEvent] = asyncio.Queue(maxsize=QUEUE_CAPACITY)
        self.config = SyslogConfig(environment=settings.environment)
        self.task: asyncio.Task[None] | None = None
        self.last_successful_delivery: str | None = None
        self.last_error: str | None = None
        self.dropped_count = 0
        self._last_config_load = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._config_loaded = False
        self.events_seen = 0
        self.events_queued = 0
        self.events_sent = 0
        self.transport_failures = 0
        self.events_filtered = 0
        self.last_dispatch_attempt: str | None = None
        self.debug = os.getenv("MYKHAYA_SYSLOG_DEBUG", "").casefold() in {"1", "true", "yes"}

    def _debug(self, message: str) -> None:
        if self.debug:
            print(f"[SYSLOG-DEBUG] {message}", flush=True)

    def _event_is_allowed(self, event: Mapping[str, Any]) -> bool:
        event_rank = MINIMUM_LEVEL_RANK[normalize_event_level(event.get("level", "INFO"))]
        return event_rank >= MINIMUM_LEVEL_RANK[self.config.minimum_level]

    async def start(self) -> None:
        if self.task is None:
            self._loop = asyncio.get_running_loop()
            self._debug(
                f"dispatcher started pid={os.getpid()} dispatcher_id={id(self)} "
                f"queue_id={id(self.queue)} loop_available=true thread={threading.get_ident()}"
            )
            self._debug("config refresher started")
            await self._refresh_config()
            self.task = asyncio.create_task(self._run(), name="mykhaya-syslog-forwarder")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
            self._loop = None

    def mark_seen(self, event_name: str) -> None:
        self.events_seen += 1
        self._debug(
            f"processor invoked event={event_name[:80]!r} dispatcher available=true "
            f"pid={os.getpid()} thread={threading.get_ident()}"
        )

    def enqueue(
        self,
        event: Mapping[str, Any],
        *,
        completion: asyncio.Future[bool] | None = None,
    ) -> bool:
        event = redact(dict(event))
        loop = self._loop
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        # structlog's async methods (ainfo/aerror/etc.) execute the wrapped
        # synchronous logger in a worker thread.  asyncio.Queue is not
        # thread-safe, so marshal those events back to the loop that owns the
        # dispatcher.  Synchronous log calls on the loop retain the cheap
        # direct path.
        if loop is None:
            if running_loop is not None:
                return self._enqueue_now(event, completion)
            else:
                self._drop(completion)
                return False
        if running_loop is loop:
            return self._enqueue_now(event, completion)
        self._debug(
            f"event loop available=true scheduling event thread={threading.get_ident()}"
        )
        try:
            loop.call_soon_threadsafe(self._enqueue_now, event, completion)
            return True
        except RuntimeError:
            self._drop(completion)
            return False

    def _drop(self, completion: asyncio.Future[bool] | None = None) -> None:
        self.dropped_count += 1
        if completion and not completion.done():
            completion.set_result(False)

    def _enqueue_now(
        self, event: dict[str, Any], completion: asyncio.Future[bool] | None = None
    ) -> bool:
        try:
            self.queue.put_nowait(_QueuedEvent(event, completion))
            self.events_queued += 1
            self._debug(f"event queued queue size={self.queue.qsize()}")
            return True
        except asyncio.QueueFull:
            self._drop(completion)
            return False

    async def enqueue_and_wait(
        self, event: Mapping[str, Any], timeout_seconds: float = 5
    ) -> bool:
        loop = asyncio.get_running_loop()
        completion = loop.create_future()
        if not self.enqueue(event, completion=completion):
            return False
        return await asyncio.wait_for(completion, timeout_seconds)

    async def _refresh_config(self) -> None:
        if not self.config_loader or time.monotonic() - self._last_config_load < 5:
            return
        self._last_config_load = time.monotonic()
        try:
            loaded = await self.config_loader()
        except Exception as exc:  # noqa: BLE001 - configuration must fail closed
            self._debug(f"config refresh failed error_type={type(exc).__name__}")
            return
        if loaded:
            self.config = loaded
            self._config_loaded = True
            self._debug(
                f"config refreshed enabled={loaded.enabled} host_set={bool(loaded.host)} "
                f"protocol={loaded.protocol}"
            )

    async def _run(self) -> None:
        while True:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=5)
            except TimeoutError:
                # Refresh even while idle, so a PCC change takes effect without
                # restarting the long-running API, worker, or scheduler process.
                await self._refresh_config()
                continue
            try:
                self._debug("dispatcher consumed event")
                await self._refresh_config()
                if not self._event_is_allowed(event):
                    self.events_filtered += 1
                    self._debug(
                        f"event filtered minimum_level={self.config.minimum_level} "
                        f"event_level={event.get('level', 'info')}"
                    )
                    if event.completion and not event.completion.done():
                        event.completion.set_result(False)
                elif self.config.enabled and self.config.host:
                    self.last_dispatch_attempt = datetime.now(UTC).isoformat()
                    self._debug(
                        f"attempting transport enabled=true protocol={self.config.protocol}"
                    )
                    await send_syslog(
                        self.config,
                        format_rfc5424(self.config, event, service=self.service),
                        **({"debug": self._debug} if self.debug else {}),
                    )
                    self.last_successful_delivery = datetime.now(UTC).isoformat()
                    self.last_error = None
                    self.events_sent += 1
                    self._debug("transport completed")
                    if event.completion and not event.completion.done():
                        event.completion.set_result(True)
                else:
                    self.events_filtered += 1
                    if event.completion and not event.completion.done():
                        event.completion.set_result(False)
            except Exception as exc:  # noqa: BLE001 - logging must never escape
                self.last_error = type(exc).__name__
                self.transport_failures += 1
                self._debug(f"transport failed error_type={type(exc).__name__}")
                if event.completion and not event.completion.done():
                    event.completion.set_result(False)
            finally:
                self.queue.task_done()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "dispatcher_running": self.task is not None and not self.task.done(),
            "config_loaded": self._config_loaded,
            "queue_size": self.queue.qsize(),
            "queue_capacity": QUEUE_CAPACITY,
            "events_seen": self.events_seen,
            "events_queued": self.events_queued,
            "events_sent": self.events_sent,
            "events_filtered": self.events_filtered,
            "events_dropped": self.dropped_count,
            "transport_failures": self.transport_failures,
            "last_dispatch_attempt": self.last_dispatch_attempt,
            "last_successful_delivery": self.last_successful_delivery,
            "last_error": self.last_error,
        }


_dispatcher: SyslogDispatcher | None = None


def _forward_to_syslog(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    if _dispatcher:
        _dispatcher.mark_seen(str(event_dict.get("event", "")))
        _dispatcher.enqueue(event_dict)
    elif os.getenv("MYKHAYA_SYSLOG_DEBUG", "").casefold() in {"1", "true", "yes"}:
        print("[SYSLOG-DEBUG] processor invoked dispatcher available=false", flush=True)
    return event_dict


def configure_structlog_forwarding(dispatcher: SyslogDispatcher) -> None:
    global _dispatcher
    _dispatcher = dispatcher
    current = structlog.get_config()
    processors = [
        processor
        for processor in current.get("processors", [])
        if processor is not _forward_to_syslog
    ]
    processors.insert(0, _forward_to_syslog)
    structlog.configure(processors=processors)
    dispatcher._debug(
        f"forwarding processor installed=true before_renderer=true pid={os.getpid()}"
    )


def current_dispatcher() -> SyslogDispatcher | None:
    return _dispatcher
