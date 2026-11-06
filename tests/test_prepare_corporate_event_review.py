"""Tests for the fail-closed event-candidate staging utility."""
import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_corporate_event_review.py"
spec = importlib.util.spec_from_file_location("prepare_corporate_event_review", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_review_queue_deduplicates_and_never_verifies(tmp_path):
    universe = tmp_path / "universe.csv"
    incoming = tmp_path / "incoming.csv"
    output = tmp_path / "review.csv"
    _csv(universe, ["Symbol"], [["RELIANCE"]])
    _csv(incoming, module.COLUMNS, [
        ["RELIANCE", "earnings", "2026-11-20", "2026-11-01T10:00:00+05:30",
         "Board meeting", "https://nseindia.com/announcement/1"],
        ["RELIANCE", "earnings", "2026-11-20", "2026-11-01T10:00:00+05:30",
         "Board meeting", "https://nseindia.com/announcement/1"],
    ])
    assert module.build_review_queue(universe, [incoming], output) == 1
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["review_status"] == "pending"
    assert rows[0]["secondary_source_url"] == ""
    assert "complete" not in rows[0]
    with pytest.raises(FileExistsError):
        module.build_review_queue(universe, [incoming], output)


@pytest.mark.parametrize("symbol,announced,url", [
    ("UNKNOWN", "2026-11-01T10:00:00+05:30", "https://example.com/event"),
    ("RELIANCE", "2026-11-01T10:00:00", "https://example.com/event"),
    ("RELIANCE", "2026-11-01T10:00:00+05:30", "file:///tmp/event"),
])
def test_invalid_candidates_rejected(tmp_path, symbol, announced, url):
    universe = tmp_path / "universe.csv"
    incoming = tmp_path / "incoming.csv"
    _csv(universe, ["Symbol"], [["RELIANCE"]])
    _csv(incoming, module.COLUMNS, [
        [symbol, "earnings", "2026-11-20", announced, "Board meeting", url],
    ])
    with pytest.raises(ValueError):
        module.build_review_queue(universe, [incoming], tmp_path / "review.csv")
