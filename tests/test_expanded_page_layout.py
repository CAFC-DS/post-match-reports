"""Real template pages rendered with match shapes that once overflowed in production."""
import pandas as pd
import pytest
from jinja2 import ChainableUndefined, Environment

from src.report.expanded import _fonts, browser, gamestate as gs, layout_check, pages, transition
from src.report.expanded.working import TEMPLATES_DIR

from tests.test_expanded_gamestate import AWAY, HOME, _events


@pytest.fixture(scope="module")
def chrome():
    try:
        return browser.resolve_chrome(None)
    except browser.BrowserConfigurationError:
        pytest.skip("no Chrome available")


def _render(*markers: str, **ctx) -> str:
    """The template's head and macros plus only the lines containing ``markers``."""
    lines = (TEMPLATES_DIR / "expanded.html.j2").read_text(encoding="utf-8").split("\n")
    head = lines[:next(i for i, l in enumerate(lines) if l.startswith("<section"))]
    body = [l for l in lines if any(m in l for m in markers)]
    env = Environment(undefined=ChainableUndefined, trim_blocks=True, lstrip_blocks=True)
    return env.from_string("\n".join(head + body + ["</body></html>"])).render(
        page_plan=pages.build_page_plan(True), subject=AWAY, opponent=HOME, team_order=[AWAY, HOME],
        subject_colour="#d01012", opponent_colour="#7d7869", font_faces_css=_fonts.embedded_css(), **ctx)


def test_game_state_page_fits_when_the_subject_led_drew_and_trailed(chrome):
    pressure = pd.DataFrame([dict(eventId=1, squadName=AWAY)])
    ctx = gs.gamestate_context(_events(), pressure, AWAY, HOME, 60.0)
    assert len(ctx["gamestate"]["states"]) + len(ctx["gamestate"]["other"]) == 7   # one more card than columns used to be
    html = _render("header('Game State & Phases'", **ctx)
    assert layout_check.find_overflow(html, chrome) == []


def test_defending_transition_fits_a_long_counter_press_surname(chrome):
    losses = pd.DataFrame({"x": [-30.0, 0.0, 30.0], "y": [-10.0, 0.0, 10.0], "xg": [0.0, .1, .3]})
    side = {"summary": "45 lost · 38% won back within 5 s · 1.84 xG conceded (6 shots)",
            "pitch": transition._pitch_map(losses, "#d01012"), "median": "6.4 s",
            "buckets": [{"label": l, "n": 9, "pct": 20} for l in ("under 3 s", "3–5 s", "5–10 s", "10–20 s", "not won back")],
            "counterpress": [{"name": n, "n": 5 - i} for i, n in enumerate(("Docherty", "Mitchell-Lawson", "Berry", "Ramsay"))],
            "rows": [{"n": i, "minute": "12'", "player": "Kaminski", "zone": "Middle third centre", "back": "not won back",
                      "shots": 1, "xg": .3} for i in range(1, 6)], "xg_max": .3}
    html = _render("{% macro tcard", "header('Defending Transition'", trans_defending={AWAY: side, HOME: side})
    assert layout_check.find_overflow(html, chrome) == []
