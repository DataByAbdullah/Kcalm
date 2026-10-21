from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.exceptions import APIErrorException
from app.services import tracking_common


@pytest.mark.parametrize("days_ahead", [0, 1, 2])
def test_tracking_date_utc_grace_period(monkeypatch, days_ahead):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return cls(2026, 12, 31, 23, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(tracking_common, "datetime", FrozenDatetime)
    log_date = date(2026, 12, 31) + timedelta(days=days_ahead)

    if days_ahead <= 1:
        tracking_common.validate_record_date(log_date)
    else:
        with pytest.raises(APIErrorException) as error:
            tracking_common.validate_record_date(log_date)
        assert error.value.status_code == 422
        assert error.value.code == "FUTURE_LOG_DATE"
