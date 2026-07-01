# Speedrun content tooling (deterministic, NO AI)

Builds the GRE-Math exam profile and seed deck used by both desktop and Android.
Everything here is rule-based / hand-authored — no LLM or model calls.

## Setup
    cd repos/anki/speedrun
    uv sync

## Build the seed deck
    uv run python seed/build_seed_deck.py
    # -> out/gre_math_seed.apkg  (import into Anki desktop or AnkiDroid)

## Validate
    uv run pytest tests/ -v

## Scraper (FLEX)
    uv run python scraper/scrape_openstax.py --help
    # Emits YAML in the seed/ note shape from open-licensed sources only.
    # Every emitted note carries a Source citation and rule-based topic tags.

## License
All content shipped here is open-licensed (OpenStax CC-BY, public domain).
ETS released forms are NOT redistributed; used only for our own benchmarking.
