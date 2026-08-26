from src.visualisation.badges import TEAM_BADGE_FILES, badge_data_uri, badge_path


CURRENT_CHAMPIONSHIP_TEAMS = {
    "AFC Wrexham", "Birmingham City", "Blackburn Rovers", "Bolton Wanderers",
    "Bristol City", "Cardiff City", "Charlton Athletic", "Derby County",
    "FC Burnley", "FC Middlesbrough", "FC Millwall", "FC Portsmouth",
    "FC Southampton", "FC Watford", "Lincoln City", "Norwich City",
    "Preston North End", "Queens Park Rangers", "Sheffield United", "Stoke City",
    "Swansea City", "West Bromwich Albion", "West Ham United",
    "Wolverhampton Wanderers",
}


def test_every_championship_badge_is_available():
    assert CURRENT_CHAMPIONSHIP_TEAMS <= TEAM_BADGE_FILES.keys()
    for team in TEAM_BADGE_FILES:
        path = badge_path(team)
        assert path is not None
        assert path.is_file()
        assert badge_data_uri(team).startswith("data:image/png;base64,")
