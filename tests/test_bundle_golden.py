from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader


GOLDEN_DIR = Path(__file__).parent / "golden"


def _assert_fixture_pdf(filename: str, pages: int, minimum_images: int):
    path = GOLDEN_DIR / filename
    reader = PdfReader(path)
    assert len(reader.pages) == pages
    text = " ".join((page.extract_text() or "") for page in reader.pages[:2])
    assert "West Ham United" in text
    assert "Charlton Athletic" in text
    with fitz.open(path) as document:
        assert len(document[0].get_images(full=True)) >= minimum_images


def test_board_report_golden_contract():
    _assert_fixture_pdf(
        "board_post_match_report_West_Ham_United_v_Charlton_Athletic_22-08-2026.pdf",
        pages=1,
        minimum_images=2,
    )


def test_set_piece_player_report_golden_contract():
    _assert_fixture_pdf(
        "set_piece_report_West_Ham_United_v_Charlton_Athletic_22-08-2026_players.pdf",
        pages=1,
        minimum_images=2,
    )
