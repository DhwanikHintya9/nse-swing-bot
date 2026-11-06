from __future__ import annotations

import json
from pathlib import Path

import pytest

from nse_swing_bot.market_data.acquisition_manifest import (
    AcquisitionManifestError,
    build_acquisition_manifest,
    sha256_file,
    verify_acquisition_manifest,
    write_acquisition_manifest,
)


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "manifest_id": "pilot-2026-11-06-001",
        "run_started_at_utc": "2026-11-06T10:00:00Z",
        "run_completed_at_utc": "2026-11-06T10:02:00Z",
        "provider": "kite_connect",
        "read_only": True,
        "orders_endpoint_calls": 0,
        "production_eligible": False,
        "adjustment_status": "provider_adjusted_unreconciled",
        "symbols": [
            {
                "exchange": "NSE",
                "tradingsymbol": "RELIANCE",
                "isin": "INE002A01018",
                "instrument_token": 738561,
                "row_count": 3,
            }
        ],
    }


def test_manifest_digest_is_deterministic_and_verifiable() -> None:
    first = build_acquisition_manifest(valid_payload())
    second = build_acquisition_manifest(dict(reversed(list(valid_payload().items()))))

    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert verify_acquisition_manifest(first)


def test_manifest_detects_payload_tampering() -> None:
    manifest = build_acquisition_manifest(valid_payload())
    manifest["symbols"][0]["row_count"] = 4  # type: ignore[index]

    with pytest.raises(AcquisitionManifestError, match="does not match"):
        verify_acquisition_manifest(manifest)


def test_manifest_requires_read_only_safety_envelope() -> None:
    payload = valid_payload()
    payload["orders_endpoint_calls"] = 1

    with pytest.raises(AcquisitionManifestError, match="zero order endpoint"):
        build_acquisition_manifest(payload)


def test_manifest_rejects_credential_fields_recursively() -> None:
    payload = valid_payload()
    payload["connection"] = {"access_token": "must-not-be-recorded"}

    with pytest.raises(AcquisitionManifestError, match="credential-like"):
        build_acquisition_manifest(payload)


def test_manifest_rejects_non_finite_json_values() -> None:
    payload = valid_payload()
    payload["unexpected_numeric"] = float("nan")

    with pytest.raises(AcquisitionManifestError, match="canonical JSON"):
        build_acquisition_manifest(payload)


def test_manifest_write_is_immutable_and_hashable(tmp_path: Path) -> None:
    manifest = build_acquisition_manifest(valid_payload())
    destination = tmp_path / "manifests" / "pilot.json"

    written = write_acquisition_manifest(manifest, destination)

    assert written == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == manifest
    assert sha256_file(destination)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_acquisition_manifest(manifest, destination)
