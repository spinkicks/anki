# AGENTS.md — anki fork (rslib engine + pylib + ts) [Speedrun]

This is our fork of ankitects/anki. See workspace-root AGENTS.md for global rules. AGPL-3.0-or-later; credit Anki.

## Build / test (exact)

- Builds are driven by **`just`** (see this repo's CLAUDE.md). Do NOT call `./ninja`, `./run`, or `tools/` directly.
- Run desktop: `just run` (first build slow; honors `rust-toolchain.toml` = 1.92.0; `just` wraps `tools/ninja`; install `just` + N2 + MSYS2 rsync in Phase 0)
- All checks: `just check` · Rust tests: `just test-rust`
- Quick iteration: `cargo check` / `cargo test -p anki <module>::`
- Python integration: `uv run pytest pylib/tests/<test>.py`

## Add a backend method (proto → Rust → Python), append-only

1. `proto/anki/scheduler.proto` (or new `proto/anki/speedrun.proto`): add message(s) + `rpc` in a service. NEW field numbers only.
2. Implement trait on `Collection`: `impl crate::services::SpeedrunService for Collection { fn … }` (mirror `rslib/src/decks/service.rs`); wire module into parent `mod.rs`.
3. Rebuild → `_backend_generated.py` gains the method. Add a clean Python wrapper in `pylib/anki/` (never call `col._backend.*` from app code).

## Our change lives here

- Review ordering: `rslib/src/scheduler/queue/builder/` (`gathering.rs`, `sorting.rs`, topic-aware `intersperser.rs`).
- Read-only `SpeedrunService` RPC: memory range, coverage, (later) readiness. Read-only → no transact needed.

## Invariants (hard)

- Mutations → `Collection::transact(Op::X, |col| {…})` returning `OpChanges`; never raw DB writes; never `transact_no_undo` for user-facing ops. (`rslib/src/ops.rs`, `collection/transact.rs`, `undo/`)
- DB-persisted proto fields: append-only; never renumber/reuse; `reserved` removals.
- Don't add native deps to rslib without checking cross-compile (OpenSSL banned; use rustls).
- Don't edit generated files (`*_generated.py`, `@generated/*`).

## Grounding

Use Serena (rust-analyzer) `find_symbol`/`find_referencing_symbols` + `ast-grep -l rust` before editing. Verify with `cargo check` / `./ninja check:rust` + `get_diagnostics_for_file`.
