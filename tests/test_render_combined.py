from types import SimpleNamespace

import pandas as pd
import pytest

from src.dvms.loaders import fixtures
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


def _fixture_rows(*rows):
    return pd.DataFrame(rows, columns=[
        "FIXTURE_ID", "OPTA_MATCH_ID", "MATCH_DATE", "HOME_TEAM_NAME",
        "AWAY_TEAM_NAME", "HOME_SCORE", "AWAY_SCORE",
    ])


def test_auto_fixture_match_normalizes_fc_suffix(monkeypatch):
    data = _fixture_rows(("f1", "g2566913", "2026-08-15", "Charlton Athletic FC",
                          "Derby County", 1, 2))
    monkeypatch.setattr(fixtures, "list_fixtures", lambda env_path=".env": data)
    result = fixtures.resolve_fixture_for_match(
        "Charlton Athletic", "Derby County", pd.Timestamp("2026-08-15", tz="UTC")
    )
    assert result.opta_match_id == "2566913"


def test_auto_fixture_match_returns_none_when_date_is_absent(monkeypatch):
    data = _fixture_rows(("f1", "1", "2026-08-14", "Charlton Athletic", "Derby County", 1, 2))
    monkeypatch.setattr(fixtures, "list_fixtures", lambda env_path=".env": data)
    assert fixtures.resolve_fixture_for_match(
        "Charlton Athletic", "Derby County", pd.Timestamp("2026-08-15")
    ) is None


def test_auto_fixture_match_rejects_same_date_identity_conflict(monkeypatch):
    data = _fixture_rows(("f1", "1", "2026-08-15", "Millwall", "Derby County", 1, 2))
    monkeypatch.setattr(fixtures, "list_fixtures", lambda env_path=".env": data)
    with pytest.raises(LookupError, match="Candidates"):
        fixtures.resolve_fixture_for_match(
            "Charlton Athletic", "Derby County", pd.Timestamp("2026-08-15")
        )
