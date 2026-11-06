from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime

import pandas as pd
import pytest

from nse_swing_bot.market_data.checkpoints import JsonChunkCheckpointStore
from nse_swing_bot.market_data.kite_adapter import KiteMarketDataAdapter
from nse_swing_bot.market_data.parquet_store import ParquetCandleStore
from nse_swing_bot.market_data.quarantine import DataQualityQuarantine
from nse_swing_bot.market_data.request_control import (
    KiteRequestExecutor,
    KiteRequestPacer,
    RetryPolicy,
)
from nse_swing_bot.market_data.service import MarketDataService
from nse_swing_bot.market_data.validation import CandleDataError


def no_wait_executor(sleeps: list[float] | None = None) -> KiteRequestExecutor:
    return KiteRequestExecutor(
        pacer=KiteRequestPacer(sleep=lambda _: None, monotonic=lambda: 0.0),
        policy=RetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=4),
        sleep=(sleeps.append if sleeps is not None else (lambda _: None)),
    )


def test_pacer_applies_endpoint_specific_spacing() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    pacer = KiteRequestPacer(sleep=sleep, monotonic=lambda: now[0])
    pacer.wait("historical")
    pacer.wait("historical")
    pacer.wait("other")
    pacer.wait("other")
    pacer.wait("quote")
    pacer.wait("quote")

    assert sleeps == pytest.approx([1 / 3, 0.1, 1.0])


def test_retry_honors_retry_after_for_429_and_stops_after_limit() -> None:
    sleeps: list[float] = []

    class RateLimitError(Exception):
        status_code = 429
        response = type("Response", (), {"headers": {"Retry-After": "2.5"}})()

    calls = [0]

    def operation() -> str:
        calls[0] += 1
        if calls[0] == 1:
            raise RateLimitError("slow down")
        return "ok"

    executor = no_wait_executor(sleeps)
    assert executor.call("historical", operation) == "ok"
    assert calls[0] == 2
    assert sleeps == [2.5]


def test_non_transient_client_errors_are_not_retried() -> None:
    calls = [0]

    class BadRequest(Exception):
        status_code = 400

    def operation() -> None:
        calls[0] += 1
        raise BadRequest("bad input")

    with pytest.raises(BadRequest):
        no_wait_executor().call("historical", operation)
    assert calls[0] == 1


def test_checkpoint_store_round_trips_records_and_rejects_mismatched_key(tmp_path) -> None:
    store = JsonChunkCheckpointStore(tmp_path)
    records = [{"date": "2026-01-01", "close": 123.4}]
    store.save(123, date(2026, 1, 1), date(2026, 1, 2), 2, records)
    assert store.load(123, date(2026, 1, 1), date(2026, 1, 2), 2) == records
    assert store.load(123, date(2026, 1, 1), date(2026, 1, 3), 2) is None


def test_adapter_resumes_completed_chunks_without_refetching(tmp_path) -> None:
    class FakeKiteClient:
        def __init__(self) -> None:
            self.calls: list[date] = []

        def instruments(self, exchange=None):
            return []

        def historical_data(
            self, instrument_token, from_date, to_date, interval,
            continuous=False, oi=False,
        ):
            self.calls.append(from_date.date())
            return [{
                "date": from_date,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 100.0,
            }]

    client = FakeKiteClient()
    checkpoints = JsonChunkCheckpointStore(tmp_path / "checkpoints")
    adapter = KiteMarketDataAdapter(
        client, request_executor=no_wait_executor(), checkpoint_store=checkpoints
    )
    first = adapter.fetch_daily_candles(
        123, date(2026, 1, 1), date(2026, 1, 4), chunk_days=2
    )
    second = adapter.fetch_daily_candles(
        123, date(2026, 1, 1), date(2026, 1, 4), chunk_days=2
    )

    assert len(client.calls) == 2
    assert len(first) == len(second) == 2
    assert first.equals(second)


