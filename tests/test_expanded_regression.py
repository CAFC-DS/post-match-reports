from pathlib import Path

from pypdf import PdfReader

from src.report.expanded.regression import compare_pdfs, normalized_pdf_sha256

GOLDEN = Path(__file__).parent / "golden" / (
    "expanded_analyst_report_West_Ham_United_v_Charlton_Athletic_22-08-2026.pdf"
)


def test_west_ham_golden_is_the_expected_report():
    reader = PdfReader(GOLDEN)
    assert len(reader.pages) == 16
    assert all(float(page.mediabox.width) > float(page.mediabox.height) for page in reader.pages)
    text = " ".join((page.extract_text() or "") for page in reader.pages)
    assert "West Ham United 1 - 2" in text
    assert "Charlton Athletic" in text
    assert "22/08/2026" in text
    assert "DEFENSIVE TRANSITION RESPONSE" in text


def test_metadata_only_changes_compare_exactly(tmp_path):
    candidate = tmp_path / "candidate.pdf"
    data = GOLDEN.read_bytes().replace(b"D:20260823144228", b"D:20260825150954")
    candidate.write_bytes(data)
    assert normalized_pdf_sha256(candidate) == normalized_pdf_sha256(GOLDEN)
    comparison = compare_pdfs(candidate, GOLDEN, exact=True)
    assert comparison.pages == 16
    assert comparison.mean_pixel_delta == 0
    assert comparison.exact_after_metadata_normalisation
