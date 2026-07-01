"""Configuration helpers for Snowflake table mappings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_env(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        env_name = match.group(1)
        return os.getenv(env_name, "")

    return ENV_PATTERN.sub(replace, value)


def _expand_tree(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _expand_tree(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_expand_tree(value) for value in node]
    return _expand_env(node)


@dataclass(frozen=True)
class TableMapping:
    """Logical entity to Snowflake table mapping."""

    entity_name: str
    active: bool
    required: bool
    database: str | None
    schema: str | None
    table: str | None

    @property
    def qualified_name(self) -> str | None:
        if not self.table:
            return None
        parts = [part for part in [self.database, self.schema, self.table] if part]
        return ".".join(parts)


class TableConfig:
    """Loads YAML config for project and table mappings."""

    def __init__(self, config_path: str | Path = "config/tables.yml") -> None:
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Table config not found: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as handle:
            raw_config = yaml.safe_load(handle) or {}
        self.raw_config = _expand_tree(raw_config)
        self.project = self.raw_config.get("project", {})

    def get_table(self, entity_name: str) -> TableMapping:
        entity = self.raw_config.get(entity_name)
        if entity is None:
            raise KeyError(f"Entity '{entity_name}' not found in {self.config_path}")
        return TableMapping(
            entity_name=entity_name,
            active=bool(entity.get("active", False)),
            required=bool(entity.get("required", False)),
            database=entity.get("database"),
            schema=entity.get("schema"),
            table=entity.get("table"),
        )

    def list_entities(self) -> list[str]:
        return [key for key in self.raw_config.keys() if key != "project"]

    def get_project_setting(self, key: str, default: Any = None) -> Any:
        return self.project.get(key, default)

    def get_glossary_paths(self) -> list[str]:
        glossary_cfg = self.raw_config.get("glossary", {})
        paths = []
        primary = glossary_cfg.get("path")
        if primary:
            paths.append(primary)
        paths.extend(glossary_cfg.get("fallback_paths", []))
        return paths
