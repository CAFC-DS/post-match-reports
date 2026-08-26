"""Structural, textual and visual regression checks for expanded-report PDFs."""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import fitz
import numpy as np
from pypdf import PdfReader

_DATE_RE = re.compile(rb"/(CreationDate|ModDate) \(D:\d{14}[+-]\d{2}'\d{2}'\)")
_SPACE_RE = re.compile(r"\s+")


def normalized_pdf_bytes(path: Path | str) -> bytes:
    """Return PDF bytes with volatile Chrome timestamps normalised."""
    data = Path(path).read_bytes()
    return _DATE_RE.sub(lambda match: b"/" + match.group(1) + b" (D:00000000000000+00'00')", data)


def normalized_pdf_sha256(path: Path | str) -> str:
    return hashlib.sha256(normalized_pdf_bytes(path)).hexdigest()


def _normalised_text(page) -> str:
    return _SPACE_RE.sub(" ", page.extract_text() or "").strip()


@dataclass(frozen=True)
class Comparison:
    pages: int
    mean_pixel_delta: float
    exact_after_metadata_normalisation: bool


def compare_pdfs(candidate: Path | str, golden: Path | str, *,
                 max_mean_pixel_delta: float = 0.01, exact: bool = False) -> Comparison:
    """Compare two 16-page A4-landscape reports.

    Pixel delta is the mean absolute RGB difference on a 0..1 scale at
    96dpi. Text and page geometry must match exactly; ``exact`` additionally
    requires identical PDF bytes after normalising Chrome timestamps.
    """
    candidate = Path(candidate)
    golden = Path(golden)
    candidate_reader = PdfReader(candidate)
    golden_reader = PdfReader(golden)
    if len(candidate_reader.pages) != 16 or len(golden_reader.pages) != 16:
        raise AssertionError(
            f"Expected 16 pages; candidate={len(candidate_reader.pages)}, "
            f"golden={len(golden_reader.pages)}"
        )

    for index, (candidate_page, golden_page) in enumerate(
        zip(candidate_reader.pages, golden_reader.pages), start=1
    ):
        candidate_size = (float(candidate_page.mediabox.width), float(candidate_page.mediabox.height))
        golden_size = (float(golden_page.mediabox.width), float(golden_page.mediabox.height))
        if candidate_size != golden_size or candidate_size[0] <= candidate_size[1]:
            raise AssertionError(
                f"Page {index} geometry differs or is not landscape: "
                f"candidate={candidate_size}, golden={golden_size}"
            )
        if _normalised_text(candidate_page) != _normalised_text(golden_page):
            raise AssertionError(f"Page {index} extracted text differs from the golden")

    pixel_deltas: list[float] = []
    with fitz.open(candidate) as candidate_doc, fitz.open(golden) as golden_doc:
        matrix = fitz.Matrix(96 / 72, 96 / 72)
        for index, (candidate_page, golden_page) in enumerate(
            zip(candidate_doc, golden_doc), start=1
        ):
            candidate_pix = candidate_page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
            golden_pix = golden_page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
            if (candidate_pix.width, candidate_pix.height) != (golden_pix.width, golden_pix.height):
                raise AssertionError(f"Page {index} raster dimensions differ")
            candidate_pixels = np.frombuffer(candidate_pix.samples, dtype=np.uint8)
            golden_pixels = np.frombuffer(golden_pix.samples, dtype=np.uint8)
            pixel_deltas.append(float(np.abs(candidate_pixels.astype(np.int16) - golden_pixels).mean() / 255))

    mean_delta = float(np.mean(pixel_deltas))
    if mean_delta > max_mean_pixel_delta:
        raise AssertionError(
            f"Mean rendered pixel delta {mean_delta:.6f} exceeds {max_mean_pixel_delta:.6f}"
        )
    exact_match = normalized_pdf_sha256(candidate) == normalized_pdf_sha256(golden)
    if exact and not exact_match:
        raise AssertionError("PDF bytes differ after normalising CreationDate and ModDate")
    return Comparison(16, mean_delta, exact_match)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("golden", type=Path)
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--max-mean-pixel-delta", type=float, default=0.01)
    args = parser.parse_args()
    result = compare_pdfs(
        args.candidate,
        args.golden,
        max_mean_pixel_delta=args.max_mean_pixel_delta,
        exact=args.exact,
    )
    print(
        f"Matched {result.pages} pages; mean pixel delta={result.mean_pixel_delta:.6f}; "
        f"exact={result.exact_after_metadata_normalisation}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
