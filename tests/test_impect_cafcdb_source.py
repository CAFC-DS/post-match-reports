import json

import numpy as np

from src.report.impect_cafcdb_source import _kpi_row_for_player


def test_kpi_row_picks_the_acting_players_entry():
    payload = json.dumps([{"playerId": 2, "SHOT_XG": 0.1}, {"playerId": 1, "SHOT_XG": 0.4}])
    assert _kpi_row_for_player(payload, 1) == {"playerId": 1, "SHOT_XG": 0.4}
    assert _kpi_row_for_player(payload, 3) == {}


def test_null_kpis_are_empty_whether_none_or_nan():
    # pandas 3 turns a NULL string column value into float NaN, which is truthy.
    assert _kpi_row_for_player(None, 1) == {}
    assert _kpi_row_for_player(float("nan"), 1) == {}
    assert _kpi_row_for_player(np.nan, 1) == {}
    assert _kpi_row_for_player("", 1) == {}
