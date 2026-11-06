from __future__ import annotations

from csv import DictReader, writer
from datetime import date
from json import loads
from pathlib import Path

import pytest

from nse_swing_bot.market_data.membership_evidence import (
    MembershipEvidenceError,
    ingest_membership_snapshot,
    reconcile_membership_snapshots,
)


OFFICIAL_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
CAPTURED = "2026-11-06T10:00:00Z"


def _write_snapshot(path: Path, rows: list[tuple[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv_writer = writer(handle, lineterminator="\n")
        csv_writer.writerow(["Company Name", "Industry", "Symbol", "Series", "ISIN Code"])
        for index, (symbol, isin) in enumerate(rows):
            csv_writer.writerow([f"Company {index}", "Industry", symbol, "EQ", isin])
    return path


def _rows(prefix: str, start: int, count: int) -> list[tuple[str, str]]:
    return [
        (f"{prefix}{index:03d}", f"INE{index:09d}")
        for index in range(start, start + count)
    ]


def _ingest(path: Path, output: Path, as_of: date, source_kind: str = "official_snapshot") -> Path:
    evidence_url = (
        OFFICIAL_URL
        if source_kind == "official_snapshot"
        else "https://web.archive.org/web/20261106100000id_/https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    )
    return ingest_membership_snapshot(
        path,
        as_of_date=as_of,
        source_url=OFFICIAL_URL,
        evidence_url=evidence_url,
        source_kind=source_kind,
        captured_at_utc=CAPTURED,
        published_at_utc=None,
        output_dir=output,
        min_rows=1,
        max_rows=600,
    )


def test_ingest_retains_raw_snapshot_and_verifiable_hashes(tmp_path: Path) -> None:
    source = _write_snapshot(tmp_path / "source.csv", _rows("S", 0, 500))
    manifest_path = _ingest(source, tmp_path / "snapshots", date(2026, 9, 30))
    manifest = loads(manifest_path.read_text(encoding="utf-8"))

    raw_path = manifest_path.parent / manifest["raw_filename"]
    normalized_path = manifest_path.parent / manifest["normalized_filename"]
    assert raw_path.read_bytes() == source.read_bytes()
    assert len(manifest["raw_sha256"]) == 64
    assert len(manifest["normalized_sha256"]) == 64
    assert normalized_path.is_file()
    assert manifest["effective_date_claimed"] is False
    assert manifest["identity_key"] == "isin"


def test_reconcile_reports_observed_changes_without_exact_effective_dates(
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    first = _write_snapshot(tmp_path / "first.csv", _rows("S", 0, 500))
    second_rows = _rows("S", 0, 498) + _rows("N", 500, 2)
    second = _write_snapshot(tmp_path / "second.csv", second_rows)
    _ingest(first, snapshot_dir, date(2025, 9, 30))
    _ingest(second, snapshot_dir, date(2026, 3, 31))

    diff_path = tmp_path / "diff" / "changes.csv"
    report = reconcile_membership_snapshots(snapshot_dir, diff_path)

    assert report["snapshot_count"] == 2
    assert report["total_observed_changes"] == 4
    assert report["effective_dates_inferred"] is False
    with diff_path.open(encoding="utf-8", newline="") as handle:
        changes = list(DictReader(handle))
    assert sum(row["change"] == "observed_addition" for row in changes) == 2
    assert sum(row["change"] == "observed_removal" for row in changes) == 2
    assert all(row["effective_date"] == "" for row in changes)
    assert all(
        row["effective_date_status"] == "unknown_between_snapshots"
        for row in changes
    )


def test_wayback_capture_requires_official_original_source(tmp_path: Path) -> None:
    source = _write_snapshot(tmp_path / "source.csv", _rows("S", 0, 500))
    with pytest.raises(MembershipEvidenceError, match="official NSE"):
        ingest_membership_snapshot(
            source,
            as_of_date=date(2024, 9, 30),
            source_url="https://example.com/constituents.csv",
            evidence_url="https://web.archive.org/web/20240930id_/https://example.com/constituents.csv",
            source_kind="wayback_capture",
            captured_at_utc=CAPTURED,
            published_at_utc=None,
            output_dir=tmp_path / "snapshots",
        )


def test_third_party_reconstruction_cannot_be_an_anchor(tmp_path: Path) -> None:
    source = _write_snapshot(tmp_path / "source.csv", _rows("S", 0, 500))
    with pytest.raises(MembershipEvidenceError, match="third-party reconstructions"):
        ingest_membership_snapshot(
            source,
            as_of_date=date(2024, 9, 30),
            source_url=OFFICIAL_URL,
            evidence_url=OFFICIAL_URL,
            source_kind="third_party_reconstruction",
            captured_at_utc=CAPTURED,
            published_at_utc=None,
            output_dir=tmp_path / "snapshots",
        )


def test_duplicate_isin_is_rejected(tmp_path: Path) -> None:
    rows = _rows("S", 0, 499) + [("DUPLICATE", "INE000000000")]
    rows[-1] = ("DUPLICATE", rows[0][1])
    source = _write_snapshot(tmp_path / "source.csv", rows)
    with pytest.raises(MembershipEvidenceError, match="duplicate ISIN"):
        _ingest(source, tmp_path / "snapshots", date(2024, 9, 30))


def test_tampered_normalized_snapshot_is_rejected(tmp_path: Path) -> None:
    source = _write_snapshot(tmp_path / "source.csv", _rows("S", 0, 500))
    snapshot_dir = tmp_path / "snapshots"
    manifest_path = _ingest(source, snapshot_dir, date(2024, 9, 30))
    second_source = _write_snapshot(tmp_path / "second.csv", _rows("T", 600, 500))
    _ingest(second_source, snapshot_dir, date(2025, 3, 31))
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    normalized = manifest_path.parent / manifest["normalized_filename"]
    normalized.write_text(normalized.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")

    with pytest.raises(MembershipEvidenceError, match="hash mismatch"):
        reconcile_membership_snapshots(snapshot_dir, tmp_path / "diff.csv")
