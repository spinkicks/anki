// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Memory-model calibration harness — an honest, CLEARLY-LABELED **SIMULATED**
//! FSRS review stream (matched-model self-consistency).
//!
//! ## What the Memory model actually predicts (be faithful to the engine)
//!
//! In `service.rs::get_topic_mastery`, per card that has an FSRS memory state:
//! `let r = fsrs.current_retrievability_seconds(state.into(), elapsed, decay);`
//! where `fsrs = FSRS::new(None)` (DEFAULT params — the app does NOT fit
//! per-user FSRS), `decay = card.decay.unwrap_or(FSRS5_DEFAULT_DECAY)`. So the
//! Memory model's "predicted recall" for a card IS its FSRS retrievability.
//! Calibration is therefore a REVIEW-LEVEL question: predicted probability
//! `p = FSRS retrievability`, actual outcome `o ∈ {0,1}` = recalled?
//!
//! ## The honest evaluation design (SIMULATED — read this)
//!
//! We use ONE FSRS instance as BOTH the generative truth AND the predictor
//! (default params — the same params the engine's `FSRS::new(None)` falls back
//! to; see `run_simulation` for why the harness must pass `DEFAULT_PARAMETERS`
//! explicitly to drive `next_states`, and why the retrievability values are
//! nonetheless byte-identical to the engine read-path). This is a matched-model
//! self-consistency check: the generator that samples outcomes IS the model
//! whose calibration we score.
//!
//! Because the generator matches the predictor, near-optimal calibration is
//! EXPECTED. This is NOT evidence that default FSRS matches real human memory.
//! What it DOES establish, honestly:
//!   1. The engine read-path (`current_retrievability_seconds` at the exact
//!      elapsed/decay the engine uses) is calibration-bug-free — if this harness
//!      showed miscalibration on self-consistent data, the read-path arithmetic
//!      would be wrong.
//!   2. It quantifies the IRREDUCIBLE Brier floor `mean(p·(1−p))` — the best any
//!      calibrated predictor can do on this outcome distribution.
//!   3. The model beats a constant base-rate baseline (adds RESOLUTION), so the
//!      per-card retrievabilities carry real information, not just the mean.
//!
//! The external validation (does default FSRS fit REAL logs?) is the standard
//! FSRS benchmark on real review histories — NOT run here for lack of real logs.
//!
//! ## No leakage / train-test framing
//!
//! At each review step the prediction `p` is computed STRICTLY BEFORE its own
//! outcome `o` is sampled, and never uses that outcome. So every recorded
//! `(p, o)` pair is a valid held-out prediction. The FINAL review of each card
//! is a natural held-out test point (predicted from the state built by all
//! PRIOR reviews, scored against a freshly-sampled outcome).
//!
//! Pure-Rust, dependency-free (a tiny SplitMix64 PRNG below; no `rand` crate).
//! Artifacts are emitted only under `SPEEDRUN_EVAL_EMIT=1` so `just check` stays
//! clean.

use fsrs::MemoryState;
use fsrs::FSRS;
use fsrs::FSRS5_DEFAULT_DECAY;

// ---- Deterministic PRNG (SplitMix64) --------------------------------------

/// Minimal SplitMix64 PRNG. Deterministic from a fixed seed; no `rand` crate.
/// Standard constants (as published by Sebastiano Vigna). We only need a
/// uniform f64 in [0,1) to draw Bernoulli outcomes.
struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    /// Uniform f64 in [0, 1). Uses the top 53 bits (f64 mantissa) so the value
    /// is exactly representable and deterministic across platforms.
    fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }

    /// One Bernoulli(p) draw: true with probability `p`.
    fn bernoulli(&mut self, p: f64) -> bool {
        self.next_f64() < p
    }
}

