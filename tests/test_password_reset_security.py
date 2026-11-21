import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import io
import json
import logging
import os
import signal
import sys
import threading
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.core.exceptions import APIErrorException
from app.core.password_reset_logging import PasswordResetFormatter, configure_password_reset_logging
from app.core.security import create_password_reset_token, decode_password_reset_token, hash_password, verify_password
from app.models.password_reset_job import PasswordResetJob as Job
from app.models.rate_limit import RateLimitBucket
from app.models.user import User
from app.services import auth_service
from app.services import password_reset_dispatch as dispatch
from app.services.password_reset_process import DeliveryResult, run_isolated_delivery, parse_delivery_result
from tests.test_auth import api_request, auth_db, register_user, run_async, unique_email


@pytest.fixture
def subject(auth_db):
    db, track = auth_db
    email = track(unique_email("reset-security"))
    assert register_user(email).status_code == 201
    user = db.query(User).filter_by(email=email).one()
    snapshot = (user.id, email, user.password_hash)
    db.rollback()
    return snapshot


def enqueue(email, settings=None):
    with SessionLocal() as db:
        return dispatch.enqueue_password_reset(db, email, settings)


def jobs():
    with SessionLocal() as db:
        return db.scalars(select(Job).order_by(Job.created_at, Job.id)).all()


def test_public_response_does_not_call_provider_for_any_account(subject, monkeypatch):
    _, email, _ = subject
    def forbidden(*args, **kwargs):
        pytest.fail("Provider must not run on the public request path")
    monkeypatch.setattr("app.services.email_service.send_password_reset_email", forbidden)
    inactive = unique_email("inactive")
    from app.services.auth_service import register_user as create_user
    with SessionLocal() as db:
        user = create_user(db, inactive, "StrongPassword123")
        user.is_active = False
        db.commit()
    try:
        for address in (email, unique_email("unknown"), inactive):
            response = run_async(api_request("POST", "/api/v1/auth/forgot-password", json={"email": address}))
            assert response.status_code == 200
            assert response.json() == {"message": "If an account exists for this email, a password reset link has been sent."}
        records = jobs()
        assert len(records) == 3
        assert sum(job.user_id is not None for job in records) == 1
    finally:
        with SessionLocal.begin() as db:
            db.query(User).filter_by(email=inactive).delete()


def test_provider_latency_is_outside_response_and_has_no_checked_out_db_connection(subject):
    _, email, _ = subject
    assert enqueue(email)
    settings = get_settings()
    async def check():
        started, finish = asyncio.Event(), asyncio.Event()
        async def slow(*args, **kwargs):
            assert engine.pool.checkedout() == 0
            started.set()
            await finish.wait()
            return DeliveryResult("accepted")
        task = asyncio.create_task(dispatch.dispatch_once(SessionLocal, settings, deliver=slow))
        await asyncio.wait_for(started.wait(), 3)
        for address in (email, unique_email("unknown-during-slow")):
            response = await asyncio.wait_for(api_request("POST", "/api/v1/auth/forgot-password", json={"email": address}), 2)
            assert response.status_code == 200
            assert not task.done()
        finish.set()
        assert await asyncio.wait_for(task, 3)
    run_async(check())
    assert jobs()[0].status == "accepted"


def test_same_token_has_exactly_one_winner_in_real_postgresql(subject, monkeypatch):
    identity, _, original_hash = subject
    token = create_password_reset_token(identity, original_hash)
    barrier = threading.Barrier(2)
    real_hash = auth_service.hash_password
    def synchronized_hash(value):
        result = real_hash(value)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(auth_service, "hash_password", synchronized_hash)
    passwords = ["ConcurrentPasswordOne123", "ConcurrentPasswordTwo456"]
    def attempt(password):
        with SessionLocal() as db:
            try:
                auth_service.reset_password(db, token, password)
                return 200, password
            except APIErrorException as exc:
                assert exc.code == "INVALID_PASSWORD_RESET_TOKEN"
                assert exc.status_code == 400
                return 400, password
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, passwords))
    assert sorted(code for code, _ in results) == [200, 400]
    winner = next(password for code, password in results if code == 200)
    loser = next(password for code, password in results if code == 400)
    with SessionLocal() as db:
        user = db.get(User, identity)
        assert user.token_version == 1
        assert verify_password(winner, user.password_hash)
        assert not verify_password(loser, user.password_hash)
    with SessionLocal() as db, pytest.raises(APIErrorException) as error:
        auth_service.reset_password(db, token, "ThirdPassword789")
    assert error.value.code == "INVALID_PASSWORD_RESET_TOKEN"


