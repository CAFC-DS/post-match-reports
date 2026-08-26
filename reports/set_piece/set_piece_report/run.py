"""CLI entry point for the single-match set-piece report.

Run from anywhere — the script pins the working directory to the
``full-season-analysis`` project root so the shared connection layer finds
``.env``, ``config/tables.yml`` and the cached parquet extracts.

Examples
--------
    # default fixture: Swansea City v Charlton Athletic, 2 May 2026 (Championship 25/26)
    /opt/anaconda3/bin/python set_piece_report/run.py

    # any fixture by IMPECT matchId
    python set_piece_report/run.py --match-id 206675

    # HTML only, force a Snowflake repull
    python set_piece_report/run.py --html-only --refresh
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)                      # relative paths in QueryRunner resolve here
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from set_piece_report.render import DEFAULT_OUTPUT_DIR, build_report  # noqa: E402

# Charlton Athletic away at Swansea City, 2 May 2026 (Championship 2025/26).
DEFAULT_MATCH_ID = 207019


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a one-page set-piece report for a single match.")
    parser.add_argument("--match-id", type=int, default=DEFAULT_MATCH_ID, help="IMPECT matchId (default: Swansea v Charlton, 2 May 2026)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--html-only", action="store_true", help="Generate HTML only")
    parser.add_argument("--pdf-only", action="store_true", help="Generate PDF only")
    parser.add_argument("--refresh", action="store_true", help="Force a fresh pull from Snowflake instead of the parquet cache")
    parser.add_argument(
        "--source", choices=["staging", "cafcdb"], default="staging",
        help="Impect event source: IMPECT_EVENTS_STAGING (staging, default) or "
             "CAFC_DB.IMPECT_RAW for fixtures not yet loaded into staging (cafcdb)",
    )
    parser.add_argument(
        "--corner-style", choices=["hybrid", "zones", "both"], default="hybrid",
        help="Attacking-corner graphic: arrows over danger zones (hybrid), a target-zone grid (zones), or both files (both)",
    )
    parser.add_argument(
        "--theme", choices=["light", "dark", "both"], default="light",
        help="Colour theme: cream editorial (light), charcoal (dark), or both files (both)",
    )
    parser.add_argument(
        "--tables", choices=["team", "players", "both"], default="team",
        help="Bottom tables: aggregate first-contact by team (team), first-contact winners by player (players), or both files (both)",
    )
    args = parser.parse_args()

    if args.pdf_only:
        formats: tuple[str, ...] = ("pdf",)
    elif args.html_only:
        formats = ("html",)
    else:
        formats = ("html", "pdf")

    styles = ["hybrid", "zones"] if args.corner_style == "both" else [args.corner_style]
    themes = ["light", "dark"] if args.theme == "both" else [args.theme]
    tables = ["team", "players"] if args.tables == "both" else [args.tables]

    print("=" * 64)
    print("Single-match Set-Piece Report")
    print("=" * 64)
    print(f"  matchId : {args.match_id}")
    print(f"  formats : {', '.join(formats)}")
    print(f"  corners : {', '.join(styles)}")
    print(f"  theme   : {', '.join(themes)}")
    print(f"  tables  : {', '.join(tables)}")
    print(f"  source  : {'Snowflake (refresh)' if args.refresh else 'cached parquet (data/processed)'}")
    print()

    print("Done. Output files:")
    for style in styles:
        for theme in themes:
            for tbl in tables:
                outputs = build_report(
                    args.match_id,
                    output_dir=args.output_dir,
                    formats=formats,
                    refresh=args.refresh,
                    corner_style=style,
                    theme=theme,
                    tables_style=tbl,
                    source=args.source,
                )
                for fmt, path in outputs.items():
                    print(f"  • [{style}/{theme}/{tbl}] {fmt.upper()}: {path}")


if __name__ == "__main__":
    main()
