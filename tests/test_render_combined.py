from types import SimpleNamespace

import pandas as pd
import pytest

from src.report.render_combined import FixtureMismatchError, _assert_same_fixture


def _impect_meta(home="Charlton Athletic", away="Swansea City", kickoff="2026-01-10"):
    return SimpleNamespace(home_team=home, away_team=away, kickoff=pd.Timestamp(kickoff, tz="UTC"))


def _dvms_fixture(home="Charlton Athletic", away="Swansea City", match_date="2026-01-10"):
    return SimpleNamespace(home_team=home, away_team=away, match_date=pd.Timestamp(match_date))


def test_matching_fixture_passes_silently():
    _assert_same_fixture(_impect_meta(), _dvms_fixture())  # no exception


def test_matching_fixture_is_case_insensitive():
    _assert_same_fixture(_impect_meta(home="CHARLTON ATHLETIC"), _dvms_fixture(home="charlton athletic"))


def test_mismatched_teams_raises():
    with pytest.raises(FixtureMismatchError):
        _assert_same_fixture(_impect_meta(away="Swansea City"), _dvms_fixture(away="Millwall"))


def test_mismatched_date_raises():
    with pytest.raises(FixtureMismatchError):
        _assert_same_fixture(_impect_meta(kickoff="2026-01-10"), _dvms_fixture(match_date="2026-01-11"))


def test_swapped_home_away_raises():
    # Same two teams (set check would pass) but the two feeds disagree on
    # which team was home — must still raise, not silently misattribute.
    with pytest.raises(FixtureMismatchError):
        _assert_same_fixture(
            _impect_meta(home="Charlton Athletic", away="Swansea City"),
            _dvms_fixture(home="Swansea City", away="Charlton Athletic"),
        )