def test_reset_does_not_lose_a_concurrent_logout_increment(subject, monkeypatch):
    identity, _, original_hash = subject
    token = create_password_reset_token(identity, original_hash)
    real_hash = auth_service.hash_password
    def logout_before_update(password):
        replacement = real_hash(password)
        with SessionLocal.begin() as other:
            other.execute(update(User).where(User.id == identity).values(token_version=User.token_version + 1))
        return replacement
    monkeypatch.setattr(auth_service, "hash_password", logout_before_update)
    with SessionLocal() as db:
        auth_service.reset_password(db, token, "AfterConcurrentLogout123")
    with SessionLocal() as db:
        assert db.get(User, identity).token_version == 2


def test_recipient_cooldown_is_shared_and_atomic(subject):
    _, email, _ = subject
    barrier = threading.Barrier(8)
    def attempt(index):
        barrier.wait(timeout=10)
        return enqueue((" " + email.upper() + " ") if index % 2 else email)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(8)))
    assert results.count(True) == 1
    assert len(jobs()) == 1
    with SessionLocal() as db:
        buckets = db.scalars(select(RateLimitBucket)).all()
        assert len(buckets) == 2  # registration IP and recipient digest
        assert all(len(bucket.key_hash) == 64 and email not in bucket.key_hash for bucket in buckets)


def test_distributed_clients_cannot_bypass_recipient_cooldown(subject):
    _, email, _ = subject
    async def check():
        for index in range(8):
            transport = httpx.ASGITransport(app=__import__("app.main", fromlist=["app"]).app, client=(f"192.0.2.{index+1}", 1234))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post("/api/v1/auth/forgot-password", json={"email": email})
                assert response.status_code == 200
    run_async(check())
    assert len(jobs()) == 1


def test_cooldown_expiry_allows_new_work(subject):
    _, email, _ = subject
    assert enqueue(email)
    assert not enqueue(email)
    with SessionLocal.begin() as db:
        db.execute(update(RateLimitBucket).values(expires_at=datetime.now(UTC)-timedelta(seconds=1)))
    assert enqueue(email)
    assert len(jobs()) == 2


def test_global_delivery_budget_is_shared_across_workers(subject):
    _, email, _ = subject
    settings = get_settings().model_copy(update={"rate_limit_password_reset_provider_requests": 1})
    for _ in range(3):
        with SessionLocal.begin() as db:
            db.execute(update(RateLimitBucket).values(expires_at=datetime.now(UTC)-timedelta(seconds=1)))
        assert enqueue(email)
    barrier = threading.Barrier(3)
    def claim(_):
        barrier.wait(timeout=10)
        return dispatch.claim_delivery(SessionLocal, settings)
    with ThreadPoolExecutor(max_workers=3) as executor:
        claimed = list(executor.map(claim, range(3)))
    assert sum(value is not None for value in claimed) == 1
    assert sum(job.status == "pending" for job in jobs()) == 2


def test_global_concurrency_limit_is_shared(subject):
    _, email, _ = subject
    for _ in range(3):
        with SessionLocal.begin() as db:
            db.execute(update(RateLimitBucket).values(expires_at=datetime.now(UTC)-timedelta(seconds=1)))
        assert enqueue(email)
    settings = get_settings().model_copy(update={"password_reset_max_concurrent_deliveries": 1})
    first = dispatch.claim_delivery(SessionLocal, settings)
    assert first is not None
    assert dispatch.claim_delivery(SessionLocal, settings) is None
    assert dispatch.finish_delivery(SessionLocal, settings, first, DeliveryResult("accepted"))
    assert dispatch.claim_delivery(SessionLocal, settings) is not None


