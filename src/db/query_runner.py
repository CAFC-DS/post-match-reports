"""Query execution and local extract caching."""

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
        self.outputs_dir = Path("outputs/extracts")
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_enabled = bool(self.table_config.get_project_setting("local_cache_enabled", True))
        self.cache_format = str(self.table_config.get_project_setting("local_cache_format", "parquet"))

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

    def _cache_path(self, name: str) -> Path:
        suffix = ".parquet" if self.cache_format == "parquet" else ".csv"
        return self.processed_dir / f"{name}{suffix}"

    def save_dataframe(self, df: pd.DataFrame, name: str) -> Path:
        cache_path = self._cache_path(name)
        if self.cache_format == "parquet":
            df.to_parquet(cache_path, index=False)
        else:
            df.to_csv(cache_path, index=False)
        output_path = self.outputs_dir / cache_path.name
        if self.cache_format == "parquet":
            df.to_parquet(output_path, index=False)
        else:
            df.to_csv(output_path, index=False)
        return cache_path

    def load_cached_dataframe(self, name: str) -> pd.DataFrame | None:
        cache_path = self._cache_path(name)
        if not cache_path.exists():
            return None
        if cache_path.suffix == ".parquet":
            return pd.read_parquet(cache_path)
        return pd.read_csv(cache_path)

    def default_filters(self) -> dict[str, Any]:
        return {
            "competition_name": self.table_config.get_project_setting("competition_name", "Championship"),
            "season": self.table_config.get_project_setting("season", "25/26"),
            "team_name": self.table_config.get_project_setting("team_name", "Charlton Athletic"),
        }

    def load_league_events(self, refresh: bool = False) -> pd.DataFrame:
        cache_name = "league_events"
        if self.cache_enabled and not refresh:
            cached = self.load_cached_dataframe(cache_name)
            if cached is not None:
                return cached
        params = {
            "qualified_table": self.get_active_table(),
            **self.default_filters(),
        }
        df = self.run_sql_file("sql/extracts/impect_events.sql", params=params)
        if self.cache_enabled:
            self.save_dataframe(df, cache_name)
        return df

    def load_charlton_events(self, refresh: bool = False) -> pd.DataFrame:
        cache_name = "charlton_events"
        if self.cache_enabled and not refresh:
            cached = self.load_cached_dataframe(cache_name)
            if cached is not None:
                return cached
        filters = self.default_filters()
        table = self.get_active_table()
        sql = f"""
        select *
        from {table}
        where "competitionName" = %(competition_name)s
          and "season" = %(season)s
          and (
            "squadName" = %(team_name)s
            or "homeSquadName" = %(team_name)s
            or "awaySquadName" = %(team_name)s
          )
        """
        df = self.run_sql(sql, params=filters)
        if self.cache_enabled:
            self.save_dataframe(df, cache_name)
        return df

    def load_player_iteration_averages(self, refresh: bool = False) -> pd.DataFrame:
        """Load optional IMPECT player iteration averages."""
        cache_name = "impect_player_iteration_averages"
        if self.cache_enabled and not refresh:
            cached = self.load_cached_dataframe(cache_name)
            if cached is not None:
                return cached
        table = self.get_active_table("impect_player_iteration_averages")
        df = self.run_sql(f"select * from {table}")
        if self.cache_enabled:
            self.save_dataframe(df, cache_name)
        return df
