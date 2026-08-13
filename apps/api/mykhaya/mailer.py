import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import PlatformSmtpSettings
from mykhaya.secrets_crypto import SecretDecryptionError, decrypt_secret

SmtpSource = Literal["environment", "platform_admin", "unconfigured"]


@dataclass(frozen=True)
class SmtpConfig:
    source: SmtpSource
    configured: bool
    host: str = ""
    port: int = 587
    connection_security: Literal["none", "starttls", "tls"] = "starttls"
    username: str | None = None
    password: str | None = None
    sender: str = ""
    reply_to: str | None = None
    timeout_seconds: int = 10


def _from_environment(settings: Settings) -> SmtpConfig:
    return SmtpConfig(
        source="environment",
        configured=bool(settings.smtp_host.strip() and settings.email_from.strip()),
        host=settings.smtp_host,
        port=settings.smtp_port,
        connection_security="starttls" if settings.smtp_starttls else "none",
        username=settings.smtp_username,
        password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
        sender=settings.email_from,
        timeout_seconds=10,
    )


async def resolve_smtp_config(settings: Settings, db: AsyncSession) -> SmtpConfig:
    """Environment variables win when explicitly enabled; otherwise the Platform-Admin
    stored row is used if enabled; otherwise email is unconfigured.

    See docs/architecture/platform-control-centre.md "SMTP configuration precedence".
    """
    if settings.email_delivery_configured:
        return _from_environment(settings)

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

    return SmtpConfig(source="unconfigured", configured=False)


def send_email(config: SmtpConfig, recipient: str, subject: str, text: str) -> None:
    if not config.configured:
        raise RuntimeError("Email delivery is not configured")
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = recipient
    message["Subject"] = subject
    if config.reply_to:
        message["Reply-To"] = config.reply_to
    message.set_content(text)

    client_cm: smtplib.SMTP | smtplib.SMTP_SSL
    if config.connection_security == "tls":
        client_cm = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout_seconds)
    else:
        client_cm = smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds)
    with client_cm as client:
        if config.connection_security == "starttls":
            client.starttls()
        if config.username and config.password:
            client.login(config.username, config.password)
        client.send_message(message)
