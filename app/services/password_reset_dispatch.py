"""PostgreSQL-coordinated password-reset outbox and bounded lifecycle dispatcher."""
import asyncio
import hmac
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.rate_limits import try_consume_rate_limit
from app.core.security import create_password_reset_token, password_reset_fingerprint
from app.models.password_reset_job import PasswordResetJob as Job
from app.models.user import User
from app.services.password_reset_process import DeliveryResult, run_isolated_delivery


logger = logging.getLogger(__name__)
RESET_GATE = 714640526
TERMINAL = ("accepted", "discarded", "failed")


def delivery_event(category, *, provider=None, exception_class=None, status_code=None, reason=None):
    level = logging.INFO if category in {"queued", "accepted", "suppressed", "discarded"} else logging.WARNING
    logger.log(level, "Password reset dispatch event. category=%s reason=%s", category, reason, extra={
        "event": "password_reset_email_delivery", "category": category,
        "provider": provider, "exception_class": exception_class,
        "status_code": status_code, "reason": reason,
    })


def _timeouts(db):
    db.execute(text("SET LOCAL lock_timeout = '500ms'"))
    db.execute(text("SET LOCAL statement_timeout = '2000ms'"))


def _gate(db):
    # Admission and claims acquire the advisory gate before quota/job rows.
    # Completion only locks its own job, and never waits for the gate or quota.
    # Never hold the gate, a job lock, or a database connection during delivery.
    _timeouts(db)
    db.execute(select(func.pg_advisory_xact_lock(RESET_GATE)))


def _prune(db, now):
    # Bound terminal history independently of incoming unknown-address traffic.
    old = select(Job.id).where(Job.status.in_(TERMINAL)).order_by(
        Job.updated_at.desc(), Job.id,
    ).offset(1000).limit(100)
    db.execute(delete(Job).where(Job.id.in_(old)))
    expired = select(Job.id).where(
        Job.status.in_(TERMINAL), Job.updated_at < now - timedelta(days=1),
    ).limit(100)
    db.execute(delete(Job).where(Job.id.in_(expired)))


def enqueue_password_reset(db: Session, email: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    normalized = email.strip().lower()
    try:
        _gate(db)
        now = db.scalar(select(func.clock_timestamp()))
        if not try_consume_rate_limit(db, "password_reset_recipient", normalized, settings):
            db.commit()
            delivery_event("suppressed", reason="recipient_cooldown")
            return False
        count = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(("pending", "processing"))))
        if count >= settings.password_reset_max_pending_jobs:
            db.commit()
            delivery_event("queue_unavailable", reason="queue_capacity")
            return False
        _prune(db, now)
        subject = db.execute(select(User.id, User.password_hash, User.is_active).where(User.email == normalized)).one_or_none()
        active = subject is not None and subject.is_active
        # Unknown/inactive recipients get the same durable insert and public reply.
        # No recipient address, token, or password hash is persisted in the outbox.
        db.add(Job(
            user_id=subject.id if active else None,
            password_fingerprint=password_reset_fingerprint(subject.password_hash) if active else None,
            created_at=now, updated_at=now, status="pending", attempts=0,
            available_at=now, expires_at=now + timedelta(minutes=settings.password_reset_token_expire_minutes),
        ))
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        delivery_event("queue_unavailable", exception_class=type(exc).__name__, reason="persistence_failed")
        return False
    delivery_event("queued")
    return True


@dataclass(frozen=True, repr=False)
class ClaimedDelivery:
    job_id: UUID
    lease_id: UUID
    email: str
    token: str
    deadline_monotonic: float


def claim_delivery(factory, settings: Settings) -> ClaimedDelivery | None:
    with factory.begin() as db:
        _gate(db)
        now = db.scalar(select(func.clock_timestamp()))
        # A child has its own kernel-enforced deadline, shorter than this lease,
        # even if its parent dies. Recover only work whose lease has elapsed.
        db.execute(update(Job).where(
            Job.status.in_(("pending", "processing")), Job.expires_at <= now,
            (Job.status == "pending") | (Job.lease_until <= now),
        ).values(status="discarded", lease_id=None, lease_until=None, failure_category="expired"))
        stale = (Job.status == "processing") & (Job.lease_until <= now)
        db.execute(update(Job).where(stale, Job.attempts >= settings.password_reset_max_attempts).values(
            status="failed", lease_id=None, lease_until=None, failure_category="attempts_exhausted",
        ))
        db.execute(update(Job).where(stale).values(
            status="pending", lease_id=None, lease_until=None, available_at=now,
        ))
        _prune(db, now)
        active = db.scalar(select(func.count()).select_from(Job).where(Job.status == "processing"))
        if active >= settings.password_reset_max_concurrent_deliveries:
            return None
        # Drain a bounded batch of dummy/stale jobs without starting subprocesses.
        for _ in range(16):
            job = db.scalar(select(Job).where(
                Job.status == "pending", Job.available_at <= now,
            ).order_by(Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1))
            if job is None:
                return None
            subject = None if job.user_id is None else db.execute(
                select(User.id, User.email, User.password_hash, User.is_active).where(User.id == job.user_id)
            ).one_or_none()
            valid = subject is not None and subject.is_active and hmac.compare_digest(
                job.password_fingerprint, password_reset_fingerprint(subject.password_hash),
            )
            if not valid:
                job.status, job.failure_category = "discarded", "subject_changed"
                db.flush()
                continue
            if job.attempts >= settings.password_reset_max_attempts:
                job.status, job.failure_category = "failed", "attempts_exhausted"
                db.flush()
                continue
            if not try_consume_rate_limit(db, "password_reset_provider", "all_deliveries", settings):
                return None
            now = db.scalar(select(func.clock_timestamp()))
            job.status, job.lease_id = "processing", uuid4()
            job.lease_until = now + timedelta(seconds=settings.email_delivery_deadline_seconds + 10)
            job.attempts += 1
            token = create_password_reset_token(
                subject.id, subject.password_hash, issued_at=job.created_at, expires_at=job.expires_at,
            )
            snapshot = ClaimedDelivery(job.id, job.lease_id, subject.email, token,
                                       time.monotonic() + settings.email_delivery_deadline_seconds)
            db.flush()
            return snapshot
    return None


