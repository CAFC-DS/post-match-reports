from pathlib import Path

import pytest

from src.report.expanded import browser


def test_resolve_chrome_prefers_explicit_path(tmp_path):
    chrome = tmp_path / "chrome"
    chrome.touch()
    assert browser.resolve_chrome(chrome) == chrome.resolve()


def test_resolve_chrome_uses_environment(monkeypatch, tmp_path):
    chrome = tmp_path / "chromium"
    chrome.touch()
    monkeypatch.setenv("CHROME_BIN", str(chrome))
    assert browser.resolve_chrome() == chrome.resolve()


def test_resolve_chrome_rejects_missing_explicit_path(tmp_path):
    with pytest.raises(browser.BrowserConfigurationError, match="does not exist"):
        browser.resolve_chrome(tmp_path / "missing")


def test_resolve_chrome_reports_when_discovery_fails(monkeypatch):
    monkeypatch.delenv("CHROME_BIN", raising=False)
    monkeypatch.setattr(browser.shutil, "which", lambda _name: None)
    monkeypatch.setattr(browser, "_default_chrome_candidates", lambda: (Path("/missing"),))
    with pytest.raises(browser.BrowserConfigurationError, match="Pass --chrome-bin"):
        browser.resolve_chrome()
