#!/usr/bin/env python3
"""Entry point: generate the combined Impect + DVMS board post-match report.

    python generate_report_combined.py --impect-match-id 207019 --dvms-match-id 2566913
    python generate_report_combined.py --impect-match-id 207019 --dvms-match-id 2566913 --html-only

Both ids must refer to the same real-world fixture — the tool aborts with a
clear error if the team names or kickoff date disagree between the two
sources (see src.report.render_combined._assert_same_fixture).
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impect-match-id", type=int, required=True,
                        help="IMPECT_EVENTS_STAGING matchId")
    parser.add_argument("--dvms-match-id", required=True,
                        help="DVMS/Opta match id (see: python -m src.dvms.cli list-fixtures)")
    parser.add_argument("--refresh", action="store_true",
                        help="Bypass the local parquet cache and repull Impect events from Snowflake.")
    parser.add_argument("--html-only", action="store_true")
    parser.add_argument("--pdf-only", action="store_true")
    args = parser.parse_args()

    from src.db.query_runner import QueryRunner
    from src.dvms.loaders.fixtures import resolve_fixture
    from src.dvms.preprocess import is_preprocessed, preprocess_fixture
    from src.report import metrics
    from src.report.render_combined import FixtureMismatchError, _assert_same_fixture, render_report

    fixture = resolve_fixture(args.dvms_match_id)

    # Validate that the two ids refer to the same real-world fixture BEFORE
    # paying for the (potentially multi-minute, ~28MB download) DVMS
    # preprocessing step below — a mistyped --impect-match-id should fail
    # fast, not after preprocessing has already run.
    try:
        impect_events = QueryRunner().load_match_events(args.impect_match_id, refresh=args.refresh)
        impect_meta = metrics.match_meta(impect_events)
        _assert_same_fixture(impect_meta, fixture)
    except (FixtureMismatchError, LookupError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not is_preprocessed(fixture.opta_match_id):
        print(f"cache not ready for {fixture.opta_match_id}; preprocessing "
              "(first run downloads ~28MB of tracking) ...")
        preprocess_fixture(fixture.fixture_id, fixture.opta_match_id)

    formats = ("html",) if args.html_only else (("pdf",) if args.pdf_only else ("html", "pdf"))
    outputs = render_report(args.impect_match_id, fixture.opta_match_id, formats=formats, refresh=args.refresh)
    for fmt, path in outputs.items():
        print(f"Wrote {fmt.upper()}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
