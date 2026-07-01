# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Deterministic (NO AI) scraper for open-licensed math sources.

Given a local HTML/LaTeX file from an OpenStax CC-BY book (or a public-domain
text), it extracts definition/theorem blocks, assigns a topic tag by keyword
rules, and emits YAML in the seed/ note shape. Every emitted note carries a
Source citation. Content whose topic cannot be determined is DROPPED (never
guessed) and reported, so the deck never contains mis-tagged or unsourced notes.
"""
from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser
from pathlib import Path

import yaml

RULES = yaml.safe_load(
    (Path(__file__).resolve().parent / "topic_rules.yaml").read_text("utf-8")
)["rules"]


def tag_for(text: str) -> str | None:
    low = text.lower()
    for rule in RULES:
        if any(kw in low for kw in rule["any"]):
            return rule["topic"]
    return None


class _BlockExtractor(HTMLParser):
    """Collects text inside <div class="definition|theorem"> blocks."""

    def __init__(self) -> None:
        super().__init__()
        self.capturing = False
        self.blocks: list[str] = []
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            cls = dict(attrs).get("class", "")
            if any(k in cls for k in ("definition", "theorem", "key-equation")):
                self.capturing = True
                self._buf = []

    def handle_endtag(self, tag):
        if tag == "div" and self.capturing:
            self.capturing = False
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                self.blocks.append(text)

    def handle_data(self, data):
        if self.capturing:
            self._buf.append(data)


def scrape(html: str, source: str) -> tuple[list[dict], int]:
    parser = _BlockExtractor()
    parser.feed(html)
    notes, dropped = [], 0
    for block in parser.blocks:
        topic = tag_for(block)
        if topic is None:
            dropped += 1
            continue
        # Split "Front. Back" heuristically on the first sentence boundary.
        head, _, tail = block.partition(". ")
        notes.append(
            {
                "front": head.strip() + ("?" if not head.strip().endswith("?") else ""),
                "back": (tail or head).strip(),
                "topic": topic,
                "source": source,
            }
        )
    return notes, dropped


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic open-licensed scraper (no AI).")
    ap.add_argument("html_file", type=Path, help="Local HTML from a CC-BY/public-domain source")
    ap.add_argument("--source", required=True, help="Citation string, e.g. 'OpenStax Calculus Vol.1 (CC BY 4.0)'")
    ap.add_argument("--out", type=Path, required=True, help="Output YAML path")
    args = ap.parse_args()
    notes, dropped = scrape(args.html_file.read_text("utf-8"), args.source)
    args.out.write_text(yaml.safe_dump(notes, allow_unicode=True, sort_keys=False), "utf-8")
    print(f"wrote {len(notes)} notes to {args.out}; dropped {dropped} untaggable blocks")


if __name__ == "__main__":
    main()
