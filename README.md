<!-- SPEEDRUN FORK NOTE -->

# Speedrun — an honest GRE Math Subject Test trainer, built on Anki

**Speedrun** is a fork of [Anki](https://apps.ankiweb.net) that turns the same spaced-repetition
engine into a focused trainer for the GRE Mathematics Subject Test. It runs on **desktop and Android
from one shared Rust engine**, and its guiding rule is *honesty*: every score carries a confidence
range and **abstains (`—`) when there isn't enough data**, instead of inventing a number.

> Independent learning fork — not affiliated with or endorsed by ETS or Ankitects. The upstream Anki
> project and its README are credited below, and this fork keeps Anki's license: **AGPL-3.0-or-later**.

## What the fork adds

### One engine, two apps
The core change lives in the Rust engine (`rslib/src/speedrun/`) behind an **append-only** gRPC surface
(`proto/anki/speedrun.proto`), so **desktop (this repo) and Android (AnkiDroid, via the
Anki-Android-Backend AAR) run the exact same scoring code**. The one mutating operation — a
points-at-stake new-card reorder plus a due-card weakness×topic interleave — goes through Anki's
`transact`/undo path, and ships with an `AblationMode` (Full / FeatureOff / Plain) for fair A/B testing.

### A persistent Speedrun shell (both platforms)
`ts/lib/speedrun/SpeedrunShell.svelte` is a single shared frame for every Speedrun page. It renders a
**persistent left sidebar** on desktop (collapsing to a compact top bar on phones) with **Home / The
Map / Memory** navigation and **Start Run / Mini-mock** practice actions, and owns the design tokens in
one place so every page stays consistent. It's the same Svelte surface on desktop and Android.

### A cohesive, honest study flow
Desktop runs as a **single Speedrun window** — Home / The Map / Memory share one webview, and the base
Anki window steps aside while you're in Speedrun (reversible via the `speedrunSingleWindow` profile flag).
Problem cards enforce an honest sequence: **place a Sure / Think / Guess confidence bet first** (it locks
in), then answer the multiple-choice — and your pick **persists through *Show Answer*** instead of
resetting. **Mini-mocks show a live count-up timer** (it's a timed set), and AI practice generation
**loops until it has 5 source-verified problems**, importing only what passes (or honestly reporting the
shortfall).

### Three honest scores
- **Memory** — per-topic mastery from FSRS retrievability with a **Wilson 95% interval**; abstains below the data threshold.
- **Performance** — **objectively key-checked**: multiple-choice answers are graded **in the engine** against the stored key (never client-trusted or self-rated), read from a synced attempts log, alongside a memory→performance transfer gap.
- **Readiness** — a flat-IRT ability mapped to the **200–990** scale with a **conformal range** and an explicit **give-up rule** when the data can't support a claim.

All three are computed deterministically in the engine and are range/abstain-tested.

### Four interactive, pure-SVG visuals
- **THE MAP** (`ts/routes/speedrun-map/`) — an interactive prerequisite graph; tap a topic to light up its downstream **"blast radius"** (every topic it gates).
- **Calibration reliability diagram** and a **Memory→Performance gap** chart on the Memory page.
- A **Readiness gauge** (with the conformal band drawn in) on Home.

### A problem bank + timed mini-mock
A scored multiple-choice note type (`Speedrun::Problem`) backed by a hand-authored, symbolically-verified
problem bank, plus a **timed mini-mock** (a filtered deck) that feeds the objective Performance signal.

### Learning-science study modes
- **Calibration (LS1)** — a pre-answer confidence self-bet (Sure / Think / Guess) scored by Brier/ECE.
- **Worked-examples-first with faded reveal (LS2)** — progressive, LaTeX-safe step reveal.
- **Honesty-guardrail copy (LS3)** — framing that renders only on real data.

### Optional, off-by-default AI practice generation (desktop)
A ⚡ **Generate practice** button can import *verified* extra problems from an **external** AI service —
the service lives in the project hub and is **never** imported into the engine. It is **OFF by default**
and stays disabled unless that service reports itself enabled. Because a packaged installer has no
environment variables, a **Tools → "Enable AI generation (this session)"** toggle
(`qt/aqt/speedrun_ai.py`) can flip the switch **in-memory for the current session only** — it never
supplies the API key and never bypasses the health check, so the kill-switch stays intact.

## Running it

From this repo (see the upstream [Development](./docs/development.md) guide for toolchain setup):

```bash
just run                          # desktop app — Speedrun Home auto-opens
cargo test -p anki speedrun::     # the fork's engine test suite (84 tests)
just bench                        # latency microbench: p50/p95/worst on a ~50k-card deck
```

A **prebuilt Windows installer** is published on the project hub's
[Releases page](https://github.com/spinkicks/speedrun/releases) — it bundles the seed deck and
auto-imports it on first launch, so the app opens with live (honest, mostly-abstaining) data. A
one-command launcher that builds and runs everything also lives in the hub
(`scripts/speedrun-launch.ps1 -All`).

**Project hub (design docs, the external AI service, evals):** https://github.com/spinkicks/speedrun

---

# Anki

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## Getting Started

### Contributing

Want to contribute to Anki? Check out the [Contribution Guidelines](./docs/contributing.md).

For more information on building and developing, please see [Development](./docs/development.md).

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)