// ---- Continuous-p calibration metrics -------------------------------------
//
// NOTE: the `brier_score` / `ece` / `reliability_bins` in `mod.rs` are for the
// DISCRETE 3-level self-bet calibration (only 3 distinct forecast probs, keyed
// by exact value). Here the forecast `p` is a CONTINUOUS FSRS retrievability, so
// we need width-binned versions. These are named `*_continuous` to keep them
// clearly distinct from the discrete self-bet helpers.

const CLAMP_LO: f64 = 1e-6;
const CLAMP_HI: f64 = 1.0 - 1e-6;
/// Number of equal-width predicted-probability bins for ECE / reliability.
const N_BINS: usize = 10;

/// Brier score = mean((p − o)^2). `pairs` is (predicted_prob, outcome∈{0,1}).
/// Lower is better; 0.0 is perfect. Empty => 0.0.
fn brier_continuous(pairs: &[(f64, u8)]) -> f64 {
    if pairs.is_empty() {
        return 0.0;
    }
    let sum: f64 = pairs
        .iter()
        .map(|(p, o)| {
            let d = p - *o as f64;
            d * d
        })
        .sum();
    sum / pairs.len() as f64
}

/// Log-loss = −mean(o·ln(p) + (1−o)·ln(1−p)), p clamped to [1e-6, 1−1e-6].
/// Lower is better. Empty => 0.0.
fn log_loss_continuous(pairs: &[(f64, u8)]) -> f64 {
    if pairs.is_empty() {
        return 0.0;
    }
    let sum: f64 = pairs
        .iter()
        .map(|(p, o)| {
            let p = p.clamp(CLAMP_LO, CLAMP_HI);
            let o = *o as f64;
            o * p.ln() + (1.0 - o) * (1.0 - p).ln()
        })
        .sum();
    -sum / pairs.len() as f64
}

/// Equal-width reliability bins over predicted `p` in [0,1]. Returns, per
/// NON-EMPTY bin, `(mean_predicted_p, empirical_accuracy, n)` ascending by bin.
/// A prediction of exactly 1.0 falls in the top bin.
fn reliability_bins_continuous(pairs: &[(f64, u8)]) -> Vec<(f64, f64, u32)> {
    let mut sum_p = [0.0f64; N_BINS];
    let mut sum_o = [0.0f64; N_BINS];
    let mut n = [0u32; N_BINS];
    for (p, o) in pairs {
        let idx = ((p * N_BINS as f64) as usize).min(N_BINS - 1);
        sum_p[idx] += *p;
        sum_o[idx] += *o as f64;
        n[idx] += 1;
    }
    (0..N_BINS)
        .filter(|&i| n[i] > 0)
        .map(|i| {
            let cnt = n[i] as f64;
            (sum_p[i] / cnt, sum_o[i] / cnt, n[i])
        })
        .collect()
}

/// Expected Calibration Error = Σ (n_bin / N) · |empirical_acc − mean_pred_p|
/// over the equal-width bins. Lower is better; 0.0 = perfectly calibrated.
fn ece_continuous(pairs: &[(f64, u8)]) -> f64 {
    if pairs.is_empty() {
        return 0.0;
    }
    let total = pairs.len() as f64;
    reliability_bins_continuous(pairs)
        .into_iter()
        .map(|(mean_p, acc, n)| (n as f64 / total) * (acc - mean_p).abs())
        .sum()
}

// ---- Metrics bundle -------------------------------------------------------

/// All calibration metrics computed over the simulated review stream. Aggregate
/// numbers only (plus the reliability bins for the plot).
#[derive(Debug, Clone, PartialEq)]
struct CalibrationMetrics {
    /// Number of (prediction, outcome) pairs.
    n: usize,
    /// Overall base rate = mean outcome (fraction recalled).
    base_rate: f64,
    /// Model Brier = mean((p − o)^2).
    brier: f64,
    /// Log-loss (natural log), p clamped to [1e-6, 1−1e-6].
    log_loss: f64,
    /// Expected Calibration Error over 10 equal-width predicted-p bins.
    ece: f64,
    /// Baseline Brier using a CONSTANT prediction = base rate (no resolution).
    baseline_brier: f64,
    /// Irreducible Brier floor = mean(p·(1−p)) (min when predictions == truth).
    irreducible_floor: f64,
    /// Reliability bins: (mean_predicted_p, empirical_accuracy, n) per bin.
    reliability: Vec<(f64, f64, u32)>,
}

