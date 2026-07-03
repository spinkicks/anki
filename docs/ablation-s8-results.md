# §8 Interleaving Ablation — Results

An honest, pre-registered comparison of the three shipped reorder modes
(`AblationMode` **Full** / **FeatureOff** / **Plain**) on one fixed, deterministic
input. This measures the **ordering effect** the topic-aware interleave directly
produces — not a learning-outcome study (see [Scope & caveats](#scope--caveats)).

> **Honesty up front:** one of the two pre-registered metrics **failed** its
> predicted direction. We report the miss rather than tuning it away, and explain
> why it was mis-specified. See [Verdict](#verdict).

## Why one build, not three

§8/BUILD-WORKFLOW originally framed this as a "3-build ablation" (full /
feature-off / plain). The engine's `AblationMode` enum lets us select the mode
**per call** to `speedrun_reorder_new(deck_id, topic_weights, mode)`, so three
separate app builds are unnecessary. The harness drives all three modes on the
**same** input in one process — strictly more controlled (identical input,
identical engine, no build drift) and CI-runnable.

## Pre-registered metrics (written before measuring)

The topic-aware interleave exists to do two things (DECISIONS.md Decision 3;
PRD §4/§8): **(1)** interleave — spread same-topic cards apart (Rohrer & Taylor
2007); **(2)** front-load high points-at-stake (exam-weight) topics earlier. One
metric was pre-registered for each.

Let the resulting position order be the topic sequence `t_0 … t_{n-1}` (cards
sorted ascending by their resulting new-card position `due`, ties by card id).
`w_i` is the exam `ets_weight` of a card's matched topic; a card is *matched* if
a note tag equals a weighted topic or is a hierarchical descendant `topic::…`.

### M1 — same-topic adjacency rate (PRIMARY, anti-clumping)

```
adjacency = |{ i : t_i and t_{i+1} are both matched and equal }| / (n - 1)
```

**Lower is better** (fewer same-topic neighbours = better interleaving). Unmatched
cards break a run and are never counted as a same-topic pair.

### M2 — normalized weighted **mean** position (SECONDARY, front-loading)

```
wmp = Σ(w_i · p_i) / Σ(w_i)      (p_i = 1-based position of matched card i)
M2  = (wmp - 1) / (n - 1)        (normalized to [0,1])
```

**Lower is better** (high-weight topics surfaced earlier).

### Pre-registered directions ("what counts as Full winning")

On a **realistic authored deck** — cards added grouped topic-by-topic, the way a
human authors one (all Calculus cards, then all Linear-Algebra cards), which is
also the note-id order the `FeatureOff` baseline sorts by — we predicted:

- **M1:** `Full < FeatureOff` and `Full < Plain` (strict); `FeatureOff == Plain`
  (both reflect the grouped order).
- **M2:** `Full ≤ FeatureOff` and `Full ≤ Plain`.

Full's spread is **best-effort**, not a hard no-adjacency guarantee (see the
`interleave_is_best_effort_not_hard_no_adjacency` engine test): a dominant topic's
surplus trails adjacently in the tail. We therefore assert the **direction**, not
`adjacency == 0`.

## Input (fixed, reproducible)

Synthetic new cards with a topic mix mirroring the seed exam profile
(`speedrun/exam_profiles/gre_math.json`): the 8 leaf topics with their real
`ets_weight`s, card counts per topic roughly proportional to those weights
(points-at-stake ⇒ more cards, as a real study deck would emphasize). Cards are
added **grouped by area** (all calc, then all linear_algebra) — realistic
authoring order. Fully deterministic: fixed topic list, fixed counts, fixed
insertion order, no RNG. `n = 40` cards.

| Topic | `ets_weight` | cards |
|---|---|---|
| `calc::single_var::integration` | 0.16 | 8 |
| `calc::multivar` | 0.15 | 7 |
| `calc::single_var::differentiation` | 0.14 | 6 |
| `calc::limits` | 0.10 | 4 |
| `calc::sequences_series` | 0.10 | 4 |
| `linear_algebra::eigen` | 0.10 | 4 |
| `linear_algebra::matrices` | 0.09 | 3 |
| `linear_algebra::vector_spaces` | 0.08 | 2 |
| `linear_algebra::linear_maps` | 0.08 | 2 |

## Results

Measured by the harness (`cargo test … -- --nocapture`). All arrows: **lower is
better**.

| Mode | M1 adjacency ↓ | M2 wmean pos ↓ | M3 wfirst appear ↓ |
|---|---|---|---|
| **Full** | **0.0000** | 0.5241 | **0.0864** |
| FeatureOff | 0.7949 | **0.4327** | 0.5049 |
| Plain | 0.7949 | **0.4327** | 0.5049 |

## Verdict

**M1 (primary, pre-registered): Full wins decisively.** Full drives same-topic
adjacency to **0.0000** — a perfect interleave on this input (no two same-topic
cards adjacent, because no single topic dominates all others combined). Both
baselines sit at **0.7949**: on a grouped authored deck ~80% of neighbouring
pairs share a topic. `FeatureOff == Plain` exactly, as predicted (both reflect the
grouped order — `FeatureOff` sorts by note-id, which *is* the grouped insertion
order; `Plain` is a no-op). This is the headline interleaving result and it holds
strongly.

**M2 (secondary, pre-registered): MISS — reported honestly.** The predicted
`Full ≤ baselines` **did not hold** (Full **0.5241** > baselines **0.4327**), and
it **cannot** hold by construction. Weighted-**mean** position rewards *clumping*
the single heaviest topic at the very front — exactly what the grouped-deck
baselines do (all 8 `integration` cards land at positions 1–8, minimizing that
topic's mean position). Interleaving **spreads** `integration`'s 8 cards to
positions 1, 9, 17, … which *necessarily raises* their mean position. **M2 is in
direct tension with the interleave objective**, so it is a mis-specified proxy for
front-loading. We do **not** tune the input to force it; the miss stands, and the
harness asserts the observed (structurally forced) `Full > baselines` so the
result cannot silently flip.

**M3 (exploratory, post-hoc — NOT pre-registered): front-loading, done right.**
After observing the M2 miss we added a metric that isolates front-loading without
penalizing spread: normalized weighted **first-appearance** position — the
weighted-mean of the position at which each high-weight topic *first* appears.

```
wfa = Σ_topic (w_topic · first_pos_topic) / Σ_topic w_topic
M3  = (wfa - 1) / (n - 1)
```

Here **Full 0.0864** vs baselines **0.5049**: Full surfaces the first card of each
high-weight topic far earlier (heaviest topic at position 1, next at 2, …),
whereas the grouped baselines don't reach the lighter-but-still-weighted
linear-algebra topics until the back half. So Full **does** front-load — the
pre-registered M2 was simply the wrong lens for it. M3 is labelled exploratory and
is not claimed as a pre-registered result.

### One-line summary

On a realistic grouped deck, **Full interleaving eliminates same-topic clumping
(0.00 vs 0.79 adjacency) and front-loads high-weight topics (0.09 vs 0.50
first-appearance)**. The one pre-registered metric that failed (M2, weighted-mean
position) failed because it structurally rewards the clumping the feature is
designed to remove — an honest mis-specification, kept on the record.

## Reproduction

From the `anki` repo (worktree `feat/ablation-harness`):

```sh
# Canonical (sets up protoc + i18n via ninja):
just test-rust

# Just the ablation harness, with the printed metric table:
cargo test -p anki speedrun::ablation -- --nocapture
```

If invoking `cargo` directly in a fresh worktree, the i18n build script needs the
translation submodules and `protoc` on the environment (both provided by the
`just`/ninja path):

```sh
git submodule update --init ftl/core-repo ftl/qt-repo
export PROTOC=/path/to/out/extracted/protoc/bin/protoc   # e.g. from a built checkout
cargo test -p anki speedrun::ablation -- --nocapture
```

- Harness: `rslib/src/speedrun/ablation.rs` (module `speedrun::ablation::harness`).
- Two tests: `ablation_three_modes_preregistered_metric` (measures + asserts the
  honest directions) and `ablation_metrics_are_deterministic` (byte-identical
  metrics across runs — §8 reproducibility).

## Scope & caveats

- **Best-effort spread, not a guarantee.** Full's `adjacency == 0.0000` here holds
  because no single topic dominates all others combined. When one topic dominates,
  its surplus trails adjacently in the tail (by design; see
  `interleave_is_best_effort_not_hard_no_adjacency`). The pre-registered claim is
  the *direction* (Full strictly beats the baselines), not zero adjacency.
- **Ordering effect, not a learning-outcome study.** This measures the *ordering*
  the interleave produces. Whether that ordering improves exam scores under equal
  study time is a controlled human study — a larger future item (FUTURE-PLANS.md),
  out of scope here.
- **Synthetic input.** The card mix is synthetic but mirrors the seed exam
  profile's real topic weights, with counts proportional to points-at-stake and a
  realistic grouped authoring order. Results are specific to that grouped-deck
  assumption: on a deck whose cards are already interleaved at authoring time, the
  baselines' M1 would be lower and the gap to Full would shrink.
- **A pre-registered prediction failed.** M2 is retained (computed, printed, and
  its true direction asserted) precisely so the miss stays visible; it is not
  quietly deleted. M3 is clearly marked exploratory.
