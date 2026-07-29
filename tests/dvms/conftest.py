"""Fixtures for the dvms package tests.

Everything here parses the real sample files in ``~/Desktop/dvms_samples``
(a full Blackburn v Middlesbrough match). If that directory isn't present the
whole suite skips with a clear message rather than failing — the samples are
the ground truth these parsers were written against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SAMPLES = Path.home() / "Desktop" / "dvms_samples"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: needs a full tracking file (set DVMS_TRACKING_FILE)",
    )

if not SAMPLES.is_dir():
    pytest.skip(
        f"sample data directory not found: {SAMPLES} — the dvms tests need the "
        "real sample files", allow_module_level=True,
    )


@pytest.fixture(scope="session")
def f24_text() -> str:
    return (SAMPLES / "opta_f24.xml").read_text()


@pytest.fixture(scope="session")
def f7_text() -> str:
    return (SAMPLES / "opta_f7.xml").read_text()


@pytest.fixture(scope="session")
def ss_meta_text() -> str:
    return (SAMPLES / "ss_metadata.json").read_text()


@pytest.fixture(scope="session")
def physical_summary_text() -> str:
    return (SAMPLES / "ss_physical_summary.csv").read_text()


@pytest.fixture(scope="session")
def physical_splits_text() -> str:
    return (SAMPLES / "ss_physical_splits.csv").read_text()


@pytest.fixture(scope="session")
def tracking_peek_path() -> str:
    return str(SAMPLES / "ss_data_PEEK.jsonl")


@pytest.fixture(scope="session")
def f24(f24_text):
    from src.dvms.parsers.f24 import parse_f24
    return parse_f24(f24_text)


@pytest.fixture(scope="session")
def f7(f7_text):
    from src.dvms.parsers.f7 import parse_f7
    return parse_f7(f7_text)


@pytest.fixture(scope="session")
def pitch_meta(ss_meta_text):
    from src.dvms.parsers.ss_meta import parse_ss_metadata
    return parse_ss_metadata(ss_meta_text)
