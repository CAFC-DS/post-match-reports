import pandas as pd

from src.report.expanded import summary as sm

CHA, OPP = "Charlton Athletic", "Cardiff City"


def _stats():
    return pd.DataFrame({"possession_pct": [41.0, 59.0], "shots": [6, 27], "shots_on_target": [3, 8],
                         "non_penalty_xg": [0.97, 2.40], "pass_accuracy_pct": [62.0, 79.0],
                         "won_ground_duels": [28, 20], "won_aerial_duels": [19, 10],
                         "opponent_half_regains": [37, 60]}, index=[CHA, OPP])


def _events():
    def goal(i, squad, name, t, period=1, action="GOAL", action_type="SHOT"):
        return dict(eventId=i, squadName=squad, playerName=name, action=action, actionType=action_type,
                    gameTime=f"{t}:00.000", gameTimeInSec=t * 60.0 if period == 1 else 10000.0 + (t - 45) * 60,
                    periodId=period, homeSquadName=OPP, awaySquadName=CHA)
    return pd.DataFrame([goal(1, OPP, "M Moylan", 7), goal(2, CHA, "C Campbell", 28),
                         goal(3, OPP, "M Moylan", 60, 2),
                         goal(4, CHA, "O Gal", 80, 2, action="OWN_GOAL", action_type="OWN_GOAL")])


def test_score_and_scorers_count_goals_own_goals_and_half_time():
    out = sm.score_and_scorers(_events(), CHA, OPP)
    assert out["score"] == {CHA: 1, OPP: 3}                  # the own goal by a Charlton player counts for Cardiff
    assert out["half_time"] == {CHA: 1, OPP: 1}
    assert [s["who"] for s in out["scorers"][OPP]] == ["Moylan", "Moylan", "Gal (og)"]
    assert [s["minute"] for s in out["scorers"][OPP]] == ["7'", "60'", "80'"]       # same flooring as the rest of the report
    assert out["home"] == OPP


def test_key_numbers_show_both_teams_with_duels_as_a_share_of_all_duels():
    rows = {r["label"]: r for r in sm.key_numbers(_stats(), CHA, OPP)}
    assert rows["Possession"] == {"label": "Possession", "subject": "41%", "opponent": "59%"}
    assert rows["Shots (on target)"]["opponent"] == "27 (8)"
    assert rows["Duels won"]["subject"] == "61%" and rows["Duels won"]["opponent"] == "39%"


def test_how_it_went_reads_the_game_state_xg_and_sharpest_spell():
    gs = {"states": [{"key": "level", "minutes": 7.0}, {"key": "trailing", "minutes": 89.0}],
          "first_goal": (7.2, OPP, "M Moylan"),
          "other": [{"label": "First half", "xg_for": .48, "xg_against": 1.53, "pressures_per_min": 2.75},
                    {"label": "Second half", "xg_for": .49, "xg_against": .87, "pressures_per_min": 1.44},
                    {"label": "Before the first substitution (45')", "xg_for": .48, "xg_against": 1.4},
                    {"label": "After the first substitution", "xg_for": .49, "xg_against": 1.0}],
          "periods": [{"label": "0–15'", "xg": (0.24, 0.18)}, {"label": "30–45'", "xg": (0.0, 0.83)}]}
    lines = sm.how_it_went(gs, _stats(), CHA, OPP)
    assert lines[0] == "Charlton Athletic spent 7 minutes level and 89 minutes trailing and never led."
    assert lines[1] == "First goal: Moylan for Cardiff City after 7 minutes."
    assert "0.97 xG from 6 shots (3 on target)" in lines[2] and "2.40 xG from 27 (8 on target)" in lines[2]
    assert "30–45'" in lines[3] and "Cardiff City created 0.83 xG" in lines[3]
    assert any(l.startswith("By half, xG was 0.48–1.53 in the first and 0.49–0.87 in the second") for l in lines)
    assert any(l.startswith("45' was the first change: xG was 0.48–1.40 before it and 0.49–1.00 after it") for l in lines)
    assert "Charlton Athletic made 41% of the passes." in lines
    assert not any(w in " ".join(lines).lower() for w in ("should", "must", "coach", "needs to", "improve"))


def test_against_the_season_ranks_by_percentile_and_flips_lower_is_better():
    baseline = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [10.0, 20.0, 30.0, 40.0]})
    wheel = [("x", "a", "Alpha", True), ("x", "b", "Beta", False)]
    out = sm.against_the_season({"a": 4.5, "b": 45.0}, baseline, wheel, CHA, n=1)
    assert out["above"][0].startswith("Alpha: 4 against an average of 2") and "100th percentile" in out["above"][0]
    assert out["below"][0].startswith("Beta: 45") and "0th percentile" in out["below"][0]


def test_standouts_rank_players_by_share_of_better_than_both_averages():
    cell = lambda v: {"text": "1", "v_both": v}
    page = {"label": "Wingers", "columns": [{"name": "Campbell", "rated": True, "minutes": 90},
                                           {"name": "Alli", "rated": True, "minutes": 45},
                                           {"name": "Cameo", "rated": False, "minutes": 5}],
            "rows": [{"label": "Goals", "cells": [cell("up"), cell("down"), cell("")]},
                     {"label": "Shots", "cells": [cell("up"), cell("up"), cell("")]},
                     {"label": "Key passes", "cells": [cell("down"), cell("down"), cell("")]}]}
    out = sm.standouts([page], n=2)
    assert [p["name"] for p in out] == ["Campbell", "Alli"]
    assert out[0]["ups"] == 2 and out[0]["rated"] == 3 and out[0]["best"] == ["Goals 1", "Shots 1"]
    assert sm.standouts([]) == []
