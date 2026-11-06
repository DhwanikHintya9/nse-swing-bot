"""Tests for bounded, fail-closed corporate-event review batches."""
import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "export_corporate_event_review_batch.py"
)
spec = importlib.util.spec_from_file_location("export_corporate_event_review_batch", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

FIELDS = [
    "record_id", "symbol", "review_priority", "review_status",
    "broadcast_date_time_raw", "subject", "details", "attachment",
    "source_file", "source_page_url", "event_type", "event_date",
    "announcement_url", "secondary_source_url", "review_notes",
]


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _row(record_id, priority, status="pending"):
    return {
        "record_id": record_id, "symbol": "RELIANCE",
        "review_priority": priority, "review_status": status,
        "broadcast_date_time_raw": "06-Nov-2026 10:00:00",
        "subject": "Board Meeting", "details": "", "attachment": "",
        "source_file": "nse.csv", "source_page_url": "https://www.nseindia.com/",
        "event_type": "", "event_date": "", "announcement_url": "",
        "secondary_source_url": "", "review_notes": "",
    }


def test_exports_bounded_pending_high_priority_batch_in_source_order(tmp_path):
    source = tmp_path / "inbox.csv"
    output = tmp_path / "batch.csv"
    _write(source, [
        _row("h1", "high"), _row("m1", "medium"),
        _row("done", "high", "reviewed"), _row("h2", "high"),
    ])
    assert module.export_review_batch(source, output, "high", 1, 1) == (2, 1)
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["record_id"] for row in rows] == ["h2"]
    assert rows[0]["event_type"] == ""
    assert rows[0]["review_status"] == "pending"


def test_all_priority_batch_and_overwrite_protection(tmp_path):
    source = tmp_path / "inbox.csv"
    output = tmp_path / "batch.csv"
    _write(source, [_row("h1", "high"), _row("m1", "medium")])
    assert module.export_review_batch(source, output, "all", 10, 0) == (2, 2)
    with pytest.raises(FileExistsError):
        module.export_review_batch(source, output, "all", 10, 0)


def test_rejects_duplicate_candidate_ids(tmp_path):
    source = tmp_path / "inbox.csv"
    _write(source, [_row("same", "high"), _row("same", "medium")])
    with pytest.raises(ValueError, match="duplicate record_id"):
        module.export_review_batch(source, tmp_path / "batch.csv", "all", 10, 0)


@pytest.mark.parametrize("limit,offset", [(0, 0), (-1, 0), (1, -1)])
def test_rejects_invalid_pagination(tmp_path, limit, offset):
    source = tmp_path / "inbox.csv"
    _write(source, [_row("h1", "high")])
    with pytest.raises(ValueError, match="limit must be positive"):
        module.export_review_batch(source, tmp_path / "batch.csv", "high", limit, offset)
