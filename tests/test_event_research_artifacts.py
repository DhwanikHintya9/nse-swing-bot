import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from nse_swing_bot.events.diagnostics import DIAGNOSTIC_COLUMNS
from nse_swing_bot.events.research_artifacts import export_research_event_frame


def sample_frame() -> pd.DataFrame:
    index = pd.date_range("2026-10-01", periods=2, freq="D", tz="Asia/Kolkata")
    data = {
        "signal": [True, False],
        "sma_50": [100.0, 101.0],
        "admitted_event_count": [1, 2],
        "event_count_7d": [1, 2],
        "event_count_30d": [1, 2],
        "days_to_next_effective_event": [3, None],
        "has_high_materiality_event_30d": [False, True],
        "positive_event_count_30d": [0, 1],
        "negative_event_count_30d": [0, 0],
        "mixed_event_count_30d": [0, 0],
        "unassessed_impact_count_30d": [1, 1],
        "taxonomy_counts_30d": [(("financial_results", 1),), (("financial_results", 2),)],
        "admitted_event_ids": [(("evt-1",)), (("evt-1", "evt-2"))],
    }
    assert set(DIAGNOSTIC_COLUMNS).issubset(data)
    return pd.DataFrame(data, index=index)


def test_export_writes_hash_bound_csv_and_manifest(tmp_path: Path) -> None:
    captured_at = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
    csv_path, manifest_path = export_research_event_frame(
        sample_frame(), tmp_path, captured_at
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    content = csv_path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == manifest["csv_sha256"]
    assert manifest["row_count"] == 2
    assert manifest["production_eligible"] is False
    assert manifest["broker_execution_eligible"] is False
    assert manifest["strategy_signal_modified"] is False
    rows = pd.read_csv(csv_path)
    assert rows["signal"].tolist() == [True, False]
    assert json.loads(rows["admitted_event_ids"].iloc[0]) == ["evt-1"]


def test_export_rejects_naive_capture_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        export_research_event_frame(
            sample_frame(), tmp_path, datetime(2026, 11, 6, 10, 0)
        )


def test_export_rejects_missing_diagnostics(tmp_path: Path) -> None:
    frame = sample_frame().drop(columns=["admitted_event_ids"])
    with pytest.raises(ValueError, match="missing event diagnostics"):
        export_research_event_frame(frame, tmp_path, datetime.now(UTC))


def test_export_rejects_duplicate_decision_times(tmp_path: Path) -> None:
    frame = sample_frame()
    frame.index = [frame.index[0], frame.index[0]]
    with pytest.raises(ValueError, match="unique"):
        export_research_event_frame(frame, tmp_path, datetime.now(UTC))


def test_export_is_immutable_and_deterministic(tmp_path: Path) -> None:
    frame = sample_frame()
    captured_at = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
    first = export_research_event_frame(frame, tmp_path, captured_at)
    with pytest.raises(FileExistsError):
        export_research_event_frame(frame, tmp_path, captured_at)
    assert first[0].exists() and first[1].exists()
