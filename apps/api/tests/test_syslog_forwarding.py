import asyncio

import httpx
import pytest
import structlog
from starlette.requests import Request
from structlog.dev import ConsoleRenderer

from mykhaya.platform_schemas import SyslogSettingsUpdate
from mykhaya.syslog_forwarding import (
    REDACTED,
    SyslogConfig,
    SyslogDispatcher,
    format_rfc5424,
    normalize_event_level,
    redact,
    send_syslog,
    syslog_config_from_platform_value,
)


def config(**overrides: object) -> SyslogConfig:
    value = {"enabled": True, "host": "graylog.internal", **overrides}
    return SyslogConfig.from_value(value, "test")


def test_rfc5424_contains_environment_service_and_structured_fields() -> None:
    payload = format_rfc5424(
        config(),
        {"event": "request", "level": "info", "request_id": "req-1", "status": 200},
        service="mykhaya-api",
    ).decode()

    assert payload.startswith("<134>1 ")
    assert 'environment="test"' in payload
    assert 'service="mykhaya-api"' in payload
    assert 'level="INFO"' in payload
    assert 'event_type="request"' in payload
    assert 'request_id="req-1"' in payload
    assert payload.endswith(" request\n")


@pytest.mark.parametrize(
    ("input_level", "expected_level", "expected_pri"),
    [("warn", "WARNING", 132), ("error", "ERROR", 131), ("CRITICAL", "CRITICAL", 130)],
)
def test_rfc5424_exposes_canonical_level_and_matching_pri(
    input_level: str, expected_level: str, expected_pri: int
) -> None:
    payload = format_rfc5424(
        config(), {"event": "application_error", "level": input_level}, service="mykhaya-api"
    ).decode()
    assert payload.startswith(f"<{expected_pri}>1 ")
    assert f'level="{expected_level}"' in payload
    assert 'event_type="application_error"' in payload


def test_unknown_level_falls_back_to_info_for_output_and_filtering() -> None:
    assert normalize_event_level("not-a-level") == "INFO"
    payload = format_rfc5424(
        config(), {"event": "request", "level": "not-a-level"}, service="test"
    ).decode()
    assert payload.startswith("<134>1 ")
    assert 'level="INFO"' in payload


def test_minimum_level_filter_uses_canonical_aliases() -> None:
    class Settings:
        environment = "test"

    dispatcher = SyslogDispatcher(Settings(), service="test")  # type: ignore[arg-type]
    dispatcher.config = config(minimum_level="ERROR")
    assert not dispatcher._event_is_allowed({"level": "warn"})
    assert dispatcher._event_is_allowed({"level": "error"})


def test_redaction_is_recursive_and_covers_auth_material() -> None:
    value = {
        "headers": {"Authorization": "Bearer secret", "cookie": "session=secret"},
        "items": [{"api_key": "key"}],
    }
    assert redact(value) == {
        "headers": {"Authorization": REDACTED, "cookie": REDACTED},
        "items": [{"api_key": REDACTED}],
    }
    assert redact({"error": "Authorization: Bearer top-secret"}) == {
        "error": "Authorization: Bearer [REDACTED]"
    }
    assert redact({"display_name": "Private Name", "note": "Private note"}) == {
        "display_name": REDACTED,
        "note": REDACTED,
    }


def test_disabled_is_the_safe_default_and_malformed_enabled_config_fails() -> None:
    assert SyslogConfig.from_value({}, "test").enabled is False
    assert SyslogConfig.from_value({}, "test").minimum_level == "INFO"
    with pytest.raises(ValueError, match="host"):
        SyslogConfig.from_value({"enabled": True}, "test")
    with pytest.raises(ValueError, match="protocol"):
        SyslogConfig.from_value({"protocol": "smtp"}, "test")


def test_legacy_platform_envelope_defaults_minimum_level_to_info() -> None:
    config_from_legacy = syslog_config_from_platform_value(
        {"value": {"enabled": True, "host": "graylog.internal"}}, "test"
    )
    assert config_from_legacy.minimum_level == "INFO"


@pytest.mark.parametrize("minimum_level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_minimum_level_values_are_supported(minimum_level: str) -> None:
    assert config(minimum_level=minimum_level).minimum_level == minimum_level


def test_invalid_minimum_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="minimum level"):
        config(minimum_level="TRACE")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("minimum_level", "allowed"),
    [
        ("DEBUG", {"debug", "info", "warning", "error", "critical"}),
        ("INFO", {"info", "warning", "error", "critical"}),
        ("WARNING", {"warning", "error", "critical"}),
        ("ERROR", {"error", "critical"}),
        ("CRITICAL", {"critical"}),
    ],
)
async def test_minimum_level_filters_remote_events_without_counting_drops(
    monkeypatch: pytest.MonkeyPatch, minimum_level: str, allowed: set[str]
) -> None:
    class Settings:
        environment = "test"

    sent: list[bytes] = []

    async def capture(_config: SyslogConfig, payload: bytes) -> None:
        sent.append(payload)

    dispatcher = SyslogDispatcher(Settings(), service="test")  # type: ignore[arg-type]
    dispatcher.config = config(minimum_level=minimum_level)
    monkeypatch.setattr("mykhaya.syslog_forwarding.send_syslog", capture)
    await dispatcher.start()
    try:
        for level in ("debug", "info", "warning", "error", "critical"):
            delivered = await dispatcher.enqueue_and_wait({"event": level, "level": level})
            assert delivered is (level in allowed)
        assert len(sent) == len(allowed)
        assert dispatcher.events_filtered == 5 - len(allowed)
        assert dispatcher.dropped_count == 0
    finally:
        await dispatcher.stop()