def test_quarantine_writes_raw_payload_and_reason(tmp_path) -> None:
    quarantine = DataQualityQuarantine(tmp_path)
    candles = pd.DataFrame(
        {"open": [10.0], "high": [8.0], "low": [9.0], "close": [10.0], "volume": [1.0]},
        index=pd.to_datetime(["2026-01-01"]),
    )
    path = quarantine.store(
        "NSE:ABC", date(2026, 1, 1), date(2026, 1, 1),
        "high is inconsistent", candles,
        captured_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert path.exists()
    payload = path.read_text(encoding="utf-8")
    assert "high is inconsistent" in payload
    assert '"symbol": "NSE:ABC"' in payload


def test_adapter_resumes_after_later_chunk_failure(tmp_path) -> None:
    class BadRequest(Exception):
        status_code = 400

    class FakeKiteClient:
        def __init__(self) -> None:
            self.calls: list[date] = []
            self.fail_second_chunk = True

        def instruments(self, exchange=None):
            return []

        def historical_data(
            self, instrument_token, from_date, to_date, interval,
            continuous=False, oi=False,
        ):
            self.calls.append(from_date.date())
            if from_date.date() == date(2026, 1, 3) and self.fail_second_chunk:
                raise BadRequest("invalid request")
            return [{
                "date": from_date,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 100.0,
            }]

    client = FakeKiteClient()
    adapter = KiteMarketDataAdapter(
        client,
        request_executor=no_wait_executor(),
        checkpoint_store=JsonChunkCheckpointStore(tmp_path / "checkpoints"),
    )
    with pytest.raises(BadRequest):
        adapter.fetch_daily_candles(
            123, date(2026, 1, 1), date(2026, 1, 4), chunk_days=2
        )

    client.fail_second_chunk = False
    resumed = adapter.fetch_daily_candles(
        123, date(2026, 1, 1), date(2026, 1, 4), chunk_days=2
    )
    assert client.calls == [
        date(2026, 1, 1),
        date(2026, 1, 3),
        date(2026, 1, 3),
    ]
    assert len(resumed) == 2


def test_market_data_service_quarantines_invalid_candles(tmp_path) -> None:
    class InvalidAdapter:
        def fetch_daily_candles(
            self, instrument_token, start, end, chunk_days=365, expected_sessions=None
        ):
            return pd.DataFrame(
                {
                    "open": [10.0],
                    "high": [8.0],
                    "low": [9.0],
                    "close": [10.0],
                    "volume": [1.0],
                },
                index=pd.to_datetime(["2026-01-01"]),
            )

    quarantine = DataQualityQuarantine(tmp_path / "quarantine")
    service = MarketDataService(
        InvalidAdapter(),
        ParquetCandleStore(tmp_path / "parquet"),
        tmp_path / "snapshots",
        quarantine=quarantine,
    )
    instrument = pd.Series(
        {"exchange": "NSE", "tradingsymbol": "ABC", "instrument_token": 123}
    )
    with pytest.raises(ValueError, match="high"):
        service.sync_daily_history(instrument, date(2026, 1, 1), date(2026, 1, 1))

    quarantined = list((tmp_path / "quarantine").rglob("quarantine-*.json"))
    assert len(quarantined) == 1
    assert "high is inconsistent" in quarantined[0].read_text(encoding="utf-8")
    assert not (tmp_path / "parquet" / "raw").exists()



def test_invalid_chunk_is_not_checkpointed_and_raw_rows_are_preserved(tmp_path) -> None:
    class FakeKiteClient:
        def historical_data(self, instrument_token, from_date, to_date, interval,
                            continuous=False, oi=False):
            return [{
                "date": from_date,
                "open": 10.0,
                "high": 8.0,
                "low": 9.0,
                "close": 10.0,
                "volume": 1.0,
            }]

    checkpoints = JsonChunkCheckpointStore(tmp_path / "checkpoints")
    adapter = KiteMarketDataAdapter(
        FakeKiteClient(), request_executor=no_wait_executor(), checkpoint_store=checkpoints
    )
    with pytest.raises(CandleDataError, match="high is inconsistent") as error:
        adapter.fetch_daily_candles(
            123, date(2026, 1, 1), date(2026, 1, 1), chunk_days=1
        )
    assert len(error.value.raw_candles) == 1
    assert checkpoints.load(123, date(2026, 1, 1), date(2026, 1, 1), 1) is None


def test_malformed_missing_date_response_is_quarantined(tmp_path) -> None:
    class MalformedAdapter:
        def fetch_daily_candles(
            self, instrument_token, start, end, chunk_days=365, expected_sessions=None
        ):
            raise CandleDataError(
                "Kite historical response did not include candle dates",
                pd.DataFrame([{"open": 10.0, "high": 11.0}]),
            )

    quarantine = DataQualityQuarantine(tmp_path / "quarantine")
    service = MarketDataService(
        MalformedAdapter(),
        ParquetCandleStore(tmp_path / "parquet"),
        tmp_path / "snapshots",
        quarantine=quarantine,
    )
    instrument = pd.Series(
        {"exchange": "NSE", "tradingsymbol": "ABC", "instrument_token": 123}
    )
    with pytest.raises(CandleDataError, match="did not include candle dates"):
        service.sync_daily_history(instrument, date(2026, 1, 1), date(2026, 1, 1))

    quarantined = list((tmp_path / "quarantine").rglob("quarantine-*.json"))
    assert len(quarantined) == 1
    payload = quarantined[0].read_text(encoding="utf-8")
    assert "did not include candle dates" in payload
    assert '"open": 10.0' in payload


def test_cached_invalid_chunk_is_deleted_and_refetched(tmp_path) -> None:
    class FakeKiteClient:
        def __init__(self):
            self.calls = 0

        def historical_data(self, instrument_token, from_date, to_date, interval,
                            continuous=False, oi=False):
            self.calls += 1
            return [{
                "date": from_date,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 100.0,
            }]

    start = date(2026, 1, 1)
    checkpoints = JsonChunkCheckpointStore(tmp_path / "checkpoints")
    checkpoints.save(123, start, start, 1, [{
        "date": "2026-01-01", "open": 10.0, "high": 8.0,
        "low": 9.0, "close": 10.0, "volume": 1.0,
    }])
    client = FakeKiteClient()
    adapter = KiteMarketDataAdapter(
        client, request_executor=no_wait_executor(), checkpoint_store=checkpoints
    )
    result = adapter.fetch_daily_candles(123, start, start, chunk_days=1)
    assert client.calls == 1
    assert result.iloc[0]["high"] == 12.0



def test_pacer_applies_shared_rate_limit_cooldown() -> None:
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    pacer = KiteRequestPacer(sleep=sleep, monotonic=lambda: now[0])
    pacer.cooldown("historical", 7.0)
    pacer.wait("historical")
    assert sleeps == [7.0]


def test_retry_after_accepts_http_date() -> None:
    sleeps: list[float] = []
    retry_at = datetime.now(UTC) + timedelta(seconds=8)

    class RateLimitError(Exception):
        status_code = 429
        response = type(
            "Response",
            (),
            {"headers": {"Retry-After": format_datetime(retry_at, usegmt=True)}},
        )()

    calls = [0]

    def operation() -> str:
        calls[0] += 1
        if calls[0] == 1:
            raise RateLimitError("slow down")
        return "ok"

    assert no_wait_executor(sleeps).call("historical", operation) == "ok"
    assert calls[0] == 2
    assert 0 <= sleeps[0] <= 8


def test_service_returns_validated_frame_matching_parquet_readback(tmp_path) -> None:
    class FakeAdapter:
        def fetch_daily_candles(
            self, instrument_token, start, end, chunk_days=365, expected_sessions=None
        ):
            return pd.DataFrame(
                {
                    "open": [10.0, 11.0],
                    "high": [12.0, 13.0],
                    "low": [9.0, 10.0],
                    "close": [11.0, 12.0],
                    "volume": [100.0, 120.0],
                },
                index=pd.to_datetime(["2026-11-02", "2026-11-04"]),
            )

    store = ParquetCandleStore(tmp_path / "parquet")
    service = MarketDataService(FakeAdapter(), store, tmp_path / "snapshots")
    instrument = pd.Series(
        {"exchange": "NSE", "tradingsymbol": "RELIANCE", "instrument_token": 123}
    )
    paths, fetched = service.sync_daily_history_with_data(
        instrument, date(2026, 11, 2), date(2026, 11, 4)
    )
    persisted = store.read_latest(
        "NSE:RELIANCE", "2026-11-02", "2026-11-04"
    )

    assert len(paths) == 1
    assert paths[0].exists()
    pd.testing.assert_frame_equal(
        persisted, fetched, check_dtype=False, check_freq=False, check_exact=False,
        rtol=1e-10, atol=1e-10,
    )


def test_request_executor_exposes_detached_retry_statistics() -> None:
    calls = [0]

    class TemporaryServerError(Exception):
        status_code = 503

    def operation() -> str:
        calls[0] += 1
        if calls[0] == 1:
            raise TemporaryServerError("temporary")
        return "ok"

    executor = no_wait_executor()
    assert executor.call("historical", operation) == "ok"
    stats = executor.snapshot_stats()

    assert stats["historical"] == {
        "calls": 1,
        "attempts": 2,
        "retries": 1,
        "errors": 1,
        "terminal_failures": 0,
    }
    stats["historical"]["calls"] = 99
    assert executor.snapshot_stats()["historical"]["calls"] == 1
