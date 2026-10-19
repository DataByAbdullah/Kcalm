import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def send_password_reset_email(email: str, reset_token: str) -> None:
    settings = get_settings()

    reset_link = (
        f"{settings.frontend_password_reset_url}"
        f"?token={reset_token}"
    )

    message = EmailMessage()
    message["Subject"] = "Reset your Kcalm password"
    message["From"] = settings.smtp_from_email
    message["To"] = email

    message.set_content(
        "You requested a password reset.\n\n"
        f"Reset your password using this link:\n{reset_link}\n\n"
        "If you did not request this, you can ignore this email."
    )
    if not settings.smtp_host or not settings.smtp_from_email:
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()

        if settings.smtp_username and settings.smtp_password:
            smtp.login(
                settings.smtp_username,
                settings.smtp_password,
            )

        smtp.send_message(message)
