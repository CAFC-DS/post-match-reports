"""Layout guard: find pages where content is clipped or pushed off the A4 sheet.

Every page is a fixed-size ``.sheet`` with ``overflow: hidden``, so anything that does not fit is
cut off silently and the PDF still has the right page count. This renders the HTML in headless
Chrome, measures each sheet and each card in the page itself and reports the ones whose content is
taller than their box. A page count test cannot see this; this can.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

TOLERANCE_PX = 2

_SCRIPT = """
<script>
window.addEventListener('load', function () {
  var problems = [];
  var tol = %d;
  document.querySelectorAll('section.sheet').forEach(function (sheet, i) {
    var page = i + 1;
    var limit = sheet.getBoundingClientRect().bottom, worst = null, worstBottom = 0;
    sheet.querySelectorAll('*').forEach(function (el) {
      var r = el.getBoundingClientRect();
      if (r.height > 0 && r.bottom > worstBottom && el.offsetParent !== null) { worstBottom = r.bottom; worst = el; }
    });
    if (worst && worstBottom > limit + tol) {
      problems.push({page: page, kind: 'sheet', what: (worst.tagName + '.' + worst.className).slice(0, 50),
                     over_px: Math.round(worstBottom - limit)});
    }
    sheet.querySelectorAll('.card').forEach(function (card) {
      var over = card.scrollHeight - card.clientHeight;
      var overW = card.scrollWidth - card.clientWidth;
      if (over > tol || overW > tol) {
        var h = card.querySelector('h2, .head, b');
        problems.push({page: page, kind: 'card', what: (h ? h.textContent : card.textContent).trim().slice(0, 50),
                       over_px: Math.max(over, overW)});
      }
    });
  });
  document.body.setAttribute('data-layout-problems', JSON.stringify(problems));
});
</script>
""" % TOLERANCE_PX


class LayoutOverflowError(RuntimeError):
    """Raised when a page has content that does not fit its sheet or card."""


def find_overflow(html: str, chrome: str | Path, extra_args: list[str] | None = None, timeout: int = 180) -> list[dict[str, Any]]:
    """Return ``[{page, kind, what, over_px}]`` for every overflowing sheet or card (empty = all fit)."""
    args = list(extra_args or [])
    if hasattr(os, "geteuid") and os.geteuid() == 0 and "--no-sandbox" not in args:
        args.append("--no-sandbox")                    # Chrome refuses to run as root otherwise
    instrumented = html.replace("</body>", _SCRIPT + "</body>") if "</body>" in html else html + _SCRIPT
    with tempfile.TemporaryDirectory(prefix="layout-check-") as tmp:
        path = Path(tmp) / "report.html"
        path.write_text(instrumented, encoding="utf-8")
        out = subprocess.run([str(chrome), "--headless", "--disable-gpu", "--virtual-time-budget=20000", "--dump-dom",
                              *args, path.resolve().as_uri()], check=True, capture_output=True, text=True,
                             timeout=timeout).stdout
    found = re.search(r'data-layout-problems="([^"]*)"', out)
    if not found:
        raise RuntimeError("layout check did not run: the page produced no result")
    return json.loads(html_lib.unescape(found.group(1)))


def describe(problems: list[dict[str, Any]]) -> str:
    return "; ".join(f"page {p['page']}: {p['kind']} '{p['what']}' overflows by {p['over_px']}px" for p in problems)
