import smtplib
from email.message import EmailMessage

from mykhaya.config import Settings


def send_email(settings: Settings, recipient: str, subject: str, text: str) -> None:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        client.send_message(message)
