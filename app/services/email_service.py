"""Password-reset delivery with safe, provider-independent failure reporting."""
import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from email_validator import EmailNotValidError, validate_email

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)
RESEND_EMAILS_URL = "https://api.resend.com/emails"
MAX_PROVIDER_RESPONSE_BYTES = 8192


class EmailDeliveryError(Exception):
    """Contains only safe metadata, never provider messages or request content."""

    def __init__(self, category: str, provider: str, *, exception_class: str | None = None,
                 status_code: int | None = None, reason: str | None = None):
        super().__init__(category)
        self.category = category
        self.provider = provider
        self.exception_class = exception_class
        self.status_code = status_code
        self.reason = reason


def frontend_reset_url(settings: Settings) -> str | None:
    value = settings.frontend_password_reset_url.strip()
    try:
        parts = urlsplit(value)
        if (not parts.hostname or parts.username is not None or parts.password is not None
                or parts.fragment or any(c.isspace() or ord(c) < 32 for c in value)):
            return None
        # A localhost default must never become a production reset link.
        if parts.scheme != "https":
            if settings.is_production or parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
                return None
        if settings.is_production and parts.hostname in {"localhost", "127.0.0.1", "::1"}:
            return None
        parts.port  # Reject malformed ports without logging the configured URL.
    except ValueError:
        return None
    return value


def email_configuration_issue(settings: Settings) -> str | None:
    if settings.email_provider == "resend":
        key = settings.resend_api_key.get_secret_value()
        if not key.strip() or not settings.resend_from_email.strip():
            return "missing_provider_credentials"
        if any(not 33 <= ord(c) <= 126 for c in key):
            return "invalid_provider_credentials"
    elif not settings.smtp_host.strip() or not settings.smtp_from_email.strip():
        return "missing_provider_credentials"
    elif bool(settings.smtp_username) != bool(settings.smtp_password):
        return "incomplete_smtp_credentials"
    sender = settings.resend_from_email if settings.email_provider == "resend" else settings.smtp_from_email
    try:
        if any(ord(c) < 32 or ord(c) == 127 for c in sender):
            return "invalid_sender"
        _, address = parseaddr(sender)
        validate_email(address, check_deliverability=False)
    except (EmailNotValidError, ValueError):
        return "invalid_sender"
    if frontend_reset_url(settings) is None:
        return "frontend_url_not_configured"
    return None


def warn_if_email_unconfigured(settings: Settings) -> None:
    issue = email_configuration_issue(settings)
    if issue:
        logger.warning("Password reset email provider is not configured. provider=%s category=provider_not_configured reason=%s",
                       settings.email_provider, issue, extra={
            "event": "password_reset_email_configuration", "provider": settings.email_provider,
            "category": "provider_not_configured", "reason": issue,
        })


def send_resend_email(settings: Settings, email: str, text: str, *, idempotency_key: str | None = None) -> None:
    try:
        timeout = httpx.Timeout(settings.email_timeout_seconds, connect=settings.email_connect_timeout_seconds)
        # TLS verification stays enabled. Do not follow redirects or inherit proxy
        # configuration that could forward credentials to an unintended endpoint.
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            headers = {
                "Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}",
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
            }
            if idempotency_key is not None:
                headers["Idempotency-Key"] = idempotency_key
            with client.stream("POST", RESEND_EMAILS_URL, headers=headers, json={
                "from": settings.resend_from_email,
                "to": [email], "subject": "Reset your Kcalm password", "text": text,
            }) as response:
                status = response.status_code
                if not 200 <= status < 300:
                    category = {401: "authentication_failed", 429: "rate_limited"}.get(status, "provider_error")
                    # Provider bodies can contain recipient addresses and message
                    # content. Never read or log them on errors, including redirects.
                    raise EmailDeliveryError(category, "resend", status_code=status)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise EmailDeliveryError("provider_error", "resend", status_code=status)
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    if len(chunk) > MAX_PROVIDER_RESPONSE_BYTES - len(content):
                        raise EmailDeliveryError("provider_error", "resend", status_code=status)
                    content.extend(chunk)
                try:
                    result = json.loads(content)
                except (ValueError, RecursionError):
                    raise EmailDeliveryError("provider_error", "resend", status_code=status) from None
                if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"].strip():
                    raise EmailDeliveryError("provider_error", "resend", status_code=status)
    except httpx.TimeoutException as exc:
        raise EmailDeliveryError("timeout", "resend", exception_class=type(exc).__name__) from None
    except (httpx.HTTPError, OSError) as exc:
        raise EmailDeliveryError("provider_error", "resend", exception_class=type(exc).__name__) from None


def send_smtp_email(settings: Settings, email: str, text: str, *, idempotency_key: str | None = None) -> None:
    message = EmailMessage()
    message["Subject"] = "Reset your Kcalm password"
    message["From"] = settings.smtp_from_email
    message["To"] = email
    if idempotency_key is not None:
        message["Message-ID"] = f"<password-reset-{idempotency_key}@password-reset.invalid>"
    message.set_content(text)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.email_timeout_seconds) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            if smtp.send_message(message):
                raise EmailDeliveryError("provider_error", "smtp")
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailDeliveryError("authentication_failed", "smtp", exception_class=type(exc).__name__) from None
    except TimeoutError as exc:
        raise EmailDeliveryError("timeout", "smtp", exception_class=type(exc).__name__) from None
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailDeliveryError("provider_error", "smtp", exception_class=type(exc).__name__) from None


def send_password_reset_email(email: str, reset_token: str, *, settings: Settings | None = None,
                              idempotency_key: str | None = None) -> None:
    settings = settings or get_settings()
    issue = email_configuration_issue(settings)
    if issue:
        raise EmailDeliveryError("provider_not_configured", settings.email_provider, reason=issue)
    parts = urlsplit(frontend_reset_url(settings))
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "token"]
    query.append(("token", reset_token))
    reset_link = urlunsplit(parts._replace(query=urlencode(query)))
    text = (
        "You requested a password reset.\n\n"
        f"Reset your password using this link:\n{reset_link}\n\n"
        "If you did not request this, you can ignore this email."
    )
    if settings.email_provider == "resend":
        send_resend_email(settings, email, text, idempotency_key=idempotency_key)
    else:
        send_smtp_email(settings, email, text, idempotency_key=idempotency_key)
    logger.info("Password reset email submitted. provider=%s category=accepted", settings.email_provider, extra={
        "event": "password_reset_email_delivery", "provider": settings.email_provider,
        "category": "accepted",
    })
