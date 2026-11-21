"""Small allowlisted formatter for password-reset operational events."""
import json
import logging


SAFE_FIELDS = ("event", "provider", "category", "exception_class", "status_code", "reason")


class PasswordResetFormatter(logging.Formatter):
    def format(self, record):
        # Ignore arbitrary messages, exception text, arguments and local variables.
        fields = {name: getattr(record, name) for name in SAFE_FIELDS if getattr(record, name, None) is not None}
        return json.dumps({"level": record.levelname, **fields}, separators=(",", ":"))


def configure_password_reset_logging():
    for name in ("app.services.email_service", "app.services.password_reset_dispatch"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not any(getattr(handler, "_password_reset_safe", False) for handler in logger.handlers):
            handler = logging.StreamHandler()
            handler._password_reset_safe = True
            handler.setFormatter(PasswordResetFormatter())
            logger.addHandler(handler)
