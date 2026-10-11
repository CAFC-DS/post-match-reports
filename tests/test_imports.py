"""Every module in the project must import: a syntax error in a rarely-used module should fail CI, not delivery."""
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("src", "post_match_reports")


def _modules():
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            relative = path.relative_to(ROOT).with_suffix("")
            parts = relative.parts
            if parts[-1] == "__main__" or "__pycache__" in parts:
                continue
            yield ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


@pytest.mark.parametrize("module", list(_modules()))
def test_module_imports(module):
    importlib.import_module(module)
