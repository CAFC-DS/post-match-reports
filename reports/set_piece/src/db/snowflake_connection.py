"""Snowflake connection helpers with password and key-pair auth."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import snowflake.connector
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv


class SnowflakeConfigurationError(RuntimeError):
    """Raised when required Snowflake settings are missing."""


class SnowflakeConnector:
    """Small wrapper around Snowflake connector with safe defaults."""

    REQUIRED_ENV_VARS = [
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_ROLE",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
    ]

    def __init__(self, env_path: str | Path = ".env") -> None:
        load_dotenv(env_path)
        self.env_path = Path(env_path)

    def _validate_env(self) -> None:
        missing = [name for name in self.REQUIRED_ENV_VARS if not os.getenv(name)]
        has_password = bool(os.getenv("SNOWFLAKE_PASSWORD"))
        has_private_key = bool(os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH"))
        if missing:
            raise SnowflakeConfigurationError(
                "Missing required Snowflake environment variables: "
                + ", ".join(missing)
            )
        if not has_password and not has_private_key:
            raise SnowflakeConfigurationError(
                "Provide either SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH."
            )

    def _load_private_key(self) -> bytes | None:
        private_key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
        if not private_key_path:
            return None

        key_path = Path(private_key_path).expanduser()
        if not key_path.exists():
            raise SnowflakeConfigurationError(
                f"SNOWFLAKE_PRIVATE_KEY_PATH does not exist: {key_path}"
            )

        passphrase = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        with key_path.open("rb") as handle:
            private_key = serialization.load_pem_private_key(
                handle.read(),
                password=passphrase.encode("utf-8") if passphrase else None,
            )

        return private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def _connection_kwargs(self) -> dict[str, Any]:
        self._validate_env()
        kwargs: dict[str, Any] = {
            "account": os.getenv("SNOWFLAKE_ACCOUNT"),
            "user": os.getenv("SNOWFLAKE_USER"),
            "role": os.getenv("SNOWFLAKE_ROLE"),
            "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
            "database": os.getenv("SNOWFLAKE_DATABASE"),
            "schema": os.getenv("SNOWFLAKE_SCHEMA"),
            "authenticator": os.getenv("SNOWFLAKE_AUTHENTICATOR") or None,
            "login_timeout": 20,
            "network_timeout": 60,
        }
        private_key = self._load_private_key()
        if private_key is not None:
            kwargs["private_key"] = private_key
        else:
            kwargs["password"] = os.getenv("SNOWFLAKE_PASSWORD")
        return kwargs

    def connect(self) -> snowflake.connector.SnowflakeConnection:
        try:
            return snowflake.connector.connect(**self._connection_kwargs())
        except SnowflakeConfigurationError:
            raise
        except Exception as exc:  # pragma: no cover - network/system dependent
            raise RuntimeError(
                "Failed to establish Snowflake connection. Check credentials, role, "
                "warehouse, network access, and key or password authentication."
            ) from exc

    @contextmanager
    def connection(self) -> Iterator[snowflake.connector.SnowflakeConnection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def query_to_dataframe(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or {})
                try:
                    return cursor.fetch_pandas_all()
                except Exception:
                    rows = cursor.fetchall()
                    columns = [description[0] for description in (cursor.description or [])]
                    return pd.DataFrame(rows, columns=columns)
