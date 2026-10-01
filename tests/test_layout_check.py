import os

import pytest

from src.report.expanded import layout_check, working

PAGE = """<!doctype html><html><head><style>
@page{size:A4 landscape;margin:0}body{margin:0}
.sheet{width:297mm;height:100mm;padding:5mm;overflow:hidden;display:flex;flex-direction:column;box-sizing:border-box}
.card{border:1px solid #888;overflow:hidden;height:30mm;padding:2mm}
</style></head><body>%s</body></html>"""


@pytest.fixture(scope="module")
def chrome():
    try:
        return working.resolve_chrome(None)
    except working.BrowserConfigurationError:
        pytest.skip("no Chrome available")


def test_a_page_that_fits_has_no_problems(chrome):
    html = PAGE % '<section class="sheet"><div class="card"><h2>Fits</h2><p>short</p></div></section>'
    assert layout_check.find_overflow(html, chrome) == []


def test_a_tall_card_and_an_overfull_sheet_are_reported_with_their_page_numbers(chrome):
    tall = "<p>line</p>" * 40
    html = PAGE % ('<section class="sheet"><div class="card"><h2>Fine</h2></div></section>'
                   f'<section class="sheet"><div class="card"><h2>Too tall</h2>{tall}</div>'
                   f'<div class="card">a</div><div class="card">b</div><div class="card">c</div></section>')
    problems = layout_check.find_overflow(html, chrome)
    assert {p["page"] for p in problems} == {2}
    assert any(p["kind"] == "card" and p["what"].startswith("Too tall") for p in problems)
    assert any(p["kind"] == "sheet" for p in problems)
    text = layout_check.describe(problems)
    assert "page 2" in text and "Too tall" in text


def test_describe_lists_every_problem():
    text = layout_check.describe([{"page": 3, "kind": "card", "what": "Key numbers", "over_px": 4},
                                  {"page": 21, "kind": "sheet", "what": "DIV.foot", "over_px": 9}])
    assert text == "page 3: card 'Key numbers' overflows by 4px; page 21: sheet 'DIV.foot' overflows by 9px"