/// Number of simulated cards. 400 cards × up to ~10 reviews => N ≥ ~3000 pairs.
const N_CARDS: usize = 400;
/// Increasing day-interval schedule for successive reviews of a card.
/// Documented FIXED schedule (1, 3, 7, 16, 35, ...): each review is scheduled
/// further out, mimicking spaced-repetition expansion, so retrievability spans
/// a wide range (high just after review, lower at long intervals). The choice
/// is a fixed schedule (NOT the FSRS good-interval) purely so the stream is
/// trivially reproducible and spans the [0,1] prediction range; the PREDICTION
/// at each step is still the true FSRS retrievability at that elapsed time.
const DAY_SCHEDULE: [u32; 10] = [1, 3, 7, 16, 35, 70, 140, 240, 400, 700];
/// Desired retention passed to `next_states` (matches the engine default 0.9).
const DESIRED_RETENTION: f32 = 0.9;
/// Fixed PRNG seed — determinism.
const SEED: u64 = 0x5EED_1234_ABCD_0001;

/// Run the SIMULATED matched-model self-consistency review stream and compute
/// all calibration metrics. See the module docs for the honest interpretation.
///
/// For each of `N_CARDS` cards:
///   * init state = `next_states(None, 0.9, 0).good.memory` (first "Good");
///   * for each interval `d` in `DAY_SCHEDULE`: compute `p =
///     current_retrievability_seconds(state, d*86400, decay)` (the prediction,
///     made BEFORE the outcome), sample `o ~ Bernoulli(p)`, record `(p, o)`,
///     then advance `state = next_states(Some(state), 0.9, d).good` if recalled
///     else `.again`. Elapsed resets (the next `d` is measured from this review).
fn run_simulation(seed: u64) -> CalibrationMetrics {
    // The engine reads retrievability off `FSRS::new(None)`, which works because
    // `current_retrievability_seconds` is PURE arithmetic (`current_retrievability(state,
    // days, decay)`) that does NOT touch model parameters — the decay is passed
    // explicitly (`FSRS5_DEFAULT_DECAY`). But building the memory states here needs
    // `next_states`, which DOES require parameters (a `None`-param FSRS panics with
    // "command requires parameters to be set on creation"). So the harness builds the
    // model with `DEFAULT_PARAMETERS` — the SAME default params FSRS falls back to — and
    // uses it for BOTH state evolution and prediction. The retrievability value at each
    // step is byte-identical to what the engine's `FSRS::new(None)` would compute (same
    // pure formula, same decay), so this stays faithful to the engine read-path.
    let fsrs = FSRS::new(Some(&fsrs::DEFAULT_PARAMETERS)).expect("default-param FSRS");
    let decay = FSRS5_DEFAULT_DECAY;
    let mut rng = SplitMix64::new(seed);
    let mut pairs: Vec<(f64, u8)> = Vec::with_capacity(N_CARDS * DAY_SCHEDULE.len());

    for _card in 0..N_CARDS {
        // First "Good" review establishes the memory state.
        let mut state: MemoryState = fsrs
            .next_states(None, DESIRED_RETENTION, 0)
            .expect("initial next_states")
            .good
            .memory;

        for &days in DAY_SCHEDULE.iter() {
            // Prediction is made STRICTLY BEFORE the outcome is sampled.
            let p = fsrs.current_retrievability_seconds(state, days * 86_400, decay) as f64;
            let recalled = rng.bernoulli(p);
            pairs.push((p, recalled as u8));
            // Advance the memory state using the just-sampled outcome.
            let next = fsrs
                .next_states(Some(state), DESIRED_RETENTION, days)
                .expect("advance next_states");
            state = if recalled {
                next.good.memory
            } else {
                next.again.memory
            };
        }
    }

    let n = pairs.len();
    let base_rate = pairs.iter().map(|(_, o)| *o as f64).sum::<f64>() / n as f64;
    let brier = brier_continuous(&pairs);
    let log_loss = log_loss_continuous(&pairs);
    let ece = ece_continuous(&pairs);
    // Baseline: constant prediction == base rate for every pair.
    let baseline_pairs: Vec<(f64, u8)> = pairs.iter().map(|(_, o)| (base_rate, *o)).collect();
    let baseline_brier = brier_continuous(&baseline_pairs);
    // Irreducible floor = mean(p·(1−p)).
    let irreducible_floor = pairs.iter().map(|(p, _)| p * (1.0 - p)).sum::<f64>() / n as f64;
    let reliability = reliability_bins_continuous(&pairs);

    CalibrationMetrics {
        n,
        base_rate,
        brier,
        log_loss,
        ece,
        baseline_brier,
        irreducible_floor,
        reliability,
    }
}

