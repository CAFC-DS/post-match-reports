import datetime as dt

import pandas as pd

from post_match_reports import discovery


def _candidate(date="2026-08-22T14:00:00Z", events=100):
    return pd.DataFrame(
        [{
            "MATCH_ID": 267843,
            "KICKOFF_UTC": date,
            "HOME_TEAM": "West Ham United",
            "AWAY_TEAM": "Charlton Athletic",
            "EVENT_COUNT": events,
            "HOME_GOALS": 1,
            "AWAY_GOALS": 2,
        }]
    )


def _fixtures(home_score=1, away_score=2):
    return pd.DataFrame(
        [{
            "FIXTURE_ID": "fixture-1",
            "OPTA_MATCH_ID": "g2647272",
            "MATCH_DATE": "2026-08-22T14:00:00",
            "HOME_TEAM_NAME": "West Ham United FC",
            "AWAY_TEAM_NAME": "Charlton Athletic FC",
            "HOME_SCORE": home_score,
            "AWAY_SCORE": away_score,
        }]
    )


def test_discover_returns_latest_complete_cross_provider_fixture(monkeypatch):
    monkeypatch.setattr(discovery, "_candidate_rows", lambda *args: _candidate())
    monkeypatch.setattr(discovery, "list_fixtures", lambda *args: _fixtures())
    monkeypatch.setattr(discovery, "_dvms_assets_ready", lambda *args: True)

    result = discovery.discover_latest_ready(not_before=dt.date(2026, 8, 20))

    assert result.impect_match_id == 267843
    assert result.dvms_match_id == "2647272"
    assert result.home_goals == 1
    assert result.away_goals == 2


def test_discover_waits_when_dvms_scores_or_assets_are_missing(monkeypatch):
    monkeypatch.setattr(discovery, "_candidate_rows", lambda *args: _candidate())
    monkeypatch.setattr(discovery, "list_fixtures", lambda *args: _fixtures(None, None))
    monkeypatch.setattr(discovery, "_dvms_assets_ready", lambda *args: True)
    assert discovery.discover_latest_ready() is None

    monkeypatch.setattr(discovery, "list_fixtures", lambda *args: _fixtures())
    monkeypatch.setattr(discovery, "_dvms_assets_ready", lambda *args: False)
    assert discovery.discover_latest_ready() is None


def test_discover_respects_automation_start_date(monkeypatch):
    monkeypatch.setattr(discovery, "_candidate_rows", lambda *args: _candidate())
    monkeypatch.setattr(discovery, "list_fixtures", lambda *args: _fixtures())
    monkeypatch.setattr(discovery, "_dvms_assets_ready", lambda *args: True)

    assert discovery.discover_latest_ready(not_before=dt.date(2026, 8, 23)) is None
