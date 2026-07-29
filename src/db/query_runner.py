"""Query execution and local parquet caching, scoped to a single fixture.

Unlike the season-wide projects (which cache the whole competition's events),
this report only ever needs one match at a time, so the cache key is the
match_id: data/processed/match_<id>_events.parquet. Re-running the report for
a different fixture is then a one-line change (pass a different match_id) with
no code edits, and each fixture's extract is cheap (a few thousand rows).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from src.db.snowflake_connection import SnowflakeConnector
from src.db.table_config import TableConfig


class QueryRunner:
    """Runs SQL files and manages local parquet extracts."""

    def __init__(
        self,
        config_path: str | Path = "config/tables.yml",
        env_path: str | Path = ".env",
    ) -> None:
        load_dotenv(env_path)
        self.table_config = TableConfig(config_path)
        self.connector = SnowflakeConnector(env_path)
        self.processed_dir = Path("data/processed")
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def quote_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def get_active_table(self, entity_name: str = "impect_events") -> str:
        mapping = self.table_config.get_table(entity_name)
        qualified_name = mapping.qualified_name
        if not mapping.active or not qualified_name:
            raise ValueError(
                f"Configuration missing for '{entity_name}'. Check config/tables.yml."
            )
        return qualified_name

    def load_sql_file(self, sql_path: str | Path) -> str:
        path = Path(sql_path)
        if not path.exists():
            raise FileNotFoundError(f"SQL file not found: {path}")
        return path.read_text(encoding="utf-8")

    def run_sql(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return self.connector.query_to_dataframe(sql, params=params)

    def run_sql_file(self, sql_path: str | Path, params: dict[str, Any] | None = None) -> pd.DataFrame:
        sql = self.load_sql_file(sql_path)
        bound_params = dict(params or {})
        qualified_table = bound_params.pop("qualified_table", None)
        if qualified_table:
            sql = sql.replace("{{ qualified_table }}", qualified_table)
        return self.run_sql(sql, params=bound_params)

    def default_filters(self) -> dict[str, Any]:
        return {
            "competition_name": self.table_config.get_project_setting("competition_name", "Championship"),
            "season": self.table_config.get_project_setting("season", "25/26"),
            "team_name": self.table_config.get_project_setting("team_name", "Charlton Athletic"),
        }

    def list_team_fixtures(self) -> pd.DataFrame:
        """All fixtures for the configured team, most recent first."""
        params = {
            "qualified_table": self.get_active_table(),
            "team_name": self.table_config.get_project_setting("team_name", "Charlton Athletic"),
        }
        return self.run_sql_file("sql/extracts/charlton_fixtures.sql", params=params)

    def load_season_results(self, refresh: bool = False) -> pd.DataFrame:
        """One row per league fixture this season, with the final score. Cached
        like the events extract: it is a season-wide aggregate over ~1.5m rows,
        so it is not something to re-run on every render."""
        cache_path = self.processed_dir / "season_results.parquet"
        if cache_path.exists() and not refresh:
            return pd.read_parquet(cache_path)
        filters = self.default_filters()
        params = {
            "qualified_table": self.get_active_table(),
            "competition_name": filters["competition_name"],
            "season": filters["season"],
        }
        df = self.run_sql_file("sql/extracts/season_results.sql", params=params)
        df.columns = [c.lower() for c in df.columns]
        df.to_parquet(cache_path, index=False)
        return df

    def load_match_events(self, match_id: int, refresh: bool = False) -> pd.DataFrame:
        cache_path = self.processed_dir / f"match_{match_id}_events.parquet"
        if cache_path.exists() and not refresh:
            return pd.read_parquet(cache_path)
        params = {"qualified_table": self.get_active_table(), "match_id": match_id}
        df = self.run_sql_file("sql/extracts/match_events.sql", params=params)
        df.to_parquet(cache_path, index=False)
        return df
