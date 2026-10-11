from pathlib import Path

from pypdf import PdfReader

from src.report.expanded.pages import build_page_plan
from src.report.expanded.regression import compare_pdfs, normalized_pdf_sha256

GOLDEN = Path(__file__).parent / "golden" / (
    "expanded_analyst_report_Cardiff_City_v_Charlton_Athletic_19-09-2026.pdf"
)


def test_cardiff_golden_is_the_expected_report():
    reader = PdfReader(GOLDEN)
    assert len(reader.pages) == build_page_plan(True)["total"] == 25
    assert all(float(page.mediabox.width) > float(page.mediabox.height) for page in reader.pages)
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)
    assert "Cardiff City 3 - 1" in text
    assert "Charlton Athletic" in text
    assert "19/09/2026" in text
    # Chrome's letter-spaced headings are extracted inconsistently by pypdf across platforms; these
    # page-level labels are stable.
    assert "ball losses and fouls: lower is better" in text


def test_metadata_only_changes_compare_exactly(tmp_path):
    candidate = tmp_path / "candidate.pdf"
    data = GOLDEN.read_bytes().replace(b"D:20261011152627", b"D:20261013150954")
    candidate.write_bytes(data)
    assert normalized_pdf_sha256(candidate) == normalized_pdf_sha256(GOLDEN)
    comparison = compare_pdfs(candidate, GOLDEN, exact=True)
    assert comparison.pages == 25
    assert comparison.mean_pixel_delta == 0
    assert comparison.exact_after_metadata_normalisation
