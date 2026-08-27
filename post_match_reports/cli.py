from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from .discovery import discover_latest_ready
from .generation import generate_bundle, write_manifest


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and generate CAFC post-match reports")
    commands = parser.add_subparsers(dest="command", required=True)

    discover = commands.add_parser("discover")
    discover.add_argument("--team", default="Charlton Athletic")
    discover.add_argument("--not-before", type=_date)
    discover.add_argument("--json", action="store_true")

    generate = commands.add_parser("generate")
    generate.add_argument("--impect-match-id", type=int, required=True)
    generate.add_argument("--dvms-match-id", required=True)
    generate.add_argument("--output-dir", type=Path, required=True)
    generate.add_argument("--manifest", type=Path)
    generate.add_argument("--chrome-bin", default=os.environ.get("CHROME_BIN"))

    args = parser.parse_args()
    if args.command == "discover":
        ready = discover_latest_ready(args.team, args.not_before)
        payload = {"ready": ready is not None, "fixture": ready.to_dict() if ready else None}
        print(json.dumps(payload) if args.json else payload)
        return 0

    manifest = generate_bundle(
        args.impect_match_id,
        args.dvms_match_id,
        args.output_dir,
        chrome_bin=args.chrome_bin,
    )
    manifest_path = args.manifest or args.output_dir / "manifest.json"
    write_manifest(manifest, manifest_path)
    print(manifest_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
