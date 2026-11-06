"""Verify the integrity of an existing local source capture."""
from __future__ import annotations

import argparse
from pathlib import Path

from nse_swing_bot.events.capture_verification import verify_capture_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify archived source bytes against their capture manifest."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    verified = verify_capture_manifest(args.manifest)
    print(f"Verified archive: {verified.archive_path}")
    print(f"Event: {verified.event_id}")
    print(f"Source record: {verified.source_record_id}")
    print(f"Bytes: {verified.byte_length}")
    print(f"SHA-256: {verified.sha256}")
    print("Integrity: verified; source authenticity and evidence review remain separate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
