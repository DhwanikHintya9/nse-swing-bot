"""Tests for the fail-closed corporate-event review summary."""
import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "summarize_corporate_event_review.py"
)
spec = importlib.util.spec_from_file_location("summarize_corporate_event_review", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _write(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_summary_reports_absent_symbols_without_claiming_negative_coverage(tmp_path):
    universe = tmp_path / "universe.csv"
    review = tmp_path / "review.csv"
    _write(universe, ["Symbol"], [["RELIANCE"], ["TCS"], ["INFY"]])
    _write(
        review,
        ["symbol", "review_priority", "review_status"],
        [["RELIANCE", "high", "pending"], ["RELIANCE", "medium", "pending"],
         ["TCS", "medium", "reviewed"]],
    )
    summary = module.summarize_review_inbox(universe, review)
    assert "Candidate records: 3" in summary
    assert "Symbols represented: 2" in summary
    assert "Symbols with no candidates in this export: 1" in summary
    assert "INFY" in summary
    assert "High-priority candidates: 1" in summary
    assert "pending=2, reviewed=1" in summary
    assert "not proof of no events" in summary
    assert "Coverage is not inferred" in summary


def test_summary_rejects_candidate_outside_universe(tmp_path):
    universe = tmp_path / "universe.csv"
    review = tmp_path / "review.csv"
    _write(universe, ["Symbol"], [["RELIANCE"]])
    _write(review, ["symbol", "review_priority", "review_status"],
           [["UNKNOWN", "high", "pending"]])
    with pytest.raises(ValueError, match="outside universe"):
        module.summarize_review_inbox(universe, review)


def test_summary_rejects_unknown_priority(tmp_path):
    universe = tmp_path / "universe.csv"
    review = tmp_path / "review.csv"
    _write(universe, ["Symbol"], [["RELIANCE"]])
    _write(review, ["symbol", "review_priority", "review_status"],
           [["RELIANCE", "urgent", "pending"]])
    with pytest.raises(ValueError, match="invalid review_priority"):
        module.summarize_review_inbox(universe, review)
