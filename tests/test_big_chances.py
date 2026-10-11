import pandas as pd

from src.report.expanded.working import _big_chances


def _shots():
    rows = []
    for i, (xg, cat) in enumerate([(0.5, "On target"), (0.4, "Other"), (0.3, "Blocked"), (0.2, "Other"),
                                   (0.15, "Other"), (0.1, "Other"), (0.03, "Goal")]):
        rows.append({"squadName": "A", "playerName": f"P Q{i}", "SHOT_XG": xg, "POSTSHOT_XG": xg,
                     "category": cat, "gameTime": f"{10 + i}:00", "gameTimeInSec": 600 + 60 * i})
    return pd.DataFrame(rows)


def test_low_xg_goal_is_always_listed_and_rows_are_in_match_order():
    rows = _big_chances(_shots(), "A")
    assert len(rows) == 6
    assert any(r["result"] == "GOAL" and r["xg"] == 0.03 for r in rows)
    assert [r["minute"] for r in rows] == sorted(r["minute"] for r in rows)


def test_all_goals_kept_even_beyond_the_limit():
    shots = pd.concat([_shots()] * 1, ignore_index=True)
    shots["category"] = "Goal"
    assert len(_big_chances(shots, "A")) == 7
