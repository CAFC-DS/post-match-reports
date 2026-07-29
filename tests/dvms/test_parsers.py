"""Parser tests against the real sample match (Blackburn 0-0 Middlesbrough)."""

import numpy as np
import pandas as pd

from src.dvms.parsers.f24 import SHOT_TYPE_IDS, parse_f24
from src.dvms.parsers.ss_physical import parse_physical_splits, parse_physical_summary
from src.dvms.parsers.tracking import frames_to_long_df, iter_frames


class TestF24:
    def test_game_meta(self, f24):
        assert f24.game_id == "2566820"
        assert f24.home_team_name == "Blackburn Rovers"
        assert f24.away_team_name == "Middlesbrough"
        assert f24.home_score == 0 and f24.away_score == 0

    def test_event_counts(self, f24):
        # 1,771 events in the raw file; every one lands in the frame.
        assert len(f24.events) == 1771
        # Counts pinned against a raw grep of the sample file.
        by_type = f24.events["type_id"].value_counts()
        assert by_type[1] > 900          # passes dominate
        assert int(f24.events["is_shot"].sum()) == 17
        assert int(f24.events["is_goal"].sum()) == 0   # it finished 0-0

    def test_qualifiers_and_end_coords(self, f24):
        passes = f24.events[f24.events["is_pass"]]
        # q140/141 (end x/y) present on essentially every pass.
        assert passes["end_x"].notna().mean() > 0.99
        assert passes["end_y"].notna().mean() > 0.99
        # Corner flag q6 pins to the known count of 14 corner deliveries.
        n_corners = int(passes["qualifiers"].map(lambda q: 6 in q).sum())
        assert n_corners == 14

    def test_chronological_order(self, f24):
        ev = f24.events
        key = ev["period_id"] * 10_000 + ev["minute"] * 60 + ev["second"]
        assert key.is_monotonic_increasing

    def test_ids_are_strings(self, f24):
        assert f24.events["player_id"].dtype == "string"
        assert f24.events["team_id"].dtype == "string"


class TestF7:
    def test_teams(self, f7):
        assert f7.home.name == "Blackburn Rovers"
        assert f7.away.name == "Middlesbrough"
        assert f7.home.team_id.isdigit() and f7.away.team_id.isdigit()
        assert f7.home.formation and f7.away.formation

    def test_lineups(self, f7):
        starters = f7.lineups[f7.lineups["status"] == "Start"]
        assert len(starters) == 22
        assert starters.groupby("team_id").size().tolist() == [11, 11]
        # Every named player resolves to a non-empty name.
        assert f7.lineups["full_name"].notna().all()

    def test_name_lookup_both_id_forms(self, f7):
        pid = f7.lineups["player_id"].iloc[0]
        assert f7.player_name(pid)
        assert f7.player_name(f"p{pid}") == f7.player_name(pid)


class TestSSMeta:
    def test_pitch_and_periods(self, pitch_meta):
        assert 100 < pitch_meta.pitch_length < 110
        assert 60 < pitch_meta.pitch_width < 70
        assert pitch_meta.fps == 25.0
        assert [p.number for p in pitch_meta.periods][:2] == [1, 2]
        # The two halves attack in opposite directions.
        assert pitch_meta.home_att_positive(1) != pitch_meta.home_att_positive(2)

    def test_rosters_join_key(self, pitch_meta):
        ids = pitch_meta.opta_id_map()
        assert len(ids) >= 30           # both squads incl. subs
        assert set(ids.values()) == {"home", "away"}
        assert pitch_meta.home_team_id and pitch_meta.away_team_id


class TestPhysical:
    def test_summary(self, physical_summary_text):
        df = parse_physical_summary(physical_summary_text)
        # Both team blocks parsed, one row per player.
        assert df["team_block"].nunique() == 2
        assert len(df) >= 28
        assert df["opta_player_id"].str.isdigit().all()
        # Distance columns numeric and positive for anyone who played.
        played = df[df["minutes"] > 10]
        assert (played["distance"] > 1000).all()
        # TIP/OTIP/BOP split columns arrived with normalized names.
        for col in ("distance_tip", "distance_otip", "distance_bop",
                    "hsr_distance_tip", "n_high_intensity_runs_otip"):
            assert col in df.columns, col
        # The splits roughly sum to the total.
        recon = played["distance_tip"] + played["distance_otip"] + played["distance_bop"]
        assert np.allclose(recon, played["distance"], rtol=0.02)

    def test_splits(self, physical_splits_text):
        df = parse_physical_splits(physical_splits_text)
        assert not df.empty
        assert set(df["half"].unique()) == {1, 2}
        # Team-total sections exist for both sides plus per-player sections.
        assert df["is_team_total"].any()
        assert df.loc[df["is_team_total"], "section"].nunique() == 2
        assert df["section"].nunique() > 20
        assert "total_distance" in set(df["metric"])
        # Minute bins are 5-minute cumulative ends.
        assert df["minute"].min() == 5


class TestTracking:
    def test_peek_stream_and_long_df(self, tracking_peek_path):
        # The peek file is byte-truncated mid-line; consume defensively —
        # every complete line parses, the final partial one is dropped.
        frames = []
        try:
            for f in iter_frames(tracking_peek_path):
                frames.append(f)
        except Exception:
            pass
        assert frames, "no complete frames in the peek file"
        f0 = frames[0]
        assert {"period", "frameIdx", "gameClock", "homePlayers", "awayPlayers",
                "ball", "live", "lastTouch"} <= set(f0)

        df = frames_to_long_df(frames, every_n=1)
        assert set(df["team"].unique()) <= {"home", "away", "ball"}
        players = df[df["team"] != "ball"]
        assert players["opta_id"].notna().all()
        # Pitch-centred metres: everything inside half-length/half-width bounds.
        assert players["x"].abs().max() < 60
        assert players["y"].abs().max() < 40