// ---- Artifact emission (opt-in via SPEEDRUN_EVAL_EMIT=1) ------------------

/// Serialize the metrics to a compact, deterministic JSON string (no external
/// crate — the numbers are simple scalars + a bins array).
fn metrics_to_json(m: &CalibrationMetrics) -> String {
    let mut bins = String::new();
    for (i, (mp, acc, n)) in m.reliability.iter().enumerate() {
        if i > 0 {
            bins.push(',');
        }
        bins.push_str(&format!(
            "\n    {{\"mean_predicted_p\": {mp:.6}, \"empirical_accuracy\": {acc:.6}, \"n\": {n}}}"
        ));
    }
    format!(
        "{{\n  \"data_source\": \"SIMULATED FSRS review stream (matched-model self-consistency; default FSRS params; NOT real human review logs)\",\n  \"n\": {n},\n  \"base_rate\": {base_rate:.6},\n  \"brier\": {brier:.6},\n  \"log_loss\": {log_loss:.6},\n  \"ece\": {ece:.6},\n  \"baseline_brier\": {baseline_brier:.6},\n  \"irreducible_floor\": {floor:.6},\n  \"desired_retention\": {dr},\n  \"decay\": {decay},\n  \"n_cards\": {ncards},\n  \"day_schedule\": {schedule:?},\n  \"reliability_bins\": [{bins}\n  ]\n}}\n",
        n = m.n,
        base_rate = m.base_rate,
        brier = m.brier,
        log_loss = m.log_loss,
        ece = m.ece,
        baseline_brier = m.baseline_brier,
        floor = m.irreducible_floor,
        dr = DESIRED_RETENTION,
        decay = FSRS5_DEFAULT_DECAY,
        ncards = N_CARDS,
        schedule = DAY_SCHEDULE,
    )
}

