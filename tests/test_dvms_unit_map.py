"""Regression test for ``unit_map`` (kept outside ``tests/dvms``: that package
skips itself wherever the real sample feeds are missing, which hid this bug)."""
import numpy as np
import pandas as pd
import pytest

from src.dvms.metrics.lines import unit_map


@pytest.mark.parametrize("missing", [
    pd.array([None, None, None, "Forward"], dtype="string"),   # pd.NA: a string column under pandas 3
    [np.nan, np.nan, np.nan, "Forward"],                      # float NaN in an object column
    [None, None, None, "Forward"],                            # plain None
])
def test_starters_get_a_unit_when_sub_position_is_missing(missing):
    """A missing sub_position is NaN / pd.NA, which is truthy; `a or b` left every
    starter without a unit, so whole halves had no defence/midfield/attack lines."""
    lineups = pd.DataFrame({
        "player_id": ["1", "2", "3", "4"],
        "position": ["Goalkeeper", "Defender", "Midfielder", "Substitute"],
        "sub_position": missing,
    })
    assert unit_map(lineups) == {"1": "goalkeeper", "2": "defence", "3": "midfield", "4": "attack"}
