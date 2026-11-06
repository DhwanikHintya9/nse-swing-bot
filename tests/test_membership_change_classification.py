from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "classify_membership_changes.py"
SPEC = importlib.util.spec_from_file_location("classify_membership_changes", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\\n")
        writer.writeheader()
        writer.writerows(rows)


OBSERVED_FIELDS = [
    "isin", "change", "previous_snapshot_date", "next_snapshot_date"
]
REGISTRY_FIELDS = module.REGISTRY_FIELDS


def test_missing_registry_creates_template_without_touching_observed(tmp_path: Path) -> None:
    observed = tmp_path / "observed.csv"
    registry = tmp_path / "registry.csv"
    output = tmp_path / "classified.csv"
    _write(observed, OBSERVED_FIELDS, [{
        "isin": "INE000000001",
        "change": "observed_addition",
        "previous_snapshot_date": "2022-05-04",
        "next_snapshot_date": "2022-10-09",
    }])
    original = observed.read_bytes()

    result = module.build_classification(observed, registry, output)

    assert result["template_created"] == 1
    assert not output.exists()
    assert observed.read_bytes() == original
    with registry.open(encoding="utf-8", newline="") as handle:
        assert next(csv.reader(handle)) == REGISTRY_FIELDS


def test_classification_preserves_observation_and_keeps_missing_rows_unresolved(
    tmp_path: Path,
) -> None:
    observed = tmp_path / "observed.csv"
    registry = tmp_path / "registry.csv"
    output = tmp_path / "classified.csv"
    _write(observed, OBSERVED_FIELDS, [
        {
            "isin": "INE000000001",
            "change": "observed_addition",
            "previous_snapshot_date": "2022-05-04",
            "next_snapshot_date": "2022-10-09",
        },
        {
            "isin": "INE000000002",
            "change": "observed_removal",
            "previous_snapshot_date": "2022-05-04",
            "next_snapshot_date": "2022-10-09",
        },
    ])
    _write(registry, REGISTRY_FIELDS, [{
        "isin": "INE000000001",
        "change": "observed_addition",
        "classification": "official_index_change",
        "evidence_type": "official_nifty_indices_notice",
        "evidence_url": "https://niftyindices.com/press-release",
        "event_date": "2022-09-30",
        "membership_effective_date": "2022-09-30",
        "conflict_flag": "false",
        "notes": "Explicit Nifty 500 section checked",
    }])
    original = observed.read_bytes()

    result = module.build_classification(observed, registry, output)

    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert result["official_index_change"] == 1
    assert result["unresolved_observed_change"] == 1
    assert rows[0]["membership_effective_date"] == "2022-09-30"
    assert rows[1]["classification"] == "unresolved_observed_change"
    assert rows[1]["membership_effective_date"] == ""
    assert observed.read_bytes() == original


def test_corporate_action_bridge_cannot_assert_membership_effective_date(
    tmp_path: Path,
) -> None:
    observed = tmp_path / "observed.csv"
    registry = tmp_path / "registry.csv"
    output = tmp_path / "classified.csv"
    _write(observed, OBSERVED_FIELDS, [{
        "isin": "INE000000001",
        "change": "observed_addition",
        "previous_snapshot_date": "2022-05-04",
        "next_snapshot_date": "2022-10-09",
    }])
    _write(registry, REGISTRY_FIELDS, [{
        "isin": "INE000000001",
        "change": "observed_addition",
        "classification": "corporate_action_identity_bridge",
        "evidence_type": "issuer_corporate_action",
        "evidence_url": "https://www.nseindia.com/",
        "event_date": "2022-07-28",
        "membership_effective_date": "2022-07-28",
        "conflict_flag": "false",
        "notes": "Identity only",
    }])

    with pytest.raises(ValueError, match="must not assert membership date"):
        module.build_classification(observed, registry, output)
