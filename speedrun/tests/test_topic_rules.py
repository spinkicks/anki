# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

import scrape_openstax as sc  # noqa: E402


def test_keyword_tagging():
    assert sc.tag_for("The derivative of a product") == "calc::single_var::differentiation"
    assert sc.tag_for("An eigenvalue satisfies Av = lambda v") == "linear_algebra::eigen"


def test_unknown_content_is_dropped_not_guessed():
    notes, dropped = sc.scrape(
        '<div class="definition">The capital of France is Paris.</div>', "PD text"
    )
    assert notes == []
    assert dropped == 1


def test_scraped_notes_carry_source():
    html = '<div class="theorem">The determinant of a 2x2 matrix. It equals ad-bc.</div>'
    notes, _ = sc.scrape(html, "Hefferon LA (free license)")
    assert notes and all(n["source"] == "Hefferon LA (free license)" for n in notes)
    assert notes[0]["topic"] == "linear_algebra::matrices"