def finish_delivery(factory, settings, snapshot, result: DeliveryResult):
    with factory.begin() as db:
        _timeouts(db)
        now = db.scalar(select(func.clock_timestamp()))
        job = db.scalar(select(Job).where(
            Job.id == snapshot.job_id, Job.lease_id == snapshot.lease_id,
            Job.status == "processing",
        ).with_for_update())
        if job is None:
            delivery_event("stale_result", reason="lease_changed")
            return False
        retryable = result.category in {"timeout", "rate_limited"} or (
            result.category == "provider_error" and (result.status_code is None or result.status_code >= 500)
        )
        retry_at = now + timedelta(seconds=settings.password_reset_retry_seconds * 2 ** max(0, job.attempts - 1))
        if result.category == "accepted":
            job.status, job.failure_category = "accepted", None
        elif retryable and job.attempts < settings.password_reset_max_attempts and retry_at < job.expires_at:
            job.status, job.available_at, job.failure_category = "pending", retry_at, result.category
        else:
            job.status, job.failure_category = "failed", result.category
        job.lease_id = job.lease_until = None
    delivery_event(
        result.category, provider=settings.email_provider, exception_class=result.exception_class,
        status_code=result.status_code, reason=result.reason,
    )
    return True


def release_delivery(factory, snapshot):
    with factory.begin() as db:
        _timeouts(db)
        db.execute(update(Job).where(
            Job.id == snapshot.job_id, Job.lease_id == snapshot.lease_id, Job.status == "processing",
        ).values(status="pending", lease_id=None, lease_until=None, available_at=func.now()))


async def dispatch_once(factory, settings, *, deliver=run_isolated_delivery, executor=None):
    loop = asyncio.get_running_loop()
    snapshot = await loop.run_in_executor(executor, claim_delivery, factory, settings)
    if snapshot is None:
        return False
    try:
        result = await deliver(snapshot.email, snapshot.token, settings, idempotency_key=str(snapshot.job_id),
                               deadline_monotonic=snapshot.deadline_monotonic)
        await loop.run_in_executor(executor, finish_delivery, factory, settings, snapshot, result)
    except asyncio.CancelledError:
        # Child cleanup completes in run_isolated_delivery before cancellation
        # reaches here. A crash during this write is still covered by the lease.
        try:
            await asyncio.shield(loop.run_in_executor(executor, release_delivery, factory, snapshot))
        except SQLAlchemyError as exc:
            delivery_event("queue_unavailable", exception_class=type(exc).__name__, reason="lease_release_failed")
        # A failed release must not replace cancellation and keep the loop alive.
        raise
    return True


async def _dispatch_loop(factory, settings, executor):
    while True:
        try:
            worked = await dispatch_once(factory, settings, executor=executor)
        except SQLAlchemyError as exc:
            delivery_event("queue_unavailable", exception_class=type(exc).__name__, reason="dispatcher_database")
            worked = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not leak provider details or let one failed iteration silently
            # stop delivery. Unfinished work remains recoverable through its lease.
            delivery_event("provider_error", exception_class=type(exc).__name__, reason="dispatcher_exception")
            worked = False
        if not worked:
            await asyncio.sleep(settings.password_reset_poll_seconds)


@asynccontextmanager
async def password_reset_lifespan(app):
    settings = get_settings()
    if not settings.password_reset_dispatcher_enabled:
        delivery_event("dispatcher_disabled", reason="pending_work_requires_consumer")
        yield
        return
    # Dedicated, small database pool and executor; provider latency consumes neither.
    engine = create_engine(
        settings.database_url, pool_size=1, max_overflow=0, pool_timeout=1,
        pool_pre_ping=True, isolation_level="READ COMMITTED",
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000 -c lock_timeout=500"},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="password-reset-db")
    task = asyncio.create_task(_dispatch_loop(factory, settings, executor), name="password-reset-dispatcher")
    try:
        yield
    finally:
        task.cancel()
        try:
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            try:
                await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
            finally:
                engine.dispose()
