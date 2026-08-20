#!/usr/bin/env python3
"""Generate the recovered Charlton post-match analyst report as PDF only.

The report combines Impect event data with DVMS/Opta tracking data.  Only the
final PDF is persisted; the HTML used for Chromium rendering remains in memory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impect-match-id", type=int, required=True)
    parser.add_argument("--dvms-match-id", help="optional DVMS/Opta match-id override")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--yes", action="store_true", help="retained for CLI compatibility")
    args = parser.parse_args()

    from src.dvms.loaders.fixtures import resolve_fixture, resolve_fixture_for_match
    from src.dvms.preprocess import is_preprocessed, preprocess_fixture
    from src.report import impect_cafcdb_source, metrics
    from src.report.render_combined import FixtureMismatchError, _assert_same_fixture, render_report

    try:
        events = impect_cafcdb_source.load_match_events(args.impect_match_id)
        meta = metrics.match_meta(events)
        fixture = (
            resolve_fixture(args.dvms_match_id)
            if args.dvms_match_id
            else resolve_fixture_for_match(meta.home_team, meta.away_team, meta.kickoff)
        )
        if fixture is None:
            raise LookupError("No matching DVMS fixture was found")
        _assert_same_fixture(meta, fixture)
    except (FixtureMismatchError, LookupError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not is_preprocessed(fixture.opta_match_id):
        preprocess_fixture(fixture.fixture_id, fixture.opta_match_id)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = render_report(
        args.impect_match_id,
        fixture.opta_match_id,
        output_dir=args.output_dir,
        formats=("pdf",),
    )
    rendered = outputs["pdf"]
    final_name = rendered.name.replace("post_match_report_", "expanded_analyst_report_", 1)
    final_path = rendered.with_name(final_name)
    rendered.replace(final_path)
    print(f"Wrote PDF: {final_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
