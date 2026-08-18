#!/usr/bin/env python3
"""Generate the canonical one-page post-match report.

    python generate_report_combined.py --impect-match-id 207019
    python generate_report_combined.py --impect-match-id 207019 --force-impect-only

DVMS is auto-matched by home team, away team and date. An explicit DVMS id is
an optional override and is still validated against the Impect fixture.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impect-match-id", type=int, required=True,
                        help="Impect matchId (CAFC_DB.IMPECT_RAW.EVENTS/MATCHES)")
    parser.add_argument("--dvms-match-id",
                        help="optional DVMS/Opta match-id override")
    parser.add_argument("--force-impect-only", action="store_true",
                        help="skip DVMS discovery and render the fallback layout")
    parser.add_argument("--output-dir", type=Path,
                        help="output directory (defaults to ./outputs)")
    parser.add_argument("--html-only", action="store_true")
    parser.add_argument("--pdf-only", action="store_true")
    args = parser.parse_args()

    from src.dvms.loaders.fixtures import resolve_fixture, resolve_fixture_for_match
    from src.dvms.preprocess import is_preprocessed, preprocess_fixture
    from src.report import impect_cafcdb_source, metrics
    from src.report.render_combined import FixtureMismatchError, _assert_same_fixture, render_report

    try:
        impect_events = impect_cafcdb_source.load_match_events(args.impect_match_id)
        impect_meta = metrics.match_meta(impect_events)
        fixture = None
        if not args.force_impect_only:
            fixture = (
                resolve_fixture(args.dvms_match_id)
                if args.dvms_match_id
                else resolve_fixture_for_match(
                    impect_meta.home_team, impect_meta.away_team, impect_meta.kickoff,
                )
            )
            if fixture is not None:
                _assert_same_fixture(impect_meta, fixture)
    except (FixtureMismatchError, LookupError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if fixture is None:
        print("DVMS unavailable or disabled; generating the Impect fallback.")
    elif not is_preprocessed(fixture.opta_match_id):
        print(f"cache not ready for {fixture.opta_match_id}; preprocessing "
              "(first run downloads ~28MB of tracking) ...")
        try:
            preprocess_fixture(fixture.fixture_id, fixture.opta_match_id)
        except Exception as exc:
            print(f"Warning: DVMS preprocessing failed; panel fallbacks will be used: {exc}",
                  file=sys.stderr)

    formats = ("html",) if args.html_only else (("pdf",) if args.pdf_only else ("html", "pdf"))
    kwargs = {"formats": formats, "force_impect_only": args.force_impect_only}
    if args.output_dir:
        kwargs["output_dir"] = args.output_dir
    outputs = render_report(
        args.impect_match_id,
        fixture.opta_match_id if fixture else None,
        **kwargs,
    )
    for fmt, path in outputs.items():
        print(f"Wrote {fmt.upper()}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
