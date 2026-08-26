from src.visualisation.badges import badge_data_uri, badge_path


def test_southampton_and_stoke_badges_are_available():
    for team in ("FC Southampton", "Stoke City"):
        path = badge_path(team)
        assert path is not None
        assert path.is_file()
        assert badge_data_uri(team).startswith("data:image/png;base64,")
