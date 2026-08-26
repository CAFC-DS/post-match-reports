"""Entry point: the DVMS (Opta + Second Spectrum) set-piece report.

    python -m set_piece_report.run_dvms --match-id 2566913
    python -m set_piece_report.run_dvms --match-id 2566913 --theme dark
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    os.chdir(Path(__file__).resolve().parents[1])
    sys.path.insert(0, str(Path.cwd()))

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", required=True,
                        help="Opta match id (see: python -m src.dvms.cli list-fixtures)")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--html-only", action="store_true")
    parser.add_argument("--pdf-only", action="store_true")
    args = parser.parse_args()

    from src.dvms.loaders.fixtures import resolve_fixture
    from src.dvms.preprocess import is_preprocessed, preprocess_fixture

    fixture = resolve_fixture(args.match_id)
    if not is_preprocessed(fixture.opta_match_id):
        print("preprocessing (first run downloads ~28MB of tracking) ...")
        preprocess_fixture(fixture.fixture_id, fixture.opta_match_id)

    from set_piece_report.render_dvms import build_report

    formats = (("html",) if args.html_only
               else (("pdf",) if args.pdf_only else ("html", "pdf")))
    outputs = build_report(fixture.opta_match_id, formats=formats, theme=args.theme)
    for fmt, path in outputs.items():
        print(f"Wrote {fmt.upper()}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
