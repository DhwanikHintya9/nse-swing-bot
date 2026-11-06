from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "validate_membership_ledgers.py"
)
SPEC = importlib.util.spec_from_file_location("validate_membership_ledgers", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

IDENTIFIER_FIELDS = module.IDENTIFIER_FIELDS
IDENTITY_EVENT_FIELDS = module.IDENTITY_EVENT_FIELDS
MEMBERSHIP_EVENT_FIELDS = module.MEMBERSHIP_EVENT_FIELDS
HASH_A = "a" * 64
HASH_B = "b" * 64


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _identifier_rows() -> list[dict[str, str]]:
    common = {
        "security_id": "SEC-1",
        "issuer_id": "ISS-1",
        "series": "EQ",
        "valid_from": "2020-01-01",
        "valid_to": "",
        "source_url": "https://www.nseindia.com/example",
        "source_sha256": HASH_A,
        "identity_status": "verified_source_attributed",
        "notes": "",
    }
    return [
        {
            **common,
            "identifier_type": "ISIN",
            "identifier_value": "INE000000001",
        },
        {
            **common,
            "identifier_type": "NSE_SYMBOL",
            "identifier_value": "ABC",
        },
    ]


def _identity_event_rows() -> list[dict[str, str]]:
    return [
        {
            "identity_event_id": "ID-EVENT-1",
            "event_type": "stock_split",
            "effective_date": "2022-01-10",
            "predecessor_security_id": "SEC-1",
            "successor_security_id": "SEC-1",
            "relationship": "continues_as",
            "old_isin": "INE000000001",
            "new_isin": "INE000000001",
            "old_symbol": "ABC",
            "new_symbol": "ABC",
            "ratio": "10:1",
            "source_url": "https://www.nseindia.com/corporate-action",
            "source_sha256": HASH_A,
            "notes": "",
        }
    ]


def _membership_event_rows() -> list[dict[str, str]]:
    return [
        {
            "event_id": "MEM-EVENT-1",
            "index_name": "NIFTY 500",
            "issuer_id": "ISS-1",
            "security_id": "SEC-1",
            "isin_at_event": "INE000000001",
            "symbol_at_event": "ABC",
            "series": "EQ",
            "action": "addition",
            "announcement_date": "2022-01-01",
            "published_at_utc": "2022-01-01T10:00:00Z",
            "effective_date": "2022-02-01",
            "event_status": "confirmed",
            "supersedes_event_id": "",
            "notice_url": "https://www.niftyindices.com/Press_Release/example.pdf",
            "notice_section": "Nifty 500 constituent changes",
            "source_sha256": HASH_B,
            "notes": "",
        }
    ]


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    identifiers = _write(
        tmp_path / "security-identifiers.csv", IDENTIFIER_FIELDS, _identifier_rows()
    )
    identity_events = _write(
        tmp_path / "security-identity-events.csv",
        IDENTITY_EVENT_FIELDS,
        _identity_event_rows(),
    )
    membership_events = _write(
        tmp_path / "official-membership-events.csv",
        MEMBERSHIP_EVENT_FIELDS,
        _membership_event_rows(),
    )
    return identifiers, identity_events, membership_events


def _validate(paths: tuple[Path, Path, Path]) -> dict[str, int]:
    return module.validate_ledgers(*paths)


def test_valid_ledgers_and_cross_references_pass(tmp_path: Path) -> None:
    counts = _validate(_paths(tmp_path))

    assert counts == {
        "security_identifiers": 2,
        "security_identity_events": 1,
        "official_membership_events": 1,
    }


def test_empty_header_only_templates_are_valid_but_empty(tmp_path: Path) -> None:
    paths = (
        _write(tmp_path / "identifiers.csv", IDENTIFIER_FIELDS, []),
        _write(tmp_path / "identity-events.csv", IDENTITY_EVENT_FIELDS, []),
        _write(tmp_path / "membership-events.csv", MEMBERSHIP_EVENT_FIELDS, []),
    )

    assert _validate(paths) == {
        "security_identifiers": 0,
        "security_identity_events": 0,
        "official_membership_events": 0,
    }


def test_schema_header_must_match_exactly(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    identifiers.write_text("security_id,issuer_id\n", encoding="utf-8")

    with pytest.raises(module.LedgerValidationError, match="header must exactly match"):
        _validate((identifiers, identity_events, membership_events))


def test_identifier_validity_intervals_are_half_open(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identifier_rows()
    rows[0]["valid_to"] = "2022-01-01"
    next_assignment = dict(
        rows[0],
        security_id="SEC-2",
        issuer_id="ISS-2",
        valid_from="2022-01-01",
        valid_to="",
    )
    rows.append(next_assignment)
    events = _membership_event_rows()
    events[0]["effective_date"] = "2021-12-31"
    _write(identifiers, IDENTIFIER_FIELDS, rows)
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, events)

    assert _validate((identifiers, identity_events, membership_events))[
        "security_identifiers"
    ] == 3


def test_overlapping_identifier_assignments_are_rejected(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identifier_rows()
    duplicate = dict(rows[0], security_id="SEC-2", issuer_id="ISS-2")
    rows.append(duplicate)
    _write(identifiers, IDENTIFIER_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="overlapping validity"):
        _validate((identifiers, identity_events, membership_events))


def test_identifier_end_must_follow_start(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identifier_rows()
    rows[0]["valid_to"] = rows[0]["valid_from"]
    _write(identifiers, IDENTIFIER_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="later than valid_from"):
        _validate((identifiers, identity_events, membership_events))


def test_security_id_cannot_map_to_multiple_issuers(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identifier_rows()
    rows[1]["issuer_id"] = "ISS-2"
    _write(identifiers, IDENTIFIER_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="multiple issuer_ids"):
        _validate((identifiers, identity_events, membership_events))


def test_unknown_identity_event_security_is_rejected(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identity_event_rows()
    rows[0]["successor_security_id"] = "SEC-MISSING"
    _write(identity_events, IDENTITY_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="unknown successor_security_id"):
        _validate((identifiers, identity_events, membership_events))


def test_identity_event_self_link_requires_continues_as(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identity_event_rows()
    rows[0]["relationship"] = "merged_into"
    _write(identity_events, IDENTITY_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="self-referencing"):
        _validate((identifiers, identity_events, membership_events))


def test_continues_as_requires_same_internal_security_id(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identifier_rows()
    second = dict(
        rows[0], security_id="SEC-2", issuer_id="ISS-2", identifier_value="INE000000002"
    )
    rows.append(second)
    _write(identifiers, IDENTIFIER_FIELDS, rows)
    events = _identity_event_rows()
    events[0]["successor_security_id"] = "SEC-2"
    _write(identity_events, IDENTITY_EVENT_FIELDS, events)

    with pytest.raises(module.LedgerValidationError, match="must retain the same"):
        _validate((identifiers, identity_events, membership_events))


def test_membership_event_requires_matching_issuer(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["issuer_id"] = "ISS-OTHER"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="issuer_id does not match"):
        _validate((identifiers, identity_events, membership_events))


def test_membership_identifiers_must_be_valid_on_effective_date(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identifier_rows()
    rows[0]["valid_to"] = "2022-01-15"
    rows[1]["valid_to"] = "2022-01-15"
    _write(identifiers, IDENTIFIER_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="not mapped.*on 2022-02-01"):
        _validate((identifiers, identity_events, membership_events))


def test_membership_event_must_match_both_isin_and_symbol(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["symbol_at_event"] = "WRONG"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="NSE_SYMBOL.*WRONG"):
        _validate((identifiers, identity_events, membership_events))


def test_membership_action_must_be_supported(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["action"] = "include"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="unsupported action"):
        _validate((identifiers, identity_events, membership_events))


def test_correction_requires_superseded_event(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["action"] = "correction"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="must reference supersedes_event_id"):
        _validate((identifiers, identity_events, membership_events))


def test_superseded_event_must_exist(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["action"] = "revocation"
    rows[0]["supersedes_event_id"] = "MISSING"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="does not exist"):
        _validate((identifiers, identity_events, membership_events))


def test_membership_event_supersession_cycles_are_rejected(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    first = dict(rows[0], event_id="MEM-EVENT-1", action="correction",
                 supersedes_event_id="MEM-EVENT-2")
    second = dict(rows[0], event_id="MEM-EVENT-2", action="revocation",
                  supersedes_event_id="MEM-EVENT-1")
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, [first, second])

    with pytest.raises(module.LedgerValidationError, match="supersession cycle"):
        _validate((identifiers, identity_events, membership_events))


def test_notice_section_must_identify_nifty_500(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["notice_section"] = "Nifty 100 constituent changes"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="explicitly identify"):
        _validate((identifiers, identity_events, membership_events))


def test_membership_notice_must_use_official_host(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["notice_url"] = "https://example.com/notice.pdf"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="official NSE/Nifty Indices host"):
        _validate((identifiers, identity_events, membership_events))


def test_source_hash_must_be_sha256(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _identifier_rows()
    rows[0]["source_sha256"] = "not-a-hash"
    _write(identifiers, IDENTIFIER_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="64-character SHA-256"):
        _validate((identifiers, identity_events, membership_events))


def test_published_timestamp_requires_timezone(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["published_at_utc"] = "2022-01-01T10:00:00"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="must include a UTC offset"):
        _validate((identifiers, identity_events, membership_events))


def test_published_timestamp_must_be_utc_not_just_offset_aware(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["published_at_utc"] = "2022-01-01T15:30:00+05:30"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="must be UTC"):
        _validate((identifiers, identity_events, membership_events))


def test_membership_ledger_rejects_other_indices(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows[0]["index_name"] = "NIFTY 50"
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="must identify NIFTY 500"):
        _validate((identifiers, identity_events, membership_events))


def test_duplicate_membership_event_ids_are_rejected(tmp_path: Path) -> None:
    identifiers, identity_events, membership_events = _paths(tmp_path)
    rows = _membership_event_rows()
    rows.append(dict(rows[0]))
    _write(membership_events, MEMBERSHIP_EVENT_FIELDS, rows)

    with pytest.raises(module.LedgerValidationError, match="duplicate event_id"):
        _validate((identifiers, identity_events, membership_events))