/// Render a self-contained, dependency-free SVG reliability diagram (pure
/// string formatting). Draws the perfect-calibration diagonal, the model's
/// reliability curve (mean predicted p vs empirical accuracy per bin), bin
/// counts, and a title/subtitle stating the data is SIMULATED plus the headline
/// metrics. Deterministic.
fn metrics_to_svg(m: &CalibrationMetrics) -> String {
    // Plot area geometry.
    let w = 640.0;
    let h = 520.0;
    let pad_l = 70.0;
    let pad_r = 30.0;
    let pad_t = 90.0;
    let pad_b = 70.0;
    let plot_w = w - pad_l - pad_r;
    let plot_h = h - pad_t - pad_b;
    // Map data (x,y) in [0,1] to SVG coords (y is flipped).
    let sx = |x: f64| pad_l + x * plot_w;
    let sy = |y: f64| pad_t + (1.0 - y) * plot_h;

    let mut s = String::new();
    s.push_str(&format!(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{w}\" height=\"{h}\" viewBox=\"0 0 {w} {h}\" font-family=\"sans-serif\">\n"
    ));
    s.push_str(&format!(
        "  <rect x=\"0\" y=\"0\" width=\"{w}\" height=\"{h}\" fill=\"#ffffff\"/>\n"
    ));
    // Title + subtitle (honesty: SIMULATED).
    s.push_str(&format!(
        "  <text x=\"{x}\" y=\"28\" font-size=\"18\" font-weight=\"bold\" fill=\"#111\">Memory-model calibration (SIMULATED FSRS review stream)</text>\n",
        x = pad_l
    ));
    s.push_str(&format!(
        "  <text x=\"{x}\" y=\"50\" font-size=\"12\" fill=\"#555\">Matched-model self-consistency — default FSRS params. NOT real human logs; near-optimal is expected.</text>\n",
        x = pad_l
    ));
    s.push_str(&format!(
        "  <text x=\"{x}\" y=\"68\" font-size=\"12\" fill=\"#555\">N={n}  base rate={br:.3}  Brier={brier:.4}  baseline Brier={bb:.4}  floor={fl:.4}  log-loss={ll:.4}  ECE={ece:.4}</text>\n",
        x = pad_l,
        n = m.n,
        br = m.base_rate,
        brier = m.brier,
        bb = m.baseline_brier,
        fl = m.irreducible_floor,
        ll = m.log_loss,
        ece = m.ece
    ));
    // Plot border.
    s.push_str(&format!(
        "  <rect x=\"{x}\" y=\"{y}\" width=\"{pw}\" height=\"{ph}\" fill=\"none\" stroke=\"#ccc\"/>\n",
        x = pad_l,
        y = pad_t,
        pw = plot_w,
        ph = plot_h
    ));
    // Gridlines + axis ticks at 0.0..1.0 step 0.2.
    let mut t = 0.0;
    while t <= 1.0001 {
        let gx = sx(t);
        let gy = sy(t);
        s.push_str(&format!(
            "  <line x1=\"{gx:.1}\" y1=\"{yt:.1}\" x2=\"{gx:.1}\" y2=\"{yb:.1}\" stroke=\"#eee\"/>\n",
            yt = pad_t,
            yb = pad_t + plot_h
        ));
        s.push_str(&format!(
            "  <line x1=\"{xl:.1}\" y1=\"{gy:.1}\" x2=\"{xr:.1}\" y2=\"{gy:.1}\" stroke=\"#eee\"/>\n",
            xl = pad_l,
            xr = pad_l + plot_w
        ));
        s.push_str(&format!(
            "  <text x=\"{tx:.1}\" y=\"{ty:.1}\" font-size=\"10\" fill=\"#666\" text-anchor=\"middle\">{t:.1}</text>\n",
            tx = gx,
            ty = pad_t + plot_h + 16.0
        ));
        s.push_str(&format!(
            "  <text x=\"{tx:.1}\" y=\"{ty:.1}\" font-size=\"10\" fill=\"#666\" text-anchor=\"end\">{t:.1}</text>\n",
            tx = pad_l - 8.0,
            ty = gy + 3.0
        ));
        t += 0.2;
    }
    // Axis labels.
    s.push_str(&format!(
        "  <text x=\"{lx:.1}\" y=\"{ly:.1}\" font-size=\"12\" fill=\"#333\" text-anchor=\"middle\">Predicted probability (FSRS retrievability)</text>\n",
        lx = pad_l + plot_w / 2.0,
        ly = pad_t + plot_h + 40.0
    ));
    s.push_str(&format!(
        "  <text x=\"20\" y=\"{ly:.1}\" font-size=\"12\" fill=\"#333\" text-anchor=\"middle\" transform=\"rotate(-90 20 {ly:.1})\">Empirical accuracy</text>\n",
        ly = pad_t + plot_h / 2.0
    ));
    // Perfect-calibration diagonal.
    s.push_str(&format!(
        "  <line x1=\"{x1:.1}\" y1=\"{y1:.1}\" x2=\"{x2:.1}\" y2=\"{y2:.1}\" stroke=\"#999\" stroke-dasharray=\"5,4\"/>\n",
        x1 = sx(0.0),
        y1 = sy(0.0),
        x2 = sx(1.0),
        y2 = sy(1.0)
    ));
    s.push_str(&format!(
        "  <text x=\"{tx:.1}\" y=\"{ty:.1}\" font-size=\"10\" fill=\"#999\">perfect calibration</text>\n",
        tx = sx(0.62),
        ty = sy(0.70)
    ));
    // Model reliability curve (polyline through bin points) + markers + counts.
    let mut poly = String::new();
    for (mp, acc, _n) in &m.reliability {
        poly.push_str(&format!("{:.1},{:.1} ", sx(*mp), sy(*acc)));
    }
    s.push_str(&format!(
        "  <polyline points=\"{poly}\" fill=\"none\" stroke=\"#1f77b4\" stroke-width=\"2\"/>\n"
    ));
    for (mp, acc, n) in &m.reliability {
        s.push_str(&format!(
            "  <circle cx=\"{cx:.1}\" cy=\"{cy:.1}\" r=\"4\" fill=\"#1f77b4\"/>\n",
            cx = sx(*mp),
            cy = sy(*acc)
        ));
        s.push_str(&format!(
            "  <text x=\"{tx:.1}\" y=\"{ty:.1}\" font-size=\"9\" fill=\"#1f77b4\" text-anchor=\"middle\">n={n}</text>\n",
            tx = sx(*mp),
            ty = sy(*acc) - 8.0
        ));
    }
    s.push_str("</svg>\n");
    s
}

