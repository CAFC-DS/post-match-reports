import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reports" / "set_piece"))
from set_piece_report.impect_cafcdb_source import exclude_penalty_phases  # noqa: E402


def _row(seq, action_type, action, squad="A", phase=None, match=1):
    return dict(matchId=match, sequenceIndex=seq, actionType=action_type, action=action, squadName=squad, setPieceId=phase)


def test_penalty_phase_is_dropped_from_the_penalty_onwards_and_earlier_events_stay():
    df = pd.DataFrame([
        _row(1, "CORNER", "CORNER", phase=7), _row(2, "FOUL", "FOUL", squad="B", phase=7),
        _row(3, "SHOT", "PENALTY_KICK", phase=7), _row(4, "GOAL", "GOAL", phase=7),
        _row(5, "GK_SAVE", "SAVE", squad="B", phase=7),            # rebound/second phase of the penalty
        _row(9, "CORNER", "CORNER", phase=8),                      # a later, unrelated phase
    ])
    out = exclude_penalty_phases(df)
    assert list(out["sequenceIndex"]) == [1, 2, 9]


def test_a_penalty_outside_any_phase_loses_its_shot_and_goal_only():
    df = pd.DataFrame([_row(1, "THROW_IN", "THROW_IN", phase=3), _row(10, "SHOT", "PENALTY_KICK"),
                       _row(11, "GOAL", "GOAL"), _row(12, "GOAL", "GOAL", squad="B"), _row(40, "GOAL", "GOAL")])
    out = exclude_penalty_phases(df)
    assert list(out["sequenceIndex"]) == [1, 12, 40]                # the other side's goal and a later goal stay


def test_matches_without_penalties_and_empty_frames_are_untouched():
    df = pd.DataFrame([_row(1, "CORNER", "CORNER", phase=1)])
    assert exclude_penalty_phases(df).equals(df)
    assert exclude_penalty_phases(df.iloc[0:0]).empty
