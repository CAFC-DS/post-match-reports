import pandas as pd

from src.report.expanded import working
from src.report.expanded.working import STAT_ROWS_EXPANDED

CHA, OPP = "Charlton Athletic", "Lincoln City"


def _stats():
    keys = {key for _, key, _, _, _ in STAT_ROWS_EXPANDED}
    stats = pd.DataFrame({k: [10.0, 10.0] for k in keys}, index=[CHA, OPP])
    stats.loc[:, "possession_pct"] = [57.3, 42.7]
    return stats


def _baseline():
    return pd.Series({b: 50.0 for _, _, _, b, _ in STAT_ROWS_EXPANDED if b})


def test_tracked_possession_row_is_labelled_and_drops_the_pass_share_baseline():
    row = working._stat_rows_expanded(_stats(), _baseline(), CHA, OPP, CHA, possession_tracked=True)[0]
    assert row["label"] == "Possession (tracked)"
    assert row["baseline"] == "—" and row["shade"] is None
    assert row["home"].startswith("57")


def test_untracked_possession_row_keeps_its_baseline():
    row = working._stat_rows_expanded(_stats(), _baseline(), CHA, OPP, CHA)[0]
    assert row["label"] == "Possession" and row["baseline"] != "—"
