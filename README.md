<!-- SPEEDRUN FORK NOTE -->

> **Speedrun fork** — honest GRE Mathematics Subject Test trainer on Anki (desktop + Android, one shared Rust engine).
> **Engine:** `rslib/src/speedrun/` + append-only `proto/anki/speedrun.proto` — topic mastery (Wilson CI + abstention), Performance & Readiness scores (IRT→200–990, conformal range, give-up rule), points-at-stake new-card reorder + due-card weakness×topic interleave (`AblationMode` Full/FeatureOff/Plain), `Speedrun::Problem` MCQ bank + timed mini-mock, LS1 calibration (`GetCalibration`).
> **UI:** shared SvelteKit pages (`ts/routes/speedrun-*`) + Qt shell (`qt/aqt/speedrun*.py`); pure-SVG interactive visuals — **THE MAP** (`ts/routes/speedrun-map/`, an interactive prerequisite graph with tap-to-see downstream blast radius), a readiness gauge, and calibration reliability / memory→performance gap charts; Manrope wordmark + near-white `#F4F7FA` accent.
> **Run:** `just run` (Speedrun Home auto-opens) · tests: `cargo test -p anki speedrun::`
> **Project hub (docs, AI service, eval):** https://github.com/spinkicks/speedrun · **Upstream credit:** Anki README below.

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
