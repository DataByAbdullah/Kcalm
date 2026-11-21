"""External delivery is mocked; PostgreSQL is used only by API integration cases."""
import json
import logging
import smtplib
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import decode_password_reset_token
from app.main import create_app
from app.services import email_service
from app.services.email_service import EmailDeliveryError, send_password_reset_email
from app.core.database import SessionLocal
from app.services.password_reset_dispatch import dispatch_once
from app.services.password_reset_process import DeliveryResult
from tests.test_auth import api_request, auth_db, login_user, register_user, run_async, unique_email


REAL_HTTP_CLIENT = httpx.Client
TOKEN = "synthetic-reset-token"
RECIPIENT = "recipient@example.com"
SENDER = "Kcalm <passwords@example.com>"
KEY = "synthetic-resend-key"
PUBLIC_MESSAGE = {"message": "If an account exists for this email, a password reset link has been sent."}


@pytest.fixture
def email_settings(monkeypatch):
    settings = Settings(
        _env_file=None, app_env="test", email_provider="resend",
        resend_api_key=KEY, resend_from_email=SENDER,
        frontend_password_reset_url="https://frontend.example.com/reset-password",
    )
    monkeypatch.setattr(email_service, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def resend_mock(monkeypatch):
    state = {"requests": [], "options": []}

    def handler(request):
        state["requests"].append(request)
        if "exception" in state:
            raise state["exception"]
        return state.get("handler", lambda _: httpx.Response(200, json={"id": "synthetic-message-id"}))(request)

    def client(**kwargs):
        state["options"].append(kwargs)
        return REAL_HTTP_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(email_service.httpx, "Client", client)
    return state


def forgot(email):
    return run_async(api_request("POST", "/api/v1/auth/forgot-password", json={"email": email}))


def dispatch_mocked_email(settings):
    """Exercise durable dispatch using this module's mocked transports only."""
    async def deliver(email, token, settings, **kwargs):
        try:
            send_password_reset_email(email, token, settings=settings, idempotency_key=kwargs["idempotency_key"])
        except EmailDeliveryError as exc:
            return DeliveryResult(exc.category, exc.exception_class, exc.status_code, exc.reason)
        return DeliveryResult("accepted")
    return run_async(dispatch_once(SessionLocal, settings, deliver=deliver))


def assert_safe_logs(caplog, *private_values):
    records = repr([record.__dict__ for record in caplog.records])
    for value in private_values:
        assert value not in records
    assert all(not record.exc_info for record in caplog.records)


def test_resend_submission_contract_and_safe_success_logging(email_settings, resend_mock, caplog):
    caplog.set_level(logging.INFO)
    send_password_reset_email(RECIPIENT, TOKEN)
    assert len(resend_mock["requests"]) == 1
    request = resend_mock["requests"][0]
    assert str(request.url) == "https://api.resend.com/emails"
    assert request.method == "POST"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Accept-Encoding"] == "identity"
    payload = json.loads(request.content)
    assert payload["from"] == SENDER
    assert payload["to"] == [RECIPIENT]
    assert payload["subject"] == "Reset your Kcalm password"
    link = email_settings.frontend_password_reset_url + "?token=" + TOKEN
    assert link in payload["text"]
    options = resend_mock["options"][0]
    assert options["follow_redirects"] is False
    assert options["trust_env"] is False
    assert options["timeout"].connect == 5
    assert options["timeout"].read == 10
    events = [r for r in caplog.records if getattr(r, "event", None) == "password_reset_email_delivery"]
    assert len(events) == 1
    assert events[0].category == "accepted"
    assert_safe_logs(caplog, RECIPIENT, SENDER, KEY, TOKEN, link)


def test_reset_link_preserves_query_and_replaces_old_token(email_settings, resend_mock):
    email_settings.frontend_password_reset_url += "?source=app&token=obsolete&empty="
    send_password_reset_email(RECIPIENT, "token+with/reserved=characters")
    text = json.loads(resend_mock["requests"][0].content)["text"]
    link = text.split("using this link:\n", 1)[1].splitlines()[0]
    assert parse_qs(urlsplit(link).query, keep_blank_values=True) == {
        "source": ["app"], "empty": [""], "token": ["token+with/reserved=characters"],
    }


@pytest.mark.parametrize("field,value", [
    ("resend_api_key", ""), ("resend_api_key", " "), ("resend_api_key", "bad\nkey"),
    ("resend_api_key", "non-ascii-\u00e9"), ("resend_from_email", ""),
    ("resend_from_email", "invalid-address"), ("resend_from_email", "a@example.com\nBcc: b@example.com"),
])
def test_invalid_resend_configuration_never_contacts_provider(email_settings, resend_mock, field, value):
    from pydantic import SecretStr
    setattr(email_settings, field, SecretStr(value) if field == "resend_api_key" else value)
    with pytest.raises(EmailDeliveryError) as error:
        send_password_reset_email(RECIPIENT, TOKEN)
    assert error.value.category == "provider_not_configured"
    assert resend_mock["requests"] == []
    assert resend_mock["options"] == []


@pytest.mark.parametrize("url", [
    "", " ", "not-a-url", "ftp://frontend.example.com/reset", "http://frontend.example.com/reset",
    "https://user:password@frontend.example.com/reset", "https://frontend.example.com/reset#fragment",
    "https://frontend.example.com:invalid/reset", "https://frontend.example.com/reset\ninjected",
])
def test_missing_or_unsafe_frontend_url_prevents_delivery(email_settings, resend_mock, url):
    email_settings.frontend_password_reset_url = url
    with pytest.raises(EmailDeliveryError) as error:
        send_password_reset_email(RECIPIENT, TOKEN)
    assert error.value.category == "provider_not_configured"
    assert resend_mock["requests"] == []


@pytest.mark.parametrize("url", ["http://localhost:3000/reset-password", "https://localhost/reset", "https://127.0.0.1/reset"])
def test_production_never_sends_localhost_reset_link(email_settings, resend_mock, url):
    email_settings.app_env = "production"
    email_settings.frontend_password_reset_url = url
    with pytest.raises(EmailDeliveryError):
        send_password_reset_email(RECIPIENT, TOKEN)
    assert resend_mock["requests"] == []


def test_development_localhost_url_stays_supported(email_settings, resend_mock):
    email_settings.frontend_password_reset_url = "http://localhost:3000/reset-password"
    send_password_reset_email(RECIPIENT, TOKEN)
    assert "http://localhost:3000/reset-password?token=" in json.loads(resend_mock["requests"][0].content)["text"]


@pytest.mark.parametrize("status,category", [
    (400, "provider_error"), (401, "authentication_failed"), (403, "provider_error"),
    (422, "provider_error"), (429, "rate_limited"), (500, "provider_error"),
    (503, "provider_error"), (302, "provider_error"),
])
def test_resend_http_errors_are_sanitized(email_settings, resend_mock, status, category):
    resend_mock["handler"] = lambda _: httpx.Response(
        status, json={"message": f"private provider details {KEY} {RECIPIENT} {TOKEN}"},
        headers={"Location": "https://untrusted.example.com/"},
    )
    with pytest.raises(EmailDeliveryError) as error:
        send_password_reset_email(RECIPIENT, TOKEN)
    assert error.value.category == category
    assert error.value.status_code == status
    assert str(error.value) == category
    assert len(resend_mock["requests"]) == 1


@pytest.mark.parametrize("exception,category", [
    (httpx.ConnectTimeout, "timeout"), (httpx.ReadTimeout, "timeout"),
    (httpx.WriteTimeout, "timeout"), (httpx.PoolTimeout, "timeout"),
    (httpx.ConnectError, "provider_error"), (httpx.ReadError, "provider_error"),
    (httpx.RemoteProtocolError, "provider_error"), (OSError, "provider_error"),
])
def test_resend_transport_failures_are_sanitized(email_settings, resend_mock, exception, category):
    resend_mock["exception"] = exception(f"private {RECIPIENT} {KEY} {TOKEN}")
    with pytest.raises(EmailDeliveryError) as error:
        send_password_reset_email(RECIPIENT, TOKEN)
    assert error.value.category == category
    assert error.value.exception_class == exception.__name__
    assert str(error.value) == category
    assert error.value.__suppress_context__ is True
    assert len(resend_mock["requests"]) == 1


@pytest.mark.parametrize("body", [b"", b"not json", b"null", b"[]", b"{}", b'{"id":null}', b'{"id":""}', b"x" * 8193,
                                  b"[" * 2000 + b"]" * 2000])
def test_invalid_success_response_is_not_reported_as_accepted(email_settings, resend_mock, caplog, body):
    caplog.set_level(logging.INFO)
    resend_mock["handler"] = lambda _: httpx.Response(200, content=body)
    with pytest.raises(EmailDeliveryError) as error:
        send_password_reset_email(RECIPIENT, TOKEN)
    assert error.value.category == "provider_error"
    assert "Password reset email submitted." not in caplog.text


def test_compressed_response_is_rejected_without_decompression(email_settings, resend_mock):
    import gzip
    class BombStream(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail("Compressed response must not be read")
            yield gzip.compress(b"x" * 1_000_000)
    resend_mock["handler"] = lambda _: httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=BombStream())
    with pytest.raises(EmailDeliveryError):
        send_password_reset_email(RECIPIENT, TOKEN)


def test_provider_error_body_is_never_read(email_settings, resend_mock):
    class PrivateStream(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail("Provider error body must not be read")
            yield b"private error"
    resend_mock["handler"] = lambda _: httpx.Response(401, stream=PrivateStream())
    with pytest.raises(EmailDeliveryError) as error:
        send_password_reset_email(RECIPIENT, TOKEN)
    assert error.value.category == "authentication_failed"


@pytest.mark.parametrize("failure", ["missing_key", "missing_url", "unauthorized", "forbidden", "rate_limited", "server_error", "timeout", "network"])
def test_forgot_password_failures_preserve_public_contract_and_safe_logs(
    auth_db, email_settings, resend_mock, monkeypatch, caplog, failure,
):
    _, track = auth_db
    email = track(unique_email("resend-failure"))
    assert register_user(email).status_code == 201
    expected = {
        "missing_key": "provider_not_configured", "missing_url": "provider_not_configured",
        "unauthorized": "authentication_failed", "forbidden": "provider_error",
        "rate_limited": "rate_limited", "server_error": "provider_error",
        "timeout": "timeout", "network": "provider_error",
    }[failure]
    if failure == "missing_key":
        from pydantic import SecretStr
        email_settings.resend_api_key = SecretStr("")
    elif failure == "missing_url":
        email_settings.frontend_password_reset_url = ""
    elif failure in {"timeout", "network"}:
        exception = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        resend_mock["exception"] = exception(f"private provider failure {KEY} {email}")
    else:
        status = {"unauthorized": 401, "forbidden": 403, "rate_limited": 429, "server_error": 503}[failure]
        resend_mock["handler"] = lambda _: httpx.Response(status, json={"message": f"private provider failure {KEY} {email}"})
    caplog.set_level(logging.INFO)
    known = forgot(email)
    unknown = forgot(unique_email("not-registered"))
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == PUBLIC_MESSAGE
    assert resend_mock["requests"] == []
    assert dispatch_mocked_email(email_settings)
    failures = [r for r in caplog.records if getattr(r, "event", None) == "password_reset_email_delivery"
                and r.category == expected]
    assert len(failures) == 1
    assert failures[0].category == expected
    if failure in {"timeout", "network"}:
        assert failures[0].exception_class == type(resend_mock["exception"]).__name__
    assert "Password reset email submitted." not in caplog.text
    if resend_mock["requests"]:
        text = json.loads(resend_mock["requests"][0].content)["text"]
        token = parse_qs(urlsplit(text.split("using this link:\n", 1)[1].splitlines()[0]).query)["token"][0]
        assert_safe_logs(caplog, email, KEY, token, "private provider failure")
    else:
        assert_safe_logs(caplog, email, KEY)


def test_unknown_and_inactive_users_never_submit_email(auth_db, email_settings, resend_mock):
    from app.models.user import User
    db, track = auth_db
    email = track(unique_email("inactive-resend"))
    assert register_user(email).status_code == 201
    user = db.query(User).filter_by(email=email).one()
    user.is_active = False
    db.commit()
    for address in (email, unique_email("unknown-resend")):
        response = forgot(address)
        assert response.status_code == 200
        assert response.json() == PUBLIC_MESSAGE
    assert not dispatch_mocked_email(email_settings)
    assert resend_mock["requests"] == []


def test_resend_flow_token_expiry_and_existing_reset_endpoint(auth_db, email_settings, resend_mock):
    db, track = auth_db
    email = track(unique_email("resend-reset"))
    assert register_user(email).status_code == 201
    response = forgot(email)
    assert response.status_code == 200
    assert dispatch_mocked_email(email_settings)
    payload = json.loads(resend_mock["requests"][0].content)
    assert payload["to"] == [email]
    link = payload["text"].split("using this link:\n", 1)[1].splitlines()[0]
    token = parse_qs(urlsplit(link).query)["token"][0]
    claims = decode_password_reset_token(token)
    from app.models.user import User
    user = db.query(User).filter_by(email=email).one()
    assert claims["sub"] == str(user.id)
    from app.core.config import get_settings
    remaining = claims["exp"] - datetime.now(UTC).timestamp()
    assert get_settings().password_reset_token_expire_minutes * 60 - 10 < remaining <= get_settings().password_reset_token_expire_minutes * 60
    new_password = "NewStrongPassword456"
    result = run_async(api_request("POST", "/api/v1/auth/reset-password", json={"token": token, "new_password": new_password}))
    assert result.status_code == 200
    assert login_user(email, new_password).status_code == 200
    assert login_user(email, "StrongPassword123").status_code == 401
    reused = run_async(api_request("POST", "/api/v1/auth/reset-password", json={"token": token, "new_password": "OtherStrongPassword789"}))
    assert reused.status_code == 400


def test_forgot_password_default_quota_unchanged(auth_db, email_settings, resend_mock):
    from app.core.config import get_settings
    from app.models.rate_limit import RateLimitBucket
    db, track = auth_db
    assert get_settings().rate_limit_forgot_password_requests == 5
    assert get_settings().rate_limit_forgot_password_window_seconds == 300
    email = track(unique_email("resend-quota"))
    assert register_user(email).status_code == 201
    for _ in range(5):
        assert forgot(email).status_code == 200
    denied = forgot(email)
    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert 1 <= int(denied.headers["Retry-After"]) <= 300
    bucket = db.query(RateLimitBucket).filter_by(request_count=5).one()
    assert bucket.request_count == 5
    assert resend_mock["requests"] == []
    assert dispatch_mocked_email(email_settings)
    assert not dispatch_mocked_email(email_settings)
    assert len(resend_mock["requests"]) == 1  # Recipient cooldown; IP quota remains five.


@pytest.fixture
def smtp_mock(monkeypatch, email_settings):
    email_settings.email_provider = "smtp"
    email_settings.smtp_host = "smtp.example.com"
    email_settings.smtp_from_email = SENDER
    email_settings.smtp_username = "synthetic-smtp-user"
    email_settings.smtp_password = "synthetic-smtp-password"
    smtp = Mock()
    smtp.send_message.return_value = {}
    constructor = MagicMock()
    constructor.return_value.__enter__.return_value = smtp
    monkeypatch.setattr(email_service.smtplib, "SMTP", constructor)
    return constructor, smtp


@pytest.mark.parametrize("tls,authenticated", [(True, True), (False, False)])
def test_smtp_backward_compatibility(email_settings, smtp_mock, resend_mock, tls, authenticated):
    constructor, smtp = smtp_mock
    email_settings.smtp_use_tls = tls
    if not authenticated:
        email_settings.smtp_username = email_settings.smtp_password = ""
    send_password_reset_email(RECIPIENT, TOKEN)
    constructor.assert_called_once_with("smtp.example.com", 587, timeout=10)
    assert smtp.starttls.call_count == int(tls)
    assert smtp.login.call_count == int(authenticated)
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == RECIPIENT
    assert message["From"] == SENDER
    assert "?token=" + TOKEN in message.get_content()
    assert resend_mock["requests"] == []


def test_resend_retries_use_a_stable_idempotency_key(email_settings, resend_mock):
    for _ in range(2):
        send_password_reset_email(RECIPIENT, TOKEN, idempotency_key="synthetic-job-id")
    assert [request.headers["Idempotency-Key"] for request in resend_mock["requests"]] == ["synthetic-job-id"] * 2
    assert resend_mock["requests"][0].content == resend_mock["requests"][1].content


def test_smtp_retries_use_a_stable_message_id(email_settings, smtp_mock):
    _, smtp = smtp_mock
    for _ in range(2):
        send_password_reset_email(RECIPIENT, TOKEN, idempotency_key="synthetic-job-id")
    messages = [call.args[0] for call in smtp.send_message.call_args_list]
    assert len(messages) == 2
    assert messages[0]["Message-ID"] == messages[1]["Message-ID"]


@pytest.mark.parametrize("failure,category", [
    (smtplib.SMTPAuthenticationError(535, b"private auth failure"), "authentication_failed"),
    (smtplib.SMTPRecipientsRefused({RECIPIENT: (550, b"private recipient")}), "provider_error"),
    (TimeoutError("private timeout"), "timeout"),
    (OSError("private network"), "provider_error"),
])
def test_smtp_failures_are_sanitized(email_settings, smtp_mock, failure, category):
    smtp_mock[1].send_message.side_effect = failure
    with pytest.raises(EmailDeliveryError) as error:
        send_password_reset_email(RECIPIENT, TOKEN)
    assert error.value.category == category
    assert error.value.exception_class == type(failure).__name__
    assert str(error.value) == category


def test_smtp_refusal_mapping_is_failure(email_settings, smtp_mock):
    smtp_mock[1].send_message.return_value = {RECIPIENT: (550, b"private refusal")}
    with pytest.raises(EmailDeliveryError):
        send_password_reset_email(RECIPIENT, TOKEN)


@pytest.mark.parametrize("missing", ["smtp_host", "smtp_from_email", "smtp_password"])
def test_smtp_unconfigured_is_explicit_failure(email_settings, smtp_mock, missing):
    setattr(email_settings, missing, "")
    with pytest.raises(EmailDeliveryError) as error:
        send_password_reset_email(RECIPIENT, TOKEN)
    assert error.value.category == "provider_not_configured"
    smtp_mock[0].assert_not_called()


@pytest.mark.parametrize("missing", ["resend_api_key", "resend_from_email", "frontend_password_reset_url"])
def test_production_startup_configuration_warning_is_safe(email_settings, monkeypatch, caplog, missing):
    from pydantic import SecretStr
    email_settings.app_env = "production"
    email_settings.jwt_secret = "isolated-test-secret-with-at-least-32-bytes"
    setattr(email_settings, missing, SecretStr("") if missing == "resend_api_key" else "")
    monkeypatch.setattr("app.main.get_settings", lambda: email_settings)
    create_app()
    events = [r for r in caplog.records if getattr(r, "event", None) == "password_reset_email_configuration"]
    assert len(events) == 1
    assert events[0].category == "provider_not_configured"
    assert_safe_logs(caplog, KEY, SENDER)


def test_configured_production_has_no_configuration_warning(email_settings, monkeypatch, caplog):
    email_settings.app_env = "production"
    email_settings.jwt_secret = "isolated-test-secret-with-at-least-32-bytes"
    monkeypatch.setattr("app.main.get_settings", lambda: email_settings)
    create_app()
    assert not any(getattr(r, "event", None) == "password_reset_email_configuration" for r in caplog.records)


@pytest.mark.parametrize("values", [
    {"email_provider": "unknown"}, {"email_timeout_seconds": 0},
    {"email_timeout_seconds": 61}, {"email_connect_timeout_seconds": -1},
    {"email_connect_timeout_seconds": 31},
])
def test_email_settings_reject_invalid_values(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_resend_key_is_redacted_from_settings(email_settings):
    assert KEY not in repr(email_settings)
    assert KEY not in email_settings.model_dump_json()
