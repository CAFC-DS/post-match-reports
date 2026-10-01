"""Locating Chrome / Chromium for the deterministic print-to-PDF step."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class BrowserConfigurationError(RuntimeError):
    """Raised when no usable Chrome/Chromium executable can be found."""


def _default_chrome_candidates() -> tuple[Path, ...]:
    return (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    )


def resolve_chrome(explicit: str | Path | None = None) -> Path:
    """Resolve the browser used for the deterministic print-to-PDF step.

    An explicit CLI value wins, then ``CHROME_BIN``, then executables on
    ``PATH``, followed by common macOS/Windows install locations.
    """
    configured = explicit or os.environ.get("CHROME_BIN")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path.resolve()
        raise BrowserConfigurationError(f"Chrome executable does not exist: {path}")

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    for path in _default_chrome_candidates():
        if path.is_file():
            return path.resolve()
    raise BrowserConfigurationError(
        "No Chrome/Chromium executable found. Pass --chrome-bin or set CHROME_BIN."
    )


def chrome_version(chrome: Path) -> str:
    result = subprocess.run(
        [str(chrome), "--version"], check=True, capture_output=True, text=True,
    )
    return result.stdout.strip() or result.stderr.strip()