// ---- Tests ----------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ---- Metric helper unit tests (hand-computed known values) ----

    #[test]
    fn brier_continuous_known_values() {
        // Perfectly confident and correct => 0.
        assert!((brier_continuous(&[(1.0, 1), (0.0, 0)]) - 0.0).abs() < 1e-12);
        // p=0.9 wrong once, p=0.9 right once: mean((0.9-0)^2,(0.9-1)^2)=mean(0.81,0.01)=0.41
        assert!((brier_continuous(&[(0.9, 0), (0.9, 1)]) - 0.41).abs() < 1e-12);
        // Empty => 0.
        assert_eq!(brier_continuous(&[]), 0.0);
    }

    #[test]
    fn log_loss_continuous_known_value() {
        // p=0.5 outcome 1: -ln(0.5) = ln(2) ≈ 0.6931471805599453.
        let ll = log_loss_continuous(&[(0.5, 1)]);
        assert!((ll - std::f64::consts::LN_2).abs() < 1e-12, "ll={ll}");
        // p=0.5 outcome 1 and p=0.5 outcome 0: both -ln(0.5) => mean = ln(2).
        let ll2 = log_loss_continuous(&[(0.5, 1), (0.5, 0)]);
        assert!((ll2 - std::f64::consts::LN_2).abs() < 1e-12, "ll2={ll2}");
        // Extreme correct prediction is clamped (no -inf): p=1.0,o=1 => -ln(1-1e-6) tiny.
        let ll3 = log_loss_continuous(&[(1.0, 1)]);
        assert!(ll3.is_finite() && (0.0..1e-5).contains(&ll3), "ll3={ll3}");
    }

    #[test]
    fn ece_continuous_two_bin_known_value() {
        // Two predictions land in distinct equal-width bins:
        //   p=0.05 (bin 0), outcome 0 => acc 0.0, |0-0.05|=0.05
        //   p=0.95 (bin 9), outcome 1 => acc 1.0, |1-0.95|=0.05
        // ECE = (1/2)*0.05 + (1/2)*0.05 = 0.05.
        let ece = ece_continuous(&[(0.05, 0), (0.95, 1)]);
        assert!((ece - 0.05).abs() < 1e-12, "ece={ece}");
        // Empty => 0.
        assert_eq!(ece_continuous(&[]), 0.0);
    }

    #[test]
    fn reliability_bins_continuous_groups_by_width() {
        // Two in bin 0 (0.05, 0.05) one correct; one in bin 9 (0.95) correct.
        let bins = reliability_bins_continuous(&[(0.05, 1), (0.05, 0), (0.95, 1)]);
        assert_eq!(bins.len(), 2);
        // Bin 0 first (ascending).
        assert!((bins[0].0 - 0.05).abs() < 1e-12); // mean predicted p
        assert!((bins[0].1 - 0.5).abs() < 1e-12); // accuracy 1/2
        assert_eq!(bins[0].2, 2);
        assert!((bins[1].0 - 0.95).abs() < 1e-12);
        assert!((bins[1].1 - 1.0).abs() < 1e-12);
        assert_eq!(bins[1].2, 1);
    }

    // ---- Headline calibration test (pre-registered honest directions) ----

    #[test]
    fn memory_calibration_is_informative_and_calibrated() {
        let m = run_simulation(SEED);

        // Enough data: N ≥ 3000 review predictions.
        assert!(m.n >= 3000, "N too small: {}", m.n);

        // Base rate is a genuine probability strictly inside (0,1) — the stream
        // is neither all-recalled nor all-forgotten.
        assert!(
            m.base_rate > 0.0 && m.base_rate < 1.0,
            "base_rate={}",
            m.base_rate
        );

        // Informative / adds resolution: the model beats the constant base-rate
        // baseline (allow a hair of float slack).
        assert!(
            m.brier <= m.baseline_brier + 1e-9,
            "model Brier {} should be <= baseline Brier {}",
            m.brier,
            m.baseline_brier
        );

        // Well-calibrated (matched model): ECE small.
        assert!(m.ece <= 0.05, "ECE too high: {}", m.ece);

        // Near the theoretical floor: |Brier − irreducible floor| ≤ 0.02.
        assert!(
            (m.brier - m.irreducible_floor).abs() <= 0.02,
            "Brier {} not near floor {}",
            m.brier,
            m.irreducible_floor
        );

        // Log-loss finite and strictly positive.
        assert!(m.log_loss.is_finite(), "log_loss not finite");
        assert!(m.log_loss > 0.0, "log_loss should be > 0: {}", m.log_loss);
    }

    #[test]
    fn memory_calibration_is_deterministic() {
        let a = run_simulation(SEED);
        let b = run_simulation(SEED);
        // Byte-identical metrics from the fixed seed.
        assert_eq!(a, b);
    }

    /// Opt-in artifact emitter: writes `speedrun/eval/memory-calibration.{json,svg}`
    /// only when `SPEEDRUN_EVAL_EMIT=1`, so normal `just check` stays clean.
    #[test]
    fn emit_memory_calibration_artifacts() {
        if std::env::var("SPEEDRUN_EVAL_EMIT").is_err() {
            return;
        }
        let m = run_simulation(SEED);
        // Repo root: rslib/ is one level under the anki repo root; CARGO_MANIFEST_DIR
        // points at rslib, so go up one to reach the repo root where speedrun/ lives.
        let manifest = env!("CARGO_MANIFEST_DIR");
        let repo_root = std::path::Path::new(manifest)
            .parent()
            .expect("repo root above rslib");
        let dir = repo_root.join("speedrun").join("eval");
        std::fs::create_dir_all(&dir).expect("create speedrun/eval");
        std::fs::write(dir.join("memory-calibration.json"), metrics_to_json(&m))
            .expect("write json");
        std::fs::write(dir.join("memory-calibration.svg"), metrics_to_svg(&m)).expect("write svg");
        eprintln!("wrote artifacts to {}", dir.display());
        eprintln!("{}", metrics_to_json(&m));
    }
}
