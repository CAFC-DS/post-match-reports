"""Cache and preprocessing CLI for the DVMS data package.

    python -m src.dvms.cli list-fixtures
    python -m src.dvms.cli prefetch    --match-id 2566913
    python -m src.dvms.cli preprocess  --match-id 2566913 [--hz 5] [--refresh]
    python -m src.dvms.cli preprocess  --all
    python -m src.dvms.cli validate-sync --match-id 2566913
    python -m src.dvms.cli cache-status
"""

from __future__ import annotations

import argparse
import sys


def _fixture(match_id: str):
    from .loaders.fixtures import resolve_fixture
    return resolve_fixture(match_id)


def cmd_list_fixtures(_args) -> int:
    from .loaders.fixtures import list_fixtures
    df = list_fixtures()
    for _, r in df.iterrows():
        print(f"{str(r['OPTA_MATCH_ID']).lstrip('g'):>9}  "
              f"{str(r['MATCH_DATE'])[:10]}  "
              f"{r['HOME_TEAM_NAME']} {r['HOME_SCORE']}-{r['AWAY_SCORE']} "
              f"{r['AWAY_TEAM_NAME']}")
    return 0


def cmd_prefetch(args) -> int:
    from .loaders import assets, positional
    fx = _fixture(args.match_id)
    for subtype in (20, 21, 40, 42, 43):
        assets.fetch_asset_text(fx.fixture_id, fx.opta_match_id, subtype)
        print(f"  subtype {subtype}: cached")
    path = positional.fetch_tracking(fx.fixture_id, fx.opta_match_id)
    print(f"  tracking: {path} ({path.stat().st_size / 1e6:.0f} MB)")
    return 0


def cmd_preprocess(args) -> int:
    from .loaders.fixtures import list_fixtures
    from .preprocess import preprocess_fixture

    if args.all:
        targets = [
            (str(r["FIXTURE_ID"]), str(r["OPTA_MATCH_ID"]).lstrip("g"))
            for _, r in list_fixtures().iterrows()
        ]
    else:
        fx = _fixture(args.match_id)
        targets = [(fx.fixture_id, fx.opta_match_id)]

    failures = 0
    for fixture_id, match_id in targets:
        print(f"preprocessing {match_id} ...", flush=True)
        try:
            d = preprocess_fixture(fixture_id, match_id, every_n=args.every_n,
                                   refresh=args.refresh)
        except LookupError as exc:
            # A fixture without staged tracking (or missing an inline asset)
            # shouldn't sink the whole batch — report and move on.
            print(f"  SKIPPED: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(f"  artifacts in {d}")
    if failures:
        print(f"{failures} fixture(s) skipped", file=sys.stderr)
    return 0


def cmd_validate_sync(args) -> int:
    from .loaders import assets
    from .parsers.f24 import parse_f24
    from .parsers.ss_meta import parse_ss_metadata
    from .preprocess import load_artifact
    from .sync import validate_sync

    fx = _fixture(args.match_id)
    f24 = parse_f24(assets.fetch_asset_text(fx.fixture_id, fx.opta_match_id, 20))
    meta = parse_ss_metadata(assets.fetch_asset_text(fx.fixture_id, fx.opta_match_id, 40))
    tracking = load_artifact(fx.opta_match_id, "frames_5hz.parquet")

    report = validate_sync(f24.events, tracking, meta)
    s = report.attrs["summary"]
    print(f"{fx.home_team} v {fx.away_team}: n={s['n']}  "
          f"median={s['median']:.2f}m  p90={s['p90']:.2f}m")
    # Gate at 3m: on the 5Hz artifacts a ball at pass speed moves ~2-3m
    # between kept frames, so a correctly-synced match lands at ~2.5m median
    # (verified per-period and per-event-type on real data); a wrong period
    # offset or axis flip shows up an order of magnitude larger.
    if s["n"] and s["median"] >= 3.0:
        print("WARNING: median ball error >= 3m — check period offsets/axes",
              file=sys.stderr)
        return 1
    return 0


def cmd_cache_status(_args) -> int:
    from .loaders.cache import cache_root, cache_status
    rows = cache_status()
    if not rows:
        print(f"cache empty ({cache_root()})")
        return 0
    total = 0
    for r in rows:
        total += r["total_bytes"]
        print(f"{r['match_id']:>9}  {r['total_bytes'] / 1e6:8.1f} MB  "
              f"{len(r['files'])} files")
    print(f"{'total':>9}  {total / 1e6:8.1f} MB  ({cache_root()})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.dvms.cli", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-fixtures")

    sp = sub.add_parser("prefetch")
    sp.add_argument("--match-id", required=True)

    sp = sub.add_parser("preprocess")
    sp.add_argument("--match-id")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--hz", dest="every_n", type=int, default=5,
                    help="keep every Nth frame (5 => 5Hz from 25fps)")
    sp.add_argument("--refresh", action="store_true")

    sp = sub.add_parser("validate-sync")
    sp.add_argument("--match-id", required=True)

    sub.add_parser("cache-status")

    args = p.parse_args(argv)
    if args.cmd == "preprocess" and not args.all and not args.match_id:
        p.error("preprocess needs --match-id or --all")

    return {
        "list-fixtures": cmd_list_fixtures,
        "prefetch": cmd_prefetch,
        "preprocess": cmd_preprocess,
        "validate-sync": cmd_validate_sync,
        "cache-status": cmd_cache_status,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
