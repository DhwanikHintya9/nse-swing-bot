"""Create a safe, non-extracting inventory of a captured ZIP filing package."""
from __future__ import annotations

import argparse
from pathlib import Path

from nse_swing_bot.events.zip_inventory import inspect_captured_zip_package


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventory a captured ZIP package without extracting its contents."
    )
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect_captured_zip_package(args.capture_manifest, args.output)
    print(f"Inventory: {result.manifest_path}")
    print(f"Event: {result.event_id}")
    print(f"Source record: {result.source_record_id}")
    print(f"Parent archive SHA-256: {result.archive_sha256}")
    print(f"Members: {result.member_count}")
    print(f"Uncompressed bytes: {result.total_uncompressed_bytes}")
    print("ZIP inventory complete; no member was extracted or accepted as evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
