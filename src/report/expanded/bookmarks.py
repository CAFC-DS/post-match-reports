"""PDF bookmarks (the sidebar outline) and clickable contents rows, added after Chrome writes the PDF."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf as fitz


def add_navigation(pdf_path: Path | str, toc: list[list[Any]], contents: list[dict[str, Any]]) -> None:
    """Write ``toc`` as the PDF outline and turn each contents-page row into a link to its section.

    The contents page is page 1: for every row the section title is located on the page and a link is
    laid over that line (title through the right margin) pointing at the section's first page."""
    path = Path(pdf_path)
    with fitz.open(path) as doc:
        doc.set_toc([[lvl, title, page] for lvl, title, page in toc])
        if doc.page_count:
            page = doc[0]
            for row in contents:
                for rect in page.search_for(str(row["title"]))[:1]:
                    span = fitz.Rect(page.rect.x0 + 20, rect.y0 - 3, page.rect.x1 - 20, rect.y1 + 3)
                    page.insert_link({"kind": fitz.LINK_GOTO, "from": span, "page": int(row["first"]) - 1,
                                      "to": fitz.Point(0, 0)})
        tmp = path.with_suffix(".nav.pdf")
        doc.save(tmp, garbage=3, deflate=True)
    tmp.replace(path)
