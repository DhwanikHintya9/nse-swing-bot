"""Tests for NSE announcement CSV normalization."""
import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_nse_announcement_export.py"
spec = importlib.util.spec_from_file_location("import_nse_announcement_export", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _write(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_nse_export_is_filtered_and_staged_without_guessing_event_date(tmp_path):
    universe = tmp_path / "universe.csv"
    source = tmp_path / "nse.csv"
    included = tmp_path / "review.csv"
    excluded = tmp_path / "excluded.csv"
    _write(universe, ["Symbol"], [["RELIANCE"], ["TCS"]])
    _write(source, [
        "SYMBOL", "COMPANY NAME", "SUBJECT", "DETAILS",
        "ATTACHMENT", "XBRL", "BROADCAST DATE/TIME",
    ], [
        ["RELIANCE", "Reliance Industries Limited", "Board Meeting",
         "Board meeting intimation", "https://example.test/file.pdf", "",
         "05-Nov-2026 18:10:00"],
        ["UNKNOWN", "Other Limited", "Investor Presentation", "Details", "", "",
         "05-Nov-2026 18:00:00"],
        ["-", "Unmapped Entity", "Annual Disclosure", "Details", "", "",
         "05-Nov-2026 17:00:00"],
    ])
    assert module.normalize_export(source, universe, included, excluded) == (1, 2)
    with included.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["symbol"] == "RELIANCE"
    assert rows[0]["review_status"] == "pending"
    assert rows[0]["event_type"] == ""
    assert rows[0]["event_date"] == ""
    assert rows[0]["announcement_url"] == ""
    assert rows[0]["broadcast_date_time_raw"] == "05-Nov-2026 18:10:00"
    with excluded.open(newline="", encoding="utf-8") as handle:
        rejects = list(csv.DictReader(handle))
    assert {row["reason"] for row in rejects} == {
        "blank_symbol", "symbol_outside_universe"
    }


def test_export_refuses_overwrite(tmp_path):
    universe = tmp_path / "universe.csv"
    source = tmp_path / "nse.csv"
    included = tmp_path / "review.csv"
    excluded = tmp_path / "excluded.csv"
    _write(universe, ["Symbol"], [["RELIANCE"]])
    _write(source, [
        "SYMBOL", "COMPANY NAME", "SUBJECT", "DETAILS", "BROADCAST DATE/TIME",
    ], [])
    module.normalize_export(source, universe, included, excluded)
    with pytest.raises(FileExistsError):
        module.normalize_export(source, universe, included, excluded)


def test_export_rejects_unknown_schema(tmp_path):
    source = tmp_path / "nse.csv"
    _write(source, ["SYMBOL", "SUBJECT"], [["RELIANCE", "Board Meeting"]])
    with pytest.raises(ValueError, match="missing columns"):
        module._column_map(["SYMBOL", "SUBJECT"])
