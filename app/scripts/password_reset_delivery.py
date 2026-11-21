"""Private transport child: bounded stdin/result, no database, no secret logging."""
import json
import os
import signal
import sys
import time


def main():
    # Use the kernel's terminating action, not a Python exception handler that
    # could be delayed inside a C DNS/TLS call. The absolute deadline includes
    # process startup and remains valid when the API parent dies.
    if not hasattr(signal, "setitimer"):
        return 1
    try:
        remaining = float(sys.argv[1]) - time.monotonic()
        if remaining <= 0:
            return 124
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL, remaining)
        from dataclasses import asdict
        from app.core.config import Settings
        from app.services.email_service import EmailDeliveryError, send_password_reset_email
        from app.services.password_reset_process import MAX_PROCESS_INPUT_BYTES, DeliveryResult

        raw = sys.stdin.buffer.read(MAX_PROCESS_INPUT_BYTES + 1)
        if len(raw) > MAX_PROCESS_INPUT_BYTES:
            return 1
        value = json.loads(raw)
        settings = Settings(_env_file=None, **value["configuration"])
        try:
            send_password_reset_email(
                value["email"], value["token"], settings=settings,
                idempotency_key=value["idempotency_key"],
            )
            result = DeliveryResult("accepted")
        except EmailDeliveryError as exc:
            result = DeliveryResult(exc.category, exc.exception_class, exc.status_code, exc.reason)
        except Exception as exc:
            result = DeliveryResult("provider_error", type(exc).__name__, reason="child_exception")
        print(json.dumps(asdict(result)), flush=True)
        return 0
    except Exception:
        # Do not write payloads, exceptions or tracebacks to either output stream.
        return 1


if __name__ == "__main__":
    os._exit(main())
