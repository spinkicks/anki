# Speedrun content tooling (deterministic, NO AI)

Builds the GRE-Math exam profile and seed deck used by both desktop and Android.
Everything here is rule-based / hand-authored — no LLM or model calls.

## IMPORTANT: use the `uvw` wrapper, not bare `uv`

This toolchain lives inside the `repos/anki` fork, whose `check:minilints`
copyright scan walks the whole working tree. A `.venv` created here would make it
flag every third-party site-packages file. So we keep the venv **out of the
anki tree** via `UV_PROJECT_ENVIRONMENT` (default `~/.speedrun-content-venv`),
scoped through a wrapper — do NOT run bare `uv sync` in this directory.

Use `uvw.sh` (bash) or `uvw.ps1` (PowerShell); both set the out-of-tree venv and
forward all args to `uv`. Override the location by exporting
`UV_PROJECT_ENVIRONMENT` yourself first.

## Setup

    bash speedrun/uvw.sh sync
    # PowerShell: pwsh speedrun/uvw.ps1 sync

## Build the seed deck

    bash speedrun/uvw.sh run python seed/build_seed_deck.py
    # -> out/gre_math_seed.apkg  (import into Anki desktop or AnkiDroid)

## Validate

    bash speedrun/uvw.sh run pytest tests/ -v

## Scraper (FLEX)

    bash speedrun/uvw.sh run python scraper/scrape_openstax.py --help
    # Emits YAML in the seed/ note shape from open-licensed sources only.
    # Every emitted note carries a Source citation and rule-based topic tags.

> Post-Wednesday follow-up (per root AGENTS.md): this content toolchain's real
> home is the umbrella `speedrun` repo, not the anki fork. Relocating it there
> permanently removes the venv-vs-lint issue. Tracked as a follow-up; not done
> now to avoid unwinding the committed A0–A2 work.

## License

All content shipped here is open-licensed (OpenStax CC-BY, public domain).
ETS released forms are NOT redistributed; used only for our own benchmarking.
