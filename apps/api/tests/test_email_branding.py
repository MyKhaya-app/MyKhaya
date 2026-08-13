"""Branded HTML email rendering (mykhaya.email_branding), the multipart SMTP
transport and its categorised failures (mykhaya.mailer), and production SMTP
configuration validation (mykhaya.config).

No external SMTP provider is used anywhere here — send_email is exercised
against a fake smtplib.SMTP/SMTP_SSL, the same pattern test_smtp_settings.py
already uses.
"""

from __future__ import annotations

import smtplib
from email import message_from_bytes
from email.utils import parseaddr

import pytest
from pydantic import ValidationError

from mykhaya.config import Settings
from mykhaya.email_branding import CTA_LABELS, logo_url, render_email_html, render_html
from mykhaya.mailer import (
    EmailAuthenticationError,
    EmailConnectionError,
    EmailPermanentError,
    EmailTemporaryError,
    EmailTlsError,
    SmtpConfig,
    send_email,
)

SECRET_KEY = "a" * 40


def _settings(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "secret_key": SECRET_KEY,
        "environment": "development",
        "public_web_url": "https://mykhaya.app",
        "trusted_hosts": [
            "mykhaya.app",
            "localhost",
            "127.0.0.1",
            "admin.localhost",
            "status.localhost",
        ],
    }
    kwargs.update(overrides)
    return Settings.model_validate(kwargs)


# ---------------------------------------------------------------------------
# Branded HTML
# ---------------------------------------------------------------------------


def test_logo_url_is_https_and_public_not_relative_or_local() -> None:
    url = logo_url(_settings())
    assert url == "https://mykhaya.app/mykhaya-email-logo.png"
    assert url.startswith("https://")
    assert "localhost" not in url
    assert "api" not in url.split("/")[2]