def test_expired_lease_recovers_durable_work_and_fences_old_result(subject):
    _, email, _ = subject
    assert enqueue(email)
    settings = get_settings()
    old = dispatch.claim_delivery(SessionLocal, settings)
    with SessionLocal.begin() as db:
        db.execute(update(Job).where(Job.id == old.job_id).values(lease_until=datetime.now(UTC)-timedelta(seconds=1)))
    replacement = dispatch.claim_delivery(SessionLocal, settings)
    assert replacement is not None
    assert old.lease_id != replacement.lease_id
    assert old.token == replacement.token
    assert not dispatch.finish_delivery(SessionLocal, settings, old, DeliveryResult("accepted"))
    assert dispatch.finish_delivery(SessionLocal, settings, replacement, DeliveryResult("accepted"))


@pytest.mark.parametrize("category,status,retry", [
    ("timeout", None, True), ("rate_limited", 429, True), ("provider_error", 503, True),
    ("authentication_failed", 401, False), ("provider_not_configured", None, False), ("provider_error", 403, False),
])
def test_failure_policy_and_safe_logs(subject, caplog, category, status, retry):
    _, email, _ = subject
    assert enqueue(email)
    settings = get_settings()
    snapshot = dispatch.claim_delivery(SessionLocal, settings)
    assert dispatch.finish_delivery(SessionLocal, settings, snapshot, DeliveryResult(category, "ReadTimeout", status))
    assert jobs()[0].status == ("pending" if retry else "failed")
    records = repr([record.__dict__ for record in caplog.records])
    assert email not in records and snapshot.token not in records
    assert all(not record.exc_info for record in caplog.records)


def test_retries_exhaust_and_never_extend_token_expiry(subject):
    _, email, _ = subject
    settings = get_settings().model_copy(update={"password_reset_max_attempts": 2, "password_reset_retry_seconds": 1})
    assert enqueue(email, settings)
    first = dispatch.claim_delivery(SessionLocal, settings)
    initial = decode_password_reset_token(first.token)
    dispatch.finish_delivery(SessionLocal, settings, first, DeliveryResult("timeout"))
    with SessionLocal.begin() as db:
        db.execute(update(Job).values(available_at=datetime.now(UTC)-timedelta(seconds=1)))
    second = dispatch.claim_delivery(SessionLocal, settings)
    assert second.token == first.token
    assert decode_password_reset_token(second.token)["exp"] == initial["exp"]
    dispatch.finish_delivery(SessionLocal, settings, second, DeliveryResult("timeout"))
    assert jobs()[0].status == "failed"


@pytest.mark.parametrize("change", ["password", "inactive", "expired"])
def test_invalidated_jobs_never_deliver(subject, change):
    identity, email, _ = subject
    assert enqueue(email)
    with SessionLocal.begin() as db:
        if change == "password":
            db.execute(update(User).where(User.id == identity).values(password_hash=hash_password("ChangedPassword123")))
        elif change == "inactive":
            db.execute(update(User).where(User.id == identity).values(is_active=False))
        else:
            db.execute(update(Job).values(expires_at=datetime.now(UTC)-timedelta(seconds=1)))
    assert dispatch.claim_delivery(SessionLocal, get_settings()) is None
    assert jobs()[0].status == "discarded"


def test_queue_capacity_and_database_failure_are_monitored(subject, monkeypatch, caplog):
    _, email, _ = subject
    settings = get_settings().model_copy(update={"password_reset_max_pending_jobs": 1})
    assert enqueue(email, settings)
    assert not enqueue(unique_email("queue-full"), settings)
    with SessionLocal() as db:
        def failed(*args, **kwargs):
            raise SQLAlchemyError("private database password and recipient details")
        monkeypatch.setattr(db, "execute", failed)
        assert not dispatch.enqueue_password_reset(db, unique_email("db-failed"), settings)
    assert "queue_capacity" in caplog.text
    assert "private database" not in caplog.text


