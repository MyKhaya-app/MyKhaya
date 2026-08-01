import smtplib
from email.message import EmailMessage

from mykhaya.config import Settings


def send_email(settings: Settings, recipient: str, subject: str, text: str) -> None:
    if not settings.email_delivery_configured:
        raise RuntimeError("Email delivery is not configured")
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username and settings.smtp_password:
            client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        client.send_message(message)