def test_pcc_schema_accepts_only_configuration_fields_and_rejects_response_fields() -> None:
    body = SyslogSettingsUpdate.model_validate(
        {
            "enabled": False,
            "host": "",
            "port": 6514,
            "protocol": "tls",
            "facility": 16,
            "environment": "test",
            "tls_verify": True,
            "reason": "Disable central logging for testing",
            "confirmed": True,
        }
    )
    assert body.enabled is False
    with pytest.raises(ValueError):
        SyslogSettingsUpdate.model_validate(
            {
                **body.model_dump(),
                "configured": False,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("port", 0), ("port", 65536), ("facility", -1), ("facility", 24), ("protocol", "smtp")],
)
def test_pcc_schema_rejects_invalid_transport_values(field: str, value: object) -> None:
    payload = {
        "enabled": False,
        "host": "",
        "port": 6514,
        "protocol": "tls",
        "facility": 16,
        "environment": "test",
        "tls_verify": True,
        "reason": "Validate central logging settings",
        "confirmed": True,
        field: value,
    }
    with pytest.raises(ValueError):
        SyslogSettingsUpdate.model_validate(payload)


@pytest.mark.asyncio
async def test_dispatcher_drops_destination_failures_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Settings:
        environment = "test"

    dispatcher = SyslogDispatcher(Settings(), service="test")  # type: ignore[arg-type]
    dispatcher.config = config()

    async def fail(*args: object, **kwargs: object) -> None:
        raise OSError("destination down")

    monkeypatch.setattr("mykhaya.syslog_forwarding.send_syslog", fail)
    await dispatcher.start()
    dispatcher.enqueue({"event": "safe", "level": "info"})
    await asyncio.wait_for(dispatcher.queue.join(), 1)
    await dispatcher.stop()
    assert dispatcher.last_error == "OSError"


@pytest.mark.asyncio
async def test_configuration_changes_are_seen_without_restarting_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Settings:
        environment = "test"

    persisted = {
        "value": {
            "enabled": False,
            "host": "",
            "port": 6514,
            "protocol": "tls",
            "facility": 16,
            "environment": "test",
            "tls_verify": True,
        }
    }

    async def load_config() -> SyslogConfig:
        return syslog_config_from_platform_value(persisted, "test")

    sent: list[bytes] = []

    async def capture(_config: SyslogConfig, payload: bytes) -> None:
        sent.append(payload)

    dispatcher = SyslogDispatcher(
        Settings(), service="test", config_loader=load_config  # type: ignore[arg-type]
    )
    monkeypatch.setattr("mykhaya.syslog_forwarding.send_syslog", capture)
    await dispatcher.start()
    try:
        assert dispatcher.config.enabled is False
        assert dispatcher.config.host == ""
        dispatcher.enqueue({"event": "disabled"})
        await asyncio.wait_for(dispatcher.queue.join(), 1)
        assert not sent

        # This is the exact PlatformSetting envelope written by the PCC PUT.
        persisted["value"] = {
            **persisted["value"],
            "enabled": True,
            "host": "graylog.internal",
        }
        dispatcher._last_config_load = 0
        assert await dispatcher.enqueue_and_wait({"event": "enabled"})
        assert dispatcher.config.enabled is True
        assert dispatcher.config.host == "graylog.internal"
        assert len(sent) == 1

        persisted["value"] = {**persisted["value"], "enabled": False}
        dispatcher._last_config_load = 0
        assert not await dispatcher.enqueue_and_wait({"event": "disabled-again"})
        assert dispatcher.config.enabled is False
        assert len(sent) == 1
    finally:
        await dispatcher.stop()


@pytest.mark.asyncio
async def test_dispatcher_redacts_before_enqueue_and_counts_drops() -> None:
    class Settings:
        environment = "test"

    dispatcher = SyslogDispatcher(Settings(), service="test")  # type: ignore[arg-type]
    dispatcher.queue = asyncio.Queue(maxsize=1)
    dispatcher.enqueue({"event": "safe", "token": "secret"})
    assert dispatcher.queue.qsize() == 1
    assert dispatcher.queue.get_nowait()["token"] == REDACTED
    dispatcher.queue.task_done()
    dispatcher.enqueue({"event": "one"})
    dispatcher.enqueue({"event": "two"})
    assert dispatcher.dropped_count == 1


