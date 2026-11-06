"""Apply a separately curated evidence registry to observed membership diffs.

The source reconciliation CSV is read-only input. Missing registry rows remain
unresolved; this tool never infers membership effective dates.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

REGISTRY_FIELDS = [
    "isin",
    "change",
    "classification",
    "evidence_type",
    "evidence_url",
    "event_date",
    "membership_effective_date",
    "conflict_flag",
    "notes",
]
CLASSIFICATIONS = {
    "official_index_change",
    "corporate_action_identity_bridge",
    "unresolved_observed_change",
}
OUTPUT_FIELDS = [
    "classification",
    "evidence_type",
    "evidence_url",
    "event_date",
    "membership_effective_date",
    "conflict_flag",
    "evidence_notes",
]


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no CSV header")
        return list(reader.fieldnames), list(reader)


def _valid_date(value: str, field: str, *, required: bool) -> str:
    if not value:
        if required:
            raise ValueError(f"{field} is required for this classification")
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD: {value}") from error


def build_classification(
    observed_path: Path, registry_path: Path, output_path: Path
) -> dict[str, int]:
    observed_fields, observed_rows = _read_csv(observed_path)
    required_observed = {
        "isin", "change", "previous_snapshot_date", "next_snapshot_date"
    }
    if not required_observed.issubset(observed_fields):
        raise ValueError(
            "observed diff is missing columns: "
            + ", ".join(sorted(required_observed - set(observed_fields)))
        )

    if not registry_path.exists():
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        with registry_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REGISTRY_FIELDS)
            writer.writeheader()
        return {"template_created": 1, "classified": 0, "unresolved": len(observed_rows)}

    registry_fields, registry_rows = _read_csv(registry_path)
    missing = set(REGISTRY_FIELDS) - set(registry_fields)
    if missing:
        raise ValueError("registry is missing columns: " + ", ".join(sorted(missing)))

    observed_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in observed_rows:
        key = (row["isin"].strip().upper(), row["change"].strip())
        if key in observed_by_key:
            raise ValueError(f"duplicate observed event key: {key}")
        observed_by_key[key] = row

    registry_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in registry_rows:
        key = (row["isin"].strip().upper(), row["change"].strip())
        if key in registry_by_key:
            raise ValueError(f"duplicate registry event key: {key}")
        if key not in observed_by_key:
            raise ValueError(f"registry row does not match an observed event: {key}")
        classification = row["classification"].strip()
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"unsupported classification for {key}: {classification}")
        registry_by_key[key] = row

    output_rows: list[dict[str, str]] = []
    counts = {name: 0 for name in CLASSIFICATIONS}
    for key, observed in observed_by_key.items():
        evidence = registry_by_key.get(key, {})
        classification = evidence.get(
            "classification", "unresolved_observed_change"
        ).strip() or "unresolved_observed_change"
        evidence_url = evidence.get("evidence_url", "").strip()
        event_date = _valid_date(
            evidence.get("event_date", "").strip(), "event_date",
            required=classification != "unresolved_observed_change",
        )
        membership_date = _valid_date(
            evidence.get("membership_effective_date", "").strip(),
            "membership_effective_date",
            required=classification == "official_index_change",
        )
        if classification == "official_index_change":
            if not evidence_url.startswith("https://"):
                raise ValueError(f"official index evidence needs an HTTPS URL: {key}")
            lower = observed["previous_snapshot_date"]
            upper = observed["next_snapshot_date"]
            if not lower <= membership_date <= upper:
                raise ValueError(
                    f"membership effective date outside observed interval for {key}: "
                    f"{membership_date} not in [{lower}, {upper}]"
                )
        elif classification == "corporate_action_identity_bridge":
            if not evidence_url.startswith("https://"):
                raise ValueError(f"corporate-action evidence needs an HTTPS URL: {key}")
            if membership_date:
                raise ValueError(
                    f"corporate-action identity bridge must not assert membership date: {key}"
                )
        elif event_date or membership_date or evidence_url:
            raise ValueError(
                f"unresolved event must not carry asserted dates or evidence URL: {key}"
            )

        conflict = evidence.get("conflict_flag", "").strip().lower()
        if conflict not in {"", "true", "false"}:
            raise ValueError(f"conflict_flag must be true/false/blank for {key}")
        counts[classification] += 1
        output_rows.append(
            {
                **observed,
                "classification": classification,
                "evidence_type": evidence.get("evidence_type", "").strip(),
                "evidence_url": evidence_url,
                "event_date": event_date,
                "membership_effective_date": membership_date,
                "conflict_flag": conflict or "false",
                "evidence_notes": evidence.get("notes", "").strip(),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_fields = observed_fields + OUTPUT_FIELDS
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields, lineterminator="\\n")
        writer.writeheader()
        writer.writerows(output_rows)
    return {
        "template_created": 0,
        "classified": counts["official_index_change"]
        + counts["corporate_action_identity_bridge"],
        "unresolved": counts["unresolved_observed_change"],
        **counts,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Classify observed membership changes using a separate evidence registry."
    )
    parser.add_argument(
        "--observed",
        type=Path,
        default=root / "data/universe/membership_reconciliation/observed-membership-changes.csv",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=root / "data/universe/membership_reconciliation/membership-change-evidence.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data/universe/membership_reconciliation/classified-membership-changes.csv",
    )
    args = parser.parse_args()
    try:
        counts = build_classification(args.observed, args.registry, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if counts["template_created"]:
        print(f"Evidence registry template created: {args.registry}")
        print("Populate it from verified primary evidence, then rerun.")
    else:
        print(f"Classified events: {counts['classified']}")
        print(f"Unresolved events: {counts['unresolved']}")
        print(f"Classified output: {args.output}")
    print("Original observed-membership-changes.csv modified: NO")
    print("Research ready: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
