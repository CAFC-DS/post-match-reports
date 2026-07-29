"""xG-lite and set-piece mapping tests against the real sample match."""

import numpy as np
import pandas as pd
import pytest

from src.dvms.metrics.opta_setpiece_map import (
    corners,
    first_contact,
    free_kicks,
    led_to_goal,
    throw_ins,
)
from src.dvms.metrics.xg_lite import XG_MODEL_LABEL, add_xg

L, W = 104.68, 65.42


def _shot_row(x, y, quals=None):
    return {
        "type_id": 15, "x": x, "y": y,
        "qualifiers": quals or {},
    }


class TestXgLite:
    def test_real_shots_in_sane_range(self, f24):
        xg = add_xg(f24.events, L, W)
        shots = xg[f24.events["is_shot"]]
        assert shots.notna().all()
        assert (shots >= 0.01).all()
        assert (shots <= 0.6).all()
        # Non-shots carry no xG.
        assert xg[~f24.events["is_shot"]].isna().all()

    def test_monotonic_in_distance_and_angle(self):
        rows = [
            _shot_row(96, 50),   # six-yard central
            _shot_row(88.5, 50), # penalty spot
            _shot_row(76, 50),   # ~25m central
            _shot_row(88.5, 25), # penalty-spot depth but wide
        ]
        df = pd.DataFrame(rows)
        xg = add_xg(df, L, W)
        assert xg[0] > xg[1] > xg[2]          # closer is better
        assert xg[1] > xg[3]                  # central beats wide at same depth
        # Anchor sanity (hand-fit): six-yard ≈ 0.37, spot ≈ 0.19, 25m ≈ 0.03.
        assert xg[0] == pytest.approx(0.37, abs=0.08)
        assert xg[1] == pytest.approx(0.19, abs=0.05)
        assert xg[2] == pytest.approx(0.03, abs=0.02)

    def test_header_worth_less(self):
        df = pd.DataFrame([_shot_row(88.5, 50), _shot_row(88.5, 50, {15: None})])
        xg = add_xg(df, L, W)
        assert xg[1] < xg[0]

    def test_label(self):
        assert XG_MODEL_LABEL == "CAFC-lite xG"


class TestSetPieceMap:
    def test_corners(self, f24):
        c = corners(f24.events)
        assert len(c) == 14
        assert set(c["side"].unique()) <= {"left", "right"}
        assert c["side"].nunique() == 2            # both flanks used
        assert set(c["corner_type"]) <= {"short", "near_post", "central", "far_post"}
        # Both teams took corners in this match.
        assert c["team_id"].nunique() == 2

    def test_first_contact(self, f24):
        c = corners(f24.events)
        fc = first_contact(f24.events, c)
        assert len(fc) == len(c)
        # The vast majority of corner deliveries produce an identifiable contact.
        assert fc["won"].notna().mean() > 0.8
        contested = fc[fc["won"].notna()]
        # Contacts split between the two teams, not all one way.
        assert 0.0 < contested["won"].mean() < 1.0

    def test_free_kicks(self, f24):
        fk = free_kicks(f24.events)
        assert len(fk) == 20                        # q5 count pinned from sample
        assert set(fk["fk_type"]) <= {"into_box_cross", "into_box", "short", "direct"}
        # This match had no direct FK shots (q26 absent from the sample feed).
        assert (fk["fk_type"] != "direct").all()
        in_box = fk[fk["fk_type"].str.startswith("into_box")]
        assert in_box["zone"].notna().all()

    def test_throw_ins(self, f24):
        t = throw_ins(f24.events)
        assert len(t) == 33                        # q107 count pinned from sample
        assert t["is_long"].dtype == bool
        # Routine restarts should dominate; long throws are the exception.
        assert t["is_long"].mean() < 0.5

    def test_led_to_goal_goalless_match(self, f24):
        c = corners(f24.events)
        flags = led_to_goal(f24.events, c)
        # 0-0: nothing can have led to a goal.
        assert not flags.any()
