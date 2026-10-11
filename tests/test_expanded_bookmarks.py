import pymupdf as fitz

from src.report.expanded import bookmarks
from src.report.expanded.pages import PAGE_TITLES, build_page_plan, build_toc, section_info


def test_toc_has_a_section_per_divider_with_content_pages_beneath_it():
    plan = build_page_plan(True)
    toc = build_toc(plan, section_info("Charlton Athletic", True, True))
    assert toc[0] == [1, "Contents", 1]
    level1 = [t for t in toc if t[0] == 1]
    assert [t[1] for t in level1] == ["Contents", "Overview", "In Possession", "Out of Possession", "Transition", "Player Performances"]
    assert len(toc) == plan["total"] and [t[2] for t in toc] == list(range(1, plan["total"] + 1))
    assert all(t[1] != key for t in toc for key in plan["order"] if key in PAGE_TITLES)     # titles, not keys
    assert [1, "In Possession", plan["pages"]["div_ip"]["n"]] in toc


def test_untracked_and_sheetless_layouts_have_titles_for_every_page():
    for tracked, sheet in ((False, True), (True, False)):
        plan = build_page_plan(tracked, sheet)
        toc = build_toc(plan, section_info("Charlton Athletic", tracked, sheet))
        assert len(toc) == plan["total"] and all(isinstance(t[1], str) and t[1] for t in toc)


def test_add_navigation_writes_an_outline_and_links_the_contents_rows(tmp_path):
    path = tmp_path / "report.pdf"
    doc = fitz.open()
    contents = doc.new_page(width=842, height=595)
    contents.insert_text((60, 100), "Overview", fontsize=14)
    contents.insert_text((60, 160), "In Possession", fontsize=14)
    for _ in range(3):
        doc.new_page(width=842, height=595)
    doc.save(path)
    doc.close()
    toc = [[1, "Contents", 1], [1, "Overview", 2], [2, "Match summary", 3], [1, "In Possession", 4]]
    bookmarks.add_navigation(path, toc, [{"title": "Overview", "first": 2}, {"title": "In Possession", "first": 4},
                                         {"title": "Missing title", "first": 3}])
    with fitz.open(path) as out:
        assert out.get_toc() == toc
        links = out[0].get_links()
        assert sorted(link["page"] for link in links) == [1, 3]           # zero-based targets; the missing title adds none
        assert out.page_count == 4
    assert not list(tmp_path.glob("*.nav.pdf"))