def test_malicious_display_name_cannot_inject_html() -> None:
    html = render_email_html(
        _settings(),
        "household_invitation",
        "You're invited to join a MyKhaya Home",
        '<script>alert(1)</script> invited you to join "The <b>Smiths</b>" Home.\n\n'
        "Open this secure link:\n\nhttps://mykhaya.app/register?invitation=tok\n\n"
        "This invitation expires on 2026-12-31.",
        "https://mykhaya.app/register?invitation=tok",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>Smiths</b>" not in html
    assert "&lt;b&gt;Smiths&lt;/b&gt;" in html


@pytest.mark.parametrize(
    "template_type",
    [
        "email_verification",
        "password_reset",
        "household_invitation",
        "platform_administrator_invitation",
    ],
)
def test_every_template_type_gets_a_cta_button_to_its_link(template_type: str) -> None:
    link = "https://mykhaya.app/action?token=abc123"
    html = render_email_html(
        _settings(), template_type, "Subject", f"Open this secure link:\n\n{link}", link
    )
    assert f'href="{link}"' in html
    assert CTA_LABELS[template_type] in html
    # The fallback URL is still visible as plain text underneath, per spec,
    # even though it's also promoted to a button.
    assert link in html


def test_no_cta_when_no_link_provided() -> None:
    html = render_html(_settings(), subject="Notice", body_text="Just some text.")
    assert "<a href" not in html


def test_footer_contains_required_copy_and_domain() -> None:
    html = render_html(_settings(), subject="Subject", body_text="Body.")
    assert "MyKhaya helps families stay connected and organised." in html
    assert "This is an automated service message from MyKhaya" in html
    assert "mykhaya.app" in html


def test_html_uses_no_external_css_js_or_tracking_pixel() -> None:
    html = render_html(
        _settings(),
        subject="Subject",
        body_text="Body.",
        cta_label="Go",
        cta_url="https://mykhaya.app/x",
    )
    assert "<script" not in html
    assert "<link " not in html
    assert "javascript:" not in html
    # Only the logo image — no 1x1 tracking pixel.
    assert html.count("<img") == 1


# ---------------------------------------------------------------------------
# Multipart transport
# ---------------------------------------------------------------------------


class _FakeSmtp:
    last_message: object = None

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        pass

    def login(self, username: str, password: str) -> None:
        pass

    def send_message(self, message: object) -> None:
        type(self).last_message = message


def _config(**overrides: object) -> SmtpConfig:
    kwargs: dict[str, object] = {
        "source": "environment",
        "configured": True,
        "host": "smtp.example.com",
        "port": 587,
        "connection_security": "starttls",
        "sender": "MyKhaya <hello@mykhaya.app>",
        "timeout_seconds": 10,
    }
    kwargs.update(overrides)
    return SmtpConfig(**kwargs)  # type: ignore[arg-type]


def test_send_email_is_multipart_alternative_with_working_text_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    send_email(
        _config(),
        "someone@example.com",
        "Verify your MyKhaya email",
        "Plain body.",
        "<p>HTML body</p>",
    )
    sent = message_from_bytes(bytes(_FakeSmtp.last_message))  # type: ignore[arg-type]
    assert sent.is_multipart()
    parts = {part.get_content_type(): part for part in sent.walk()}
    assert "text/plain" in parts
    assert "text/html" in parts
    assert parts["text/plain"].get_payload().strip() == "Plain body."
    assert "<p>HTML body</p>" in parts["text/html"].get_payload()


def test_send_email_without_html_is_still_valid_and_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    send_email(_config(), "someone@example.com", "Subject", "Only plain text.", None)
    sent = message_from_bytes(bytes(_FakeSmtp.last_message))  # type: ignore[arg-type]
    assert sent.get_content_type() == "text/plain"
    assert sent.get_payload().strip() == "Only plain text."


def test_send_email_sets_required_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    send_email(
        _config(sender="MyKhaya <hello@mykhaya.app>", reply_to="support@mykhaya.app"),
        "someone@example.com",
        "Verify your MyKhaya email",
        "Body",
    )
    sent = message_from_bytes(bytes(_FakeSmtp.last_message))  # type: ignore[arg-type]
    assert parseaddr(sent["From"])[1] == "hello@mykhaya.app"
    assert sent["To"] == "someone@example.com"
    assert sent["Subject"] == "Verify your MyKhaya email"
    assert sent["Reply-To"] == "support@mykhaya.app"
    assert sent["Message-ID"]
    assert sent["Date"]
    assert sent["MIME-Version"] == "1.0"


def test_send_email_omits_reply_to_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    send_email(_config(reply_to=None), "someone@example.com", "Subject", "Body")
    sent = message_from_bytes(bytes(_FakeSmtp.last_message))  # type: ignore[arg-type]
    assert sent["Reply-To"] is None
    assert sent["List-Unsubscribe"] is None


def test_send_email_raises_when_unconfigured() -> None:
    with pytest.raises(RuntimeError):
        send_email(SmtpConfig(source="unconfigured", configured=False), "a@b.com", "S", "B")


# ---------------------------------------------------------------------------
# Categorised failures
# ---------------------------------------------------------------------------


def test_authentication_failure_is_categorised(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailAuth(_FakeSmtp):
        def login(self, username: str, password: str) -> None:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtplib, "SMTP", FailAuth)
    with pytest.raises(EmailAuthenticationError) as excinfo:
        send_email(_config(username="mailer", password="secret"), "a@b.com", "S", "B")
    assert "secret" not in str(excinfo.value)


def test_starttls_failure_is_categorised(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailStarttls(_FakeSmtp):
        def starttls(self) -> None:
            raise smtplib.SMTPNotSupportedError("STARTTLS not supported")

    monkeypatch.setattr(smtplib, "SMTP", FailStarttls)
    with pytest.raises(EmailTlsError):
        send_email(_config(), "a@b.com", "S", "B")


def test_connection_refused_is_categorised(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    with pytest.raises(EmailConnectionError):
        send_email(_config(), "a@b.com", "S", "B")


def test_permanent_recipient_rejection_is_categorised_and_not_marked_temporary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectRecipient(_FakeSmtp):
        def send_message(self, message: object) -> None:
            raise smtplib.SMTPRecipientsRefused({"a@b.com": (550, b"No such user")})

    monkeypatch.setattr(smtplib, "SMTP", RejectRecipient)
    with pytest.raises(EmailPermanentError):
        send_email(_config(), "a@b.com", "S", "B")


def test_temporary_recipient_rejection_is_categorised_as_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TempRejectRecipient(_FakeSmtp):
        def send_message(self, message: object) -> None:
            raise smtplib.SMTPRecipientsRefused({"a@b.com": (450, b"Mailbox busy")})

    monkeypatch.setattr(smtplib, "SMTP", TempRejectRecipient)
    with pytest.raises(EmailTemporaryError):
        send_email(_config(), "a@b.com", "S", "B")


def test_smtp_config_repr_never_includes_the_password() -> None:
    config = _config(username="mailer", password="super-secret-value")  # noqa: S106
    assert "super-secret-value" not in repr(config)
    assert "super-secret-value" not in str(config)


# ---------------------------------------------------------------------------
# Production configuration validation
# ---------------------------------------------------------------------------


def test_production_rejects_mailpit_host_once_email_is_configured() -> None:
    with pytest.raises(ValidationError, match="MYKHAYA_SMTP_HOST"):
        Settings.model_validate(
            {
                "secret_key": SECRET_KEY,
                "environment": "production",
                "public_web_url": "https://mykhaya.app",
                "admin_url": "https://admin.mykhaya.app",
                "status_url": "https://status.mykhaya.app",
                "trusted_hosts": ["mykhaya.app", "admin.mykhaya.app", "status.mykhaya.app"],
                "cors_origins": ["https://admin.mykhaya.app"],
                "cookie_secure": True,
                "admin_allowed_networks": ["10.0.0.0/8"],
                "admin_mfa_required": True,
                "email_delivery_configured": True,
                "smtp_host": "mailpit",
                "email_from": "MyKhaya <hello@mykhaya.app>",
            }
        )


def test_production_rejects_local_placeholder_from_address() -> None:
    with pytest.raises(ValidationError, match="MYKHAYA_EMAIL_FROM"):
        Settings.model_validate(
            {
                "secret_key": SECRET_KEY,
                "environment": "production",
                "public_web_url": "https://mykhaya.app",
                "admin_url": "https://admin.mykhaya.app",
                "status_url": "https://status.mykhaya.app",
                "trusted_hosts": ["mykhaya.app", "admin.mykhaya.app", "status.mykhaya.app"],
                "cors_origins": ["https://admin.mykhaya.app"],
                "cookie_secure": True,
                "admin_allowed_networks": ["10.0.0.0/8"],
                "admin_mfa_required": True,
                "email_delivery_configured": True,
                "smtp_host": "smtp.provider.example",
                "email_from": "MyKhaya <hello@mykhaya.local>",
            }
        )


def test_production_accepts_a_real_smtp_relay_and_from_address() -> None:
    settings = Settings.model_validate(
        {
            "secret_key": SECRET_KEY,
            "environment": "production",
            "public_web_url": "https://mykhaya.app",
            "admin_url": "https://admin.mykhaya.app",
            "status_url": "https://status.mykhaya.app",
            "trusted_hosts": ["mykhaya.app", "admin.mykhaya.app", "status.mykhaya.app"],
            "cors_origins": ["https://admin.mykhaya.app"],
            "cookie_secure": True,
            "admin_allowed_networks": ["10.0.0.0/8"],
            "admin_mfa_required": True,
            "email_delivery_configured": True,
            "smtp_host": "smtp.provider.example",
            "smtp_connection_security": "tls",
            "email_from": "MyKhaya <hello@mykhaya.app>",
        }
    )
    assert settings.smtp_host == "smtp.provider.example"


def test_production_without_email_delivery_configured_is_unaffected_by_dev_defaults() -> None:
    """Not yet turning email on in production isn't a lie about the (still
    default/unconfigured) SMTP settings — only an explicitly enabled,
    still-placeholder configuration is rejected."""
    Settings.model_validate(
        {
            "secret_key": SECRET_KEY,
            "environment": "production",
            "public_web_url": "https://mykhaya.app",
            "admin_url": "https://admin.mykhaya.app",
            "status_url": "https://status.mykhaya.app",
            "trusted_hosts": ["mykhaya.app", "admin.mykhaya.app", "status.mykhaya.app"],
            "cors_origins": ["https://admin.mykhaya.app"],
            "cookie_secure": True,
            "admin_allowed_networks": ["10.0.0.0/8"],
            "admin_mfa_required": True,
        }
    )