def test_cancelled_delivery_releases_lease_and_connection(subject):
    _, email, _ = subject
    assert enqueue(email)
    async def check():
        started = asyncio.Event()
        async def blocked(*args, **kwargs):
            assert engine.pool.checkedout() == 0
            started.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(dispatch.dispatch_once(SessionLocal, get_settings(), deliver=blocked))
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    run_async(check())
    job = jobs()[0]
    assert job.status == "pending"
    assert job.lease_id is None and job.lease_until is None


@pytest.mark.parametrize("action", ["timeout", "cancel", "oversized_result", "invalid_result"])
def test_real_subprocess_deadline_and_cleanup(action, monkeypatch):
    settings = get_settings().model_copy(update={"email_delivery_deadline_seconds": 0.3})
    original = asyncio.create_subprocess_exec
    created = []
    async def record(*args, **kwargs):
        process = await original(*args, **kwargs)
        created.append(process)
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", record)
    script = (
        "import sys,time;sys.stdin.buffer.read();"
        + ("print('x'*10000,flush=True);time.sleep(60)" if action == "oversized_result"
           else "print('invalid',flush=True)" if action == "invalid_result" else "time.sleep(60)")
    )
    async def check():
        task = asyncio.create_task(run_isolated_delivery(
            "synthetic@example.com", "synthetic-token", settings, idempotency_key="synthetic-id",
            command=(sys.executable, "-B", "-c", script),
        ))
        if action == "cancel":
            while not created:
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, 3)
            assert result.category == ("timeout" if action == "timeout" else "provider_error")
        assert created and created[0].returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(created[0].pid, 0)
    run_async(check())


