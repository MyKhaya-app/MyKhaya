import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import PlatformSmtpSettings
from mykhaya.secrets_crypto import SecretDecryptionError, decrypt_secret

SmtpSource = Literal["environment", "platform_admin", "unconfigured"]


class EmailSendError(Exception):
    """Base for categorised send failures — mykhaya.worker branches retry
    behaviour on the subclass, and NotificationDelivery.sanitised_failure_reason
    stores `category` (never the raw exception message, which could include
    connection details or, from some SMTP servers, an echoed recipient
    address)."""

    category = "unknown_failure"


class EmailConnectionError(EmailSendError):
    """DNS resolution failure, connection refused, timeout, or the server
    disconnecting mid-handshake — a network/infrastructure problem, not
    anything about this specific message."""

    category = "dns_or_connectivity_failure"


class EmailAuthenticationError(EmailSendError):
    category = "smtp_authentication_failure"


class EmailTlsError(EmailSendError):
    category = "tls_failure"


class EmailPermanentError(EmailSendError):
    """The server permanently rejected the sender or every recipient (SMTP
    5xx) — retrying would fail identically forever."""

    category = "recipient_or_sender_rejected"


class EmailTemporaryError(EmailSendError):
    """The server rejected the sender/recipients or the send with an SMTP 4xx
    — a transient condition (e.g. greylisting, mailbox temporarily over
    quota) worth retrying with backoff."""

    category = "provider_temporary_failure"


@dataclass(frozen=True)
class SmtpConfig:
    source: SmtpSource
    configured: bool
    host: str = ""
    port: int = 587
    connection_security: Literal["none", "starttls", "tls"] = "starttls"
    username: str | None = None
    # repr=False: SmtpConfig otherwise gets logged/echoed whole in places like
    # structlog's exception context — dataclass's default __repr__ would
    # include the plaintext password.
    password: str | None = field(default=None, repr=False)
    sender: str = ""
    reply_to: str | None = None
    timeout_seconds: int = 10


def _from_environment(settings: Settings) -> SmtpConfig:
    return SmtpConfig(
        source="environment",
        configured=bool(settings.smtp_host.strip() and settings.email_from.strip()),
        host=settings.smtp_host,
        port=settings.smtp_port,
        connection_security=settings.smtp_connection_security,
        username=settings.smtp_username,
        password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
        sender=settings.email_from,
        reply_to=settings.smtp_reply_to,
        timeout_seconds=settings.smtp_timeout_seconds,
    )


async def resolve_smtp_config(settings: Settings, db: AsyncSession) -> SmtpConfig:
    """The enabled Platform Control Centre row is authoritative.

    Environment SMTP is retained only as an explicit development/test fallback for
    isolated local runs (for example, Mailpit). It must never override an enabled
    Platform Control Centre configuration.

    See docs/architecture/platform-control-centre.md "SMTP configuration precedence".
    """
    row = await db.scalar(select(PlatformSmtpSettings).limit(1))
    if row is not None and row.enabled:
        try:
            password = (
                decrypt_secret(settings, row.encrypted_password) if row.encrypted_password else None
            )
        except SecretDecryptionError:
            # The stored password can't be decrypted with the current MYKHAYA_SECRET_KEY
            # (most likely a secret-key rotation). Fail closed rather than sending
            # unauthenticated or crashing the Control Centre Email page — the admin needs
            # to re-enter the password.
            return SmtpConfig(source="platform_admin", configured=False)
        sender = f"{row.sender_name} <{row.sender_email}>" if row.sender_name else row.sender_email
        return SmtpConfig(
            source="platform_admin",
            configured=bool(row.host.strip() and row.sender_email.strip()),
            host=row.host,
            port=row.port,
            connection_security=row.connection_security.value,
            username=row.username if row.auth_enabled else None,
            password=password if row.auth_enabled else None,
            sender=sender,
            reply_to=row.reply_to,
            timeout_seconds=row.timeout_seconds,
        )

    if settings.environment in {"development", "test"} and settings.email_delivery_configured:
        return _from_environment(settings)

    return SmtpConfig(source="unconfigured", configured=False)


def _classify_response(code: int, default: type[EmailSendError]) -> EmailSendError:
    if 500 <= code < 600:
        return EmailPermanentError(f"SMTP {code}")
    if 400 <= code < 500:
        return EmailTemporaryError(f"SMTP {code}")
    return default(f"SMTP {code}")


def send_email(
    config: SmtpConfig, recipient: str, subject: str, text: str, html: str | None = None
) -> None:
    """Sends a multipart/alternative message (text/plain + optional text/html) —
    never HTML-only, so the message stays fully readable in a plain-text-only
    client or with remote images/HTML blocked. From/To/Subject/Reply-To are set
    explicitly; Date, Message-ID and MIME-Version/Content-Type structure are left
    to `EmailMessage`, which generates each correctly rather than being
    hand-built.

    Raises a specific EmailSendError subclass so callers (mykhaya.worker) can
    tell a permanent rejection (don't retry) from a transient/infrastructure
    failure (retry with backoff) without inspecting library-specific exception
    types themselves.
    """
    if not config.configured:
        raise RuntimeError("Email delivery is not configured")
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    if config.reply_to:
        message["Reply-To"] = config.reply_to
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        client_cm: smtplib.SMTP | smtplib.SMTP_SSL
        if config.connection_security == "tls":
            client_cm = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout_seconds)
        else:
            client_cm = smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds)
        with client_cm as client:
            if config.connection_security == "starttls":
                try:
                    client.starttls()
                except (smtplib.SMTPNotSupportedError, ssl.SSLError) as exc:
                    raise EmailTlsError("STARTTLS negotiation failed") from exc
            if config.username and config.password:
                try:
                    client.login(config.username, config.password)
                except smtplib.SMTPAuthenticationError as exc:
                    raise EmailAuthenticationError("SMTP authentication failed") from exc
            client.send_message(message)
    except EmailSendError:
        raise
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [code for code, _ in exc.recipients.values()]
        if codes and all(400 <= code < 500 for code in codes):
            raise EmailTemporaryError("All recipients temporarily refused") from exc
        raise EmailPermanentError("All recipients permanently refused") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise _classify_response(exc.smtp_code, EmailPermanentError) from exc
    except smtplib.SMTPResponseException as exc:
        raise _classify_response(exc.smtp_code, EmailTemporaryError) from exc
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailAuthenticationError("SMTP authentication failed") from exc
    except ssl.SSLError as exc:
        raise EmailTlsError("TLS connection failed") from exc
    except (TimeoutError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        raise EmailConnectionError("Could not connect to the mail server") from exc
