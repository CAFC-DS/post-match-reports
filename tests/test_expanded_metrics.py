import pandas as pd

from src.report import metrics
from src.report.expanded import working
from src.report import impect_cafcdb_source


def test_duel_split_kpis_reports_type_share_and_most_involved():
    duels = pd.DataFrame(
        [
            ("Charlton", "AERIAL", "Lloyd Jones"),
            ("Charlton", "GROUND", "Lloyd Jones"),
            ("Charlton", "GROUND", "Conor Coventry"),
            ("Opponent", "GROUND", "Someone Else"),
        ],
        columns=["squadName", "duel_type", "playerName"],
    )

    result = working._duel_split_kpis(duels, "Charlton")

    assert result == {
        "aerial_pct": 33,
        "ground_pct": 67,
        "most_involved": "Jones 2 · Coventry 1",
    }


def test_player_threat_ranking_uses_positive_open_play_threat(monkeypatch):
    monkeypatch.setattr(working, "_uri_fixed", lambda figure: "chart")
    events = pd.DataFrame(
        [
            ("PASS", "OPEN_PLAY", 0.20, "Miles Leaburn", "Charlton"),
            ("PASS", "OPEN_PLAY", -0.15, "Miles Leaburn", "Charlton"),
            ("DRIBBLE", "OPEN_PLAY", 0.05, "Luke Berry", "Charlton"),
            ("PASS", "GOAL", 0.90, "Luke Berry", "Charlton"),
            ("PASS", "OPEN_PLAY", 0.10, "Jarrod Bowen", "Opponent"),
        ],
        columns=["actionType", "action", "PXT_ATTACK", "playerName", "squadName"],
    )

    chart, totals = working._player_threat_ranking(events, "Charlton", "Opponent")

    assert chart == "chart"
    assert totals == {"Charlton": "0.25", "Opponent": "0.10"}


def test_starters_network_adds_undirected_pair_threat_and_drops_substitutes():
    nodes = pd.DataFrame(
        [
            ("A One", True),
            ("B Two", True),
            ("C Three", False),
        ],
        columns=["playerName", "is_starter"],
    )
    edges = pd.DataFrame(
        [("A One", "B Two"), ("A One", "C Three")], columns=["a", "b"]
    )
    net = metrics.PassingNetwork(nodes, edges, 70.0, 100)
    events = pd.DataFrame(
        [
            ("Charlton", "PASS", "SUCCESS", "A One", "B Two", 0.10),
            ("Charlton", "PASS", "SUCCESS", "B Two", "A One", -0.03),
            ("Charlton", "PASS", "SUCCESS", "A One", "C Three", 0.40),
        ],
        columns=[
            "squadName", "actionType", "result", "playerName",
            "passReceiverPlayerName", "PXT_ATTACK",
        ],
    )

    result = working._starters_only_network(net, events, "Charlton")

    assert result.nodes["playerName"].tolist() == ["A One", "B Two"]
    assert result.nodes["surname"].tolist() == ["AO", "BT"]
    assert result.edges[["a", "b"]].values.tolist() == [["A One", "B Two"]]
    assert result.edges["pxt"].iloc[0] == 0.07


def test_event_query_deduplicates_player_names_across_iterations():
    sql = " ".join(impect_cafcdb_source._EVENTS_SQL.split()).lower()
    assert "partition by id order by iteration_id desc" in sql
    assert "left join player_names pn on pn.id = e.player_id" in sql