@pytest.mark.asyncio
async def test_structlog_async_events_are_marshaled_to_dispatcher_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Settings:
        environment = "test"

    dispatcher = SyslogDispatcher(Settings(), service="test")  # type: ignore[arg-type]
    dispatcher.config = config()
    sent: list[bytes] = []

    async def capture(_config: SyslogConfig, payload: bytes) -> None:
        sent.append(payload)

    monkeypatch.setattr("mykhaya.syslog_forwarding.send_syslog", capture)
    from mykhaya.syslog_forwarding import configure_structlog_forwarding

    configure_structlog_forwarding(dispatcher)
    await dispatcher.start()
    try:
        await structlog.get_logger("async-integration").ainfo(
            "request", request_id="req-1", status=200
        )
        await asyncio.wait_for(dispatcher.queue.join(), 1)
    finally:
        await dispatcher.stop()

    assert len(sent) == 1
    assert b"request_id=\"req-1\"" in sent[0]


@pytest.mark.asyncio
async def test_actual_fastapi_request_middleware_reaches_syslog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mykhaya import main

    sent: list[bytes] = []
    delivered = asyncio.Event()

    async def capture(_config: SyslogConfig, payload: bytes) -> None:
        sent.append(payload)
        delivered.set()

    monkeypatch.setattr("mykhaya.syslog_forwarding.send_syslog", capture)
    dispatcher = main.syslog_dispatcher
    original_loader = dispatcher.config_loader
    dispatcher.config_loader = None
    dispatcher.config = config()
    main.configure_structlog_forwarding(dispatcher)
    from mykhaya.syslog_forwarding import current_dispatcher

    assert current_dispatcher() is dispatcher
    from mykhaya.syslog_forwarding import _forward_to_syslog

    assert any(
        processor is _forward_to_syslog
        for processor in structlog.get_config()["processors"]
    )
    assert any(
        isinstance(processor, ConsoleRenderer)
        for processor in structlog.get_config()["processors"]
    )
    await dispatcher.start()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://localhost",
        ) as client:
            response = await client.get("/api/v1/health/live")
        await asyncio.wait_for(delivered.wait(), 1)
    finally:
        await dispatcher.stop()
        dispatcher.config_loader = original_loader

    assert response.status_code == 200
    assert any(payload.endswith(b" request\n") for payload in sent), (
        dispatcher.queue.qsize(), dispatcher.last_error, dispatcher.dropped_count
    )
    diagnostics = dispatcher.diagnostics()
    assert diagnostics["events_seen"] >= 1
    assert diagnostics["events_queued"] >= 1
    assert diagnostics["events_sent"] >= 1


@pytest.mark.asyncio
async def test_real_audit_pipeline_reaches_syslog_with_redaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mykhaya import main
    from mykhaya.audit import audit

    sent: list[bytes] = []
    delivered = asyncio.Event()

    async def capture(_config: SyslogConfig, payload: bytes) -> None:
        sent.append(payload)
        delivered.set()

    class Database:
        def add(self, _value: object) -> None:
            return None

    monkeypatch.setattr("mykhaya.syslog_forwarding.send_syslog", capture)
    dispatcher = main.syslog_dispatcher
    dispatcher.config_loader = None
    dispatcher.config = config()
    main.configure_structlog_forwarding(dispatcher)
    await dispatcher.start()
    try:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/integration-test",
                "headers": [],
                "query_string": b"",
                "server": ("test", 80),
                "client": ("test", 1),
                "scheme": "http",
            }
        )
        request.state.request_id = "audit-request"
        audit(
            Database(),
            request,
            "integration_test",
            metadata={"token": "should-not-leave", "safe": "kept"},
        )
        await asyncio.wait_for(delivered.wait(), 1)
    finally:
        await dispatcher.stop()

    assert sent
    assert b"audit_event" in sent[0]
    assert b'\\"safe\\":\\"kept\\"' in sent[0]
    assert b"should-not-leave" not in sent[0]


def test_all_transport_values_are_accepted() -> None:
    assert {
        config(protocol=protocol).protocol for protocol in ("udp", "tcp", "tls")
    } == {"udp", "tcp", "tls"}


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["tcp", "tls"])
async def test_stream_transports_write_and_close(
    monkeypatch: pytest.MonkeyPatch, protocol: str
) -> None:
    class Writer:
        def __init__(self) -> None:
            self.payload = b""
            self.closed = False

        def write(self, payload: bytes) -> None:
            self.payload = payload

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    writer = Writer()

    async def open_connection(*args: object, **kwargs: object) -> tuple[None, Writer]:
        return None, writer

    monkeypatch.setattr("mykhaya.syslog_forwarding.asyncio.open_connection", open_connection)
    await send_syslog(config(protocol=protocol), b"payload")
    assert writer.payload == b"payload"
    assert writer.closed


@pytest.mark.asyncio
async def test_udp_transport_sends_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    class Transport:
        def __init__(self) -> None:
            self.payload = b""
            self.closed = False

        def sendto(self, payload: bytes) -> None:
            self.payload = payload

        def close(self) -> None:
            self.closed = True

    transport = Transport()

    async def endpoint(*args: object, **kwargs: object) -> tuple[Transport, None]:
        return transport, None

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "create_datagram_endpoint", endpoint)
    await send_syslog(config(protocol="udp"), b"payload")
    assert transport.payload == b"payload"
    assert transport.closed
