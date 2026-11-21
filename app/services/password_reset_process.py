"""Isolate blocking transports so deadlines also terminate DNS/TLS/SMTP calls."""
import asyncio
import json
import os
import re
import signal
import sys
import time
from dataclasses import asdict, dataclass

from app.core.config import Settings


MAX_PROCESS_INPUT_BYTES = 65536
MAX_PROCESS_RESULT_BYTES = 4096
CATEGORIES = {"accepted", "provider_not_configured", "authentication_failed", "rate_limited", "timeout", "provider_error"}
REASONS = {
    None, "missing_provider_credentials", "invalid_provider_credentials", "incomplete_smtp_credentials",
    "invalid_sender", "frontend_url_not_configured", "deadline", "child_exception", "child_exit",
    "invalid_child_result", "configuration_too_large", "unsupported_platform",
}


@dataclass(frozen=True)
class DeliveryResult:
    category: str
    exception_class: str | None = None
    status_code: int | None = None
    reason: str | None = None


def parse_delivery_result(content):
    try:
        value = json.loads(content)
        if not isinstance(value, dict) or set(value) != set(asdict(DeliveryResult("accepted"))):
            raise ValueError
        result = DeliveryResult(**value)
        if result.category not in CATEGORIES or result.reason not in REASONS:
            raise ValueError
        if result.exception_class is not None and (
            not isinstance(result.exception_class, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", result.exception_class) is None
        ):
            raise ValueError
        if result.status_code is not None and (type(result.status_code) is not int or not 100 <= result.status_code <= 599):
            raise ValueError
        return result
    except (ValueError, TypeError, RecursionError):
        return DeliveryResult("provider_error", reason="invalid_child_result")


def delivery_configuration(settings):
    # No database URL or JWT signing secret is passed into the transport process.
    names = (
        "app_env", "email_provider", "resend_from_email", "frontend_password_reset_url",
        "email_timeout_seconds", "email_connect_timeout_seconds", "smtp_host", "smtp_port",
        "smtp_username", "smtp_password", "smtp_from_email", "smtp_use_tls",
    )
    values = {name: getattr(settings, name) for name in names}
    values["resend_api_key"] = settings.resend_api_key.get_secret_value()
    return values


async def run_isolated_delivery(
    email, token, settings: Settings, *, idempotency_key,
    deadline_monotonic=None, command=None,
):
    # command is a test seam, never request/environment-controlled.
    if not hasattr(signal, "setitimer"):
        return DeliveryResult("provider_error", reason="unsupported_platform")
    deadline = min(
        deadline_monotonic if deadline_monotonic is not None else float("inf"),
        time.monotonic() + settings.email_delivery_deadline_seconds,
    )
    if deadline <= time.monotonic():
        return DeliveryResult("timeout", reason="deadline")
    payload = json.dumps({
        "email": email, "token": token, "configuration": delivery_configuration(settings),
        "idempotency_key": idempotency_key,
    }).encode()
    if len(payload) > MAX_PROCESS_INPUT_BYTES:
        return DeliveryResult("provider_not_configured", reason="configuration_too_large")
    arguments = command or (
        sys.executable, "-B", "-m", "app.scripts.password_reset_delivery", str(deadline),
    )
    # Never put credentials, recipients or tokens in argv or subprocess logs.
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *arguments, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=MAX_PROCESS_RESULT_BYTES + 1,
        env={**{key: value for key, value in os.environ.items() if key in {
            "PATH", "PYTHONPATH", "LANG", "LC_ALL", "TZ",
        }}, "PYTHONDONTWRITEBYTECODE": "1"},
    ))
    process = None
    try:
        async with asyncio.timeout(max(0, deadline - time.monotonic())):
            process = await asyncio.shield(spawn)
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            content = bytearray()
            while True:
                chunk = await process.stdout.read(min(1024, MAX_PROCESS_RESULT_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_PROCESS_RESULT_BYTES:
                    return DeliveryResult("provider_error", reason="invalid_child_result")
            await process.wait()
            if process.returncode in {124, -signal.SIGALRM}:
                return DeliveryResult("timeout", reason="deadline")
            if process.returncode != 0:
                return DeliveryResult("provider_error", reason="child_exit")
            return parse_delivery_result(content)
    except TimeoutError:
        return DeliveryResult("timeout", reason="deadline")
    except OSError as exc:
        return DeliveryResult("provider_error", exception_class=type(exc).__name__, reason="child_exit")
    finally:
        # Shield process creation so cancellation cannot orphan a newly created
        # child. The child's independent absolute alarm also covers parent death.
        if process is None:
            try:
                process = await asyncio.shield(spawn)
            except (OSError, asyncio.CancelledError):
                process = None
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await asyncio.shield(process.wait())
