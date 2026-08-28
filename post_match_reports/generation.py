from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
from pypdf import PdfReader

from src.dvms.loaders.fixtures import resolve_fixture
from src.dvms.preprocess import is_preprocessed, preprocess_fixture
from src.report import impect_cafcdb_source, metrics
from src.report.expanded.working import render_report as render_expanded
from src.report.render_combined import render_report as render_board


ROOT = Path(__file__).resolve().parents[1]
SET_PIECE_ROOT = ROOT / "reports" / "set_piece"
EXPECTED_PAGES = {"expanded": 16, "board": 1, "set_piece": 1}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_pdf(kind: str, path: Path, home: str, away: str) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{kind} report was not created: {path}")
    reader = PdfReader(path)
    pages = len(reader.pages)
    if pages != EXPECTED_PAGES[kind]:
        raise RuntimeError(f"{kind} report has {pages} pages; expected {EXPECTED_PAGES[kind]}")
    text = " ".join((page.extract_text() or "") for page in reader.pages[:2])
    for team in (home, away):
        if team not in text:
            raise RuntimeError(f"{kind} report does not identify {team}")
    with fitz.open(path) as document:
        if len(document[0].get_images(full=True)) < 2:
            raise RuntimeError(f"{kind} report page 1 does not contain both club badges")
    return {
        "kind": kind,
        "path": str(path.resolve()),
        "filename": path.name,
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def generate_bundle(
    impect_match_id: int,
    dvms_match_id: str,
    output_dir: Path,
    chrome_bin: str | None = None,
) -> dict:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_pdf in output_dir.glob("*.pdf"):
        stale_pdf.unlink()

    print(f"[generate] loading Impect events for match {impect_match_id}", flush=True)
    events = impect_cafcdb_source.load_match_events(impect_match_id)
    meta = metrics.match_meta(events)
    print(f"[generate] resolving DVMS fixture for match {dvms_match_id}", flush=True)
    fixture = resolve_fixture(dvms_match_id)
    if not is_preprocessed(fixture.opta_match_id):
        print(f"[generate] preprocessing DVMS tracking data for {fixture.opta_match_id}", flush=True)
        preprocess_fixture(fixture.fixture_id, fixture.opta_match_id)
        print("[generate] DVMS preprocessing complete", flush=True)

    def slug(value: str) -> str:
        import re
        return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")

    expanded_path = output_dir / (
        f"expanded_analyst_report_{slug(meta.home_team)}_v_{slug(meta.away_team)}_"
        f"{meta.kickoff:%d-%m-%Y}.pdf"
    )
    print("[generate] rendering expanded analyst report", flush=True)
    render_expanded(
        impect_match_id,
        fixture.opta_match_id,
        expanded_path,
        chrome_bin=chrome_bin,
    )
    print(f"[generate] expanded report written to {expanded_path}", flush=True)

    print("[generate] rendering board report", flush=True)
    board_outputs = render_board(
        impect_match_id,
        fixture.opta_match_id,
        output_dir=output_dir,
        formats=("pdf",),
        strict_data=True,
    )
    print(f"[generate] board report written to {board_outputs['pdf']}", flush=True)

    print("[generate] rendering set-piece report", flush=True)
    before = set(output_dir.glob("*.pdf"))
    command = [
        sys.executable,
        "set_piece_report/run.py",
        "--match-id", str(impect_match_id),
        "--output-dir", str(output_dir),
        "--pdf-only",
        "--source", "cafcdb",
        "--corner-style", "hybrid",
        "--theme", "light",
        "--tables", "players",
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    subprocess.run(command, cwd=SET_PIECE_ROOT, env=environment, check=True)
    created = set(output_dir.glob("*.pdf")) - before
    set_piece = [path for path in created if path.name.endswith("set_piece_report_players.pdf")]
    if len(set_piece) != 1:
        raise RuntimeError(f"Expected one set-piece PDF, found: {sorted(map(str, set_piece))}")
    print(f"[generate] set-piece report written to {set_piece[0]}", flush=True)

    print("[generate] validating generated PDFs", flush=True)
    reports = [
        _validate_pdf("expanded", expanded_path, meta.home_team, meta.away_team),
        _validate_pdf("board", board_outputs["pdf"], meta.home_team, meta.away_team),
        _validate_pdf("set_piece", set_piece[0], meta.home_team, meta.away_team),
    ]
    return {
        "schema_version": 1,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fixture": {
            "impect_match_id": impect_match_id,
            "dvms_match_id": fixture.opta_match_id,
            "fixture_id": fixture.fixture_id,
            "kickoff_utc": meta.kickoff.isoformat(),
            "home_team": meta.home_team,
            "away_team": meta.away_team,
            "home_goals": meta.home_goals,
            "away_goals": meta.away_goals,
        },
        "reports": reports,
    }


def write_manifest(manifest: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