def test_child_has_independent_absolute_deadline():
    # Exercise the child even without a parent watchdog. No input means no
    # outbound provider work; SIGALRM must terminate the blocked stdin read.
    import subprocess
    deadline = time.monotonic() + 0.5
    child = subprocess.Popen(
        [sys.executable, "-B", "-m", "app.scripts.password_reset_delivery", str(deadline)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        assert child.wait(timeout=3) == -signal.SIGALRM
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        child.stdin.close()
        child.stdout.close()


def test_child_missing_configuration_fails_without_email():
    settings = get_settings().model_copy(update={"smtp_host": "", "smtp_from_email": ""})
    result = run_async(run_isolated_delivery(
        "synthetic@example.com", "synthetic-token", settings, idempotency_key=str(uuid4()),
    ))
    assert result.category == "provider_not_configured"


def test_expired_snapshot_never_starts_child(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Expired claims must not start a child")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    result = run_async(run_isolated_delivery(
        "synthetic@example.com", "synthetic-token", get_settings(), idempotency_key=str(uuid4()),
        deadline_monotonic=time.monotonic()-1,
    ))
    assert result.category == "timeout"


def test_safe_formatter_and_visible_application_info():
    configure_password_reset_logging()
    logger = logging.getLogger("app.services.password_reset_dispatch")
    assert logger.isEnabledFor(logging.INFO)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(PasswordResetFormatter())
    logger.addHandler(handler)
    try:
        logger.info("private credentials recipient@example.com token-secret", extra={
            "event": "password_reset_email_delivery", "category": "accepted",
        })
    finally:
        logger.removeHandler(handler)
    assert json.loads(output.getvalue()) == {
        "level": "INFO", "event": "password_reset_email_delivery", "category": "accepted",
    }


@pytest.mark.parametrize("content", [
    b"{}", b"not-json", b'{"category":"recipient@example.com"}',
    json.dumps({"category":"accepted","exception_class":None,"status_code":None,"reason":"private"}).encode(),
])
def test_child_result_does_not_forward_arbitrary_diagnostics(content):
    result = parse_delivery_result(content)
    assert result == DeliveryResult("provider_error", reason="invalid_child_result")


def test_queue_delay_and_configuration_change_do_not_extend_expiry(subject):
    _, email, _ = subject
    assert enqueue(email)
    requested_at = datetime.now(UTC) - timedelta(minutes=20)
    expires_at = requested_at + timedelta(minutes=30)
    with SessionLocal.begin() as db:
        db.execute(update(Job).values(created_at=requested_at, expires_at=expires_at))
    snapshot = dispatch.claim_delivery(SessionLocal, get_settings())
    claims = decode_password_reset_token(snapshot.token)
    assert claims["iat"] == int(requested_at.timestamp())
    assert claims["exp"] == int(expires_at.timestamp())
    assert 590 < claims["exp"] - datetime.now(UTC).timestamp() <= 600


def test_global_budget_window_resets_without_dropping_work(subject):
    _, email, _ = subject
    settings = get_settings().model_copy(update={"rate_limit_password_reset_provider_requests": 1})
    for _ in range(2):
        with SessionLocal.begin() as db:
            db.execute(update(RateLimitBucket).values(expires_at=datetime.now(UTC)-timedelta(seconds=1)))
        assert enqueue(email)
    first = dispatch.claim_delivery(SessionLocal, settings)
    assert first is not None
    assert dispatch.claim_delivery(SessionLocal, settings) is None
    with SessionLocal.begin() as db:
        db.execute(update(RateLimitBucket).values(expires_at=datetime.now(UTC)-timedelta(seconds=1)))
    second = dispatch.claim_delivery(SessionLocal, settings)
    assert second is not None and second.job_id != first.job_id


def test_exhausted_crashed_delivery_becomes_terminal(subject):
    _, email, _ = subject
    settings = get_settings().model_copy(update={"password_reset_max_attempts": 1})
    assert enqueue(email)
    assert dispatch.claim_delivery(SessionLocal, settings) is not None
    with SessionLocal.begin() as db:
        db.execute(update(Job).values(lease_until=datetime.now(UTC)-timedelta(seconds=1)))
    assert dispatch.claim_delivery(SessionLocal, settings) is None
    assert jobs()[0].status == "failed"
    assert jobs()[0].failure_category == "attempts_exhausted"


def test_admission_lock_contention_is_bounded_and_monitored(subject, caplog):
    _, email, _ = subject
    with SessionLocal.begin() as blocker:
        blocker.execute(select(func.pg_advisory_xact_lock(dispatch.RESET_GATE)))
        started = time.monotonic()
        assert not enqueue(email)
        assert 0.4 <= time.monotonic() - started < 3
    assert jobs() == []
    assert any(getattr(record, "reason", None) == "persistence_failed" for record in caplog.records)
    assert email not in repr([record.__dict__ for record in caplog.records])


def test_terminal_history_is_pruned_without_touching_pending_jobs(subject):
    _, email, _ = subject
    assert enqueue(email)
    with SessionLocal.begin() as db:
        old = datetime.now(UTC) - timedelta(days=2)
        db.add(Job(status="discarded", attempts=0, created_at=old, updated_at=old,
                   available_at=old, expires_at=old+timedelta(minutes=30)))
    assert len(jobs()) == 2
    assert dispatch.claim_delivery(SessionLocal, get_settings()) is not None
    assert len(jobs()) == 1 and jobs()[0].status == "processing"


def test_deleted_account_removes_queued_work(subject):
    identity, email, _ = subject
    assert enqueue(email)
    with SessionLocal.begin() as db:
        db.query(User).filter_by(id=identity).delete()
    assert jobs() == []
    assert dispatch.claim_delivery(SessionLocal, get_settings()) is None


def test_lifespan_consumes_durable_work_and_disposes_dedicated_pool(subject, monkeypatch):
    _, email, _ = subject
    assert enqueue(email)
    settings = get_settings().model_copy(update={
        "password_reset_dispatcher_enabled": True, "password_reset_poll_seconds": 0.1,
    })
    monkeypatch.setattr(dispatch, "get_settings", lambda: settings)
    real_once = dispatch.dispatch_once
    engines = []
    real_create_engine = dispatch.create_engine
    def record_engine(*args, **kwargs):
        engine = real_create_engine(*args, **kwargs)
        engines.append(engine)
        return engine
    monkeypatch.setattr(dispatch, "create_engine", record_engine)
    async def check():
        delivered = asyncio.Event()
        async def fake_delivery(*args, **kwargs):
            assert engines[0].pool.checkedout() == 0
            assert engine.pool.checkedout() == 0
            delivered.set()
            return DeliveryResult("accepted")
        async def once(factory, settings, **kwargs):
            return await real_once(factory, settings, deliver=fake_delivery, **kwargs)
        monkeypatch.setattr(dispatch, "dispatch_once", once)
        async with dispatch.password_reset_lifespan(None):
            await asyncio.wait_for(delivered.wait(), 3)
            while jobs()[0].status != "accepted":
                await asyncio.sleep(0.01)
        assert engines[0].pool.checkedout() == 0
        assert engines[0].pool.checkedin() == 0  # Disposed on application shutdown.
    run_async(asyncio.wait_for(check(), 5))


def test_dispatch_loop_logs_unexpected_errors_and_keeps_running(monkeypatch, caplog):
    calls = []
    async def broken_then_stop(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TypeError("private recipient token credentials")
        raise asyncio.CancelledError
    monkeypatch.setattr(dispatch, "dispatch_once", broken_then_stop)
    settings = get_settings().model_copy(update={"password_reset_poll_seconds": 0.1})
    with pytest.raises(asyncio.CancelledError):
        run_async(dispatch._dispatch_loop(None, settings, None))
    assert len(calls) == 2
    events = [record for record in caplog.records if getattr(record, "reason", None) == "dispatcher_exception"]
    assert len(events) == 1 and events[0].exception_class == "TypeError"
    assert "private recipient" not in repr([record.__dict__ for record in caplog.records])


def test_process_receives_only_transport_configuration(monkeypatch):
    from app.services.password_reset_process import delivery_configuration
    settings = get_settings()
    configuration = delivery_configuration(settings)
    assert not {"database_url", "jwt_secret", "jwt_algorithm"} & configuration.keys()
    original = asyncio.create_subprocess_exec
    options = []
    async def record(*args, **kwargs):
        options.append((args, kwargs))
        return await original(*args, **kwargs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", record)
    monkeypatch.setenv("PRIVATE_PARENT_SECRET", "must-not-reach-child")
    script = "import sys,json;v=json.load(sys.stdin);print(json.dumps({'category':'accepted','exception_class':None,'status_code':None,'reason':None}))"
    result = run_async(run_isolated_delivery(
        "synthetic@example.com", "synthetic-token", settings, idempotency_key="synthetic-id",
        command=(sys.executable, "-B", "-c", script),
    ))
    assert result.category == "accepted"
    arguments, kwargs = options[0]
    assert "synthetic@example.com" not in repr(arguments)
    assert "synthetic-token" not in repr(arguments)
    assert "PRIVATE_PARENT_SECRET" not in kwargs["env"]
    assert "DATABASE_URL" not in kwargs["env"] and "JWT_SECRET" not in kwargs["env"]


def test_process_input_is_bounded_before_spawn(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Oversized transport input must not start a subprocess")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    settings = get_settings().model_copy(update={"smtp_host": "x" * 65536})
    result = run_async(run_isolated_delivery(
        "synthetic@example.com", "synthetic-token", settings, idempotency_key="synthetic-id",
    ))
    assert result == DeliveryResult("provider_not_configured", reason="configuration_too_large")


def test_cancelled_delivery_still_stops_when_database_release_fails(subject, monkeypatch, caplog):
    _, email, _ = subject
    assert enqueue(email)
    def fail_release(*args):
        raise SQLAlchemyError("private database credentials")
    monkeypatch.setattr(dispatch, "release_delivery", fail_release)
    async def check():
        started = asyncio.Event()
        async def blocked(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(dispatch.dispatch_once(SessionLocal, get_settings(), deliver=blocked))
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
    run_async(check())
    assert jobs()[0].status == "processing" and jobs()[0].lease_until is not None
    assert engine.pool.checkedout() == 0
    assert any(getattr(record, "reason", None) == "lease_release_failed" for record in caplog.records)
    assert "private database" not in repr([record.__dict__ for record in caplog.records])
