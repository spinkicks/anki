// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
import { ScoreScale } from "@generated/anki/speedrun_pb";
import {
    getCalibration,
    getCoverage,
    getExamProfile,
    getPerformanceReadiness,
    getTopicMastery,
} from "@generated/backend";

// Re-export so consumers (Svelte components, tests) can key band rendering off
// the scale without reaching into @generated directly.
export { ScoreScale };

// GRE scaled-score bounds — the single source of truth for the 200–990 track.
// Kept here (not hard-coded per component) so a scale-aware RangeBand and any
// Home copy normalize identically.
export const GRE_MIN = 200;
export const GRE_MAX = 990;

export interface ProfileTopic {
    id: string;
    name: string;
    ets_weight: number;
    prereqs: string[];
}
export interface ExamProfile {
    exam_id: string;
    name: string;
    topics: ProfileTopic[];
}

export interface Row {
    id: string;
    label: string;
    weight: number;
    isContainer: boolean; // ets_weight == 0 => group header, not a data row
    root: string; // "calc" | "linear_algebra"
    avgRecall: number;
    lower: number;
    upper: number;
    masteredCount: number;
    cardsWithData: number;
    gradedReviews: number;
    abstained: boolean;
    unlockN: number; // max(0, min_reviews - graded_reviews)
}

export async function loadProfile(examId = "gre_math"): Promise<ExamProfile | null> {
    const resp = await getExamProfile({ examId });
    if (!resp.profileJson) {
        return null;
    }
    return JSON.parse(resp.profileJson) as ExamProfile;
}

export async function loadRows(
    profile: ExamProfile,
    minReviews = 20,
): Promise<Row[]> {
    const leafIds = profile.topics.filter((t) => t.ets_weight > 0).map((t) => t.id);
    const mastery = await getTopicMastery({
        topics: leafIds,
        masteryThreshold: 0.9,
        minReviews,
    });
    const byTopic = new Map(mastery.topics.map((t) => [t.topic, t]));
    return profile.topics.map((t) => {
        const m = byTopic.get(t.id);
        const graded = m ? Number(m.gradedReviews) : 0;
        return {
            id: t.id,
            label: t.name,
            weight: t.ets_weight,
            isContainer: t.ets_weight === 0,
            root: t.id.split("::")[0],
            avgRecall: m ? m.avgRecall : 0,
            lower: m ? m.masteredLower : 0,
            upper: m ? m.masteredUpper : 1,
            masteredCount: m ? Number(m.masteredCount) : 0,
            cardsWithData: m ? Number(m.cardsWithData) : 0,
            gradedReviews: graded,
            abstained: m ? m.abstained : true,
            unlockN: Math.max(0, minReviews - graded),
        };
    });
}

export async function loadCoverage(
    profile: ExamProfile,
): Promise<{ covered: number; total: number; percent: number }> {
    const required = profile.topics.filter((t) => t.ets_weight > 0).map((t) => t.id);
    const c = await getCoverage({ requiredTags: required });
    return { covered: c.covered, total: c.total, percent: c.percent };
}

// PERFORMANCE / READINESS scaffolding from the engine. Abstains until enough
// real (timed problem) data exists — the UI must never fabricate a number.
export async function loadScaffold(profile: ExamProfile) {
    const leafIds = profile.topics.filter((t) => t.ets_weight > 0).map((t) => t.id);
    return await getPerformanceReadiness({ topics: leafIds });
}

// One score band carried across the TS boundary. Mirrors proto ScoreScaffold
// (point/lower/upper/percentile/scale) plus a per-row gapDelta (declarative
// recall − problem accuracy, from the topic message). `scale` tells the UI
// which track/units to render — a 200–990 value must never be shown on the
// 0..1 track. Defaults are honest: abstained=true, UNIT scale, zeros.
export interface ScaffoldCell {
    abstained: boolean;
    point: number;
    lower: number;
    upper: number;
    percentile: number;
    scale: ScoreScale;
    gapDelta: number;
}
export interface TopicScaffoldRow {
    performance: ScaffoldCell;
    readiness: ScaffoldCell;
    gapDelta: number;
}

// One actionable unlock hint for an abstaining Readiness score (proto
// UnlockRequirement), e.g. "Complete 3 more timed mini-mock(s)".
export interface UnlockHint {
    kind: string;
    have: number;
    need: number;
    human: string;
    topic: string;
}

// Response-level scaffold summary: the per-topic rows PLUS the exam-level
// overall Readiness headline (200–990), its abstain reason, and unlock hints.
export interface ScaffoldSummary {
    rows: Map<string, TopicScaffoldRow>;
    overallReadiness: ScaffoldCell;
    abstainReason: string;
    unlockRequirements: UnlockHint[];
}

// Structural (duck-typed) shapes of the proto response. The generated proto
// classes satisfy these, and tests can build plain objects against them without
// constructing Message instances. All fields optional so the mappers stay
// tolerant of missing sub-messages (=> honest abstain).
export interface ScoreScaffoldLike {
    abstained?: boolean;
    point?: number;
    lower?: number;
    upper?: number;
    percentile?: number;
    scale?: ScoreScale;
    // int64 arrives as bigint at runtime; unused by the UI but typed for parity.
    lastUpdated?: bigint | number;
}
export interface TopicScaffoldLike {
    topic: string;
    performance?: ScoreScaffoldLike;
    readiness?: ScoreScaffoldLike;
    gapDelta?: number;
}
export interface ScaffoldResponseLike {
    scaffolding?: boolean;
    topics: TopicScaffoldLike[];
    overallReadiness?: ScoreScaffoldLike;
    abstainReason?: string;
    unlockRequirements?: UnlockHint[];
}

// Map one proto ScoreScaffold to a ScaffoldCell. `defaultScale` distinguishes a
// missing Performance cell (UNIT 0..1) from a missing Readiness cell
// (GRE_200_990). Missing => honest abstain, never a fabricated point.
function mapCell(
    cell: ScoreScaffoldLike | undefined,
    defaultScale: ScoreScale,
    gapDelta = 0,
): ScaffoldCell {
    return {
        abstained: cell?.abstained ?? true,
        point: cell?.point ?? 0,
        lower: cell?.lower ?? 0,
        upper: cell?.upper ?? 0,
        percentile: cell?.percentile ?? 0,
        scale: cell?.scale ?? defaultScale,
        gapDelta,
    };
}

// Pure mapping of the whole PerformanceReadinessResponse -> ScaffoldSummary.
// Extracted from the loaders so the boundary is unit-testable without the RPC.
export function mapScaffoldResponse(resp: ScaffoldResponseLike): ScaffoldSummary {
    const rows = new Map<string, TopicScaffoldRow>();
    for (const t of resp.topics ?? []) {
        const gapDelta = t.gapDelta ?? 0;
        rows.set(t.topic, {
            performance: mapCell(t.performance, ScoreScale.UNIT, gapDelta),
            readiness: mapCell(t.readiness, ScoreScale.GRE_200_990, gapDelta),
            gapDelta,
        });
    }
    return {
        rows,
        // Overall Readiness is exam-level (200–990); missing => abstaining band.
        overallReadiness: mapCell(resp.overallReadiness, ScoreScale.GRE_200_990),
        abstainReason: resp.abstainReason ?? "",
        unlockRequirements: (resp.unlockRequirements ?? []).map((u) => ({
            kind: u.kind ?? "",
            have: u.have ?? 0,
            need: u.need ?? 0,
            human: u.human ?? "",
            topic: u.topic ?? "",
        })),
    };
}

// Back-compat loader: per-topic rows only (existing Memory-table caller).
export async function loadScaffoldMap(
    profile: ExamProfile,
): Promise<Map<string, TopicScaffoldRow>> {
    return (await loadScaffoldSummary(profile)).rows;
}

// Full summary loader: rows + overall Readiness + unlock hints (Home caller).
export async function loadScaffoldSummary(
    profile: ExamProfile,
): Promise<ScaffoldSummary> {
    const resp = await loadScaffold(profile);
    return mapScaffoldResponse(resp as unknown as ScaffoldResponseLike);
}

// CALIBRATION of the learner's SELF-RATED accuracy (NOT key-checked). Brier +
// ECE + reliability bins over logged pre-answer confidence on problem attempts.
// Abstains below the engine's attempt threshold — the UI must never fabricate a
// Brier/ECE number.

// One reliability-diagram point (proto ReliabilityBin).
export interface ReliabilityBin {
    confidence: number;
    accuracy: number;
    n: number;
}

// The Home "Calibration" headline. `brier` (lower is better) is the primary
// number; `ece` is the attempt-weighted reliability gap shown as a sub-hint.
// Defaults are honest: abstained=true, zeros, no bins.
export interface CalibrationHeadline {
    abstained: boolean;
    brier: number;
    ece: number;
    attempts: number;
    bins: ReliabilityBin[];
}

// Structural (duck-typed) shape of the proto CalibrationResponse. The generated
// class satisfies this; tests build plain objects against it. All optional so
// the mapper stays tolerant of missing fields (=> honest abstain).
export interface CalibrationResponseLike {
    brier?: number;
    ece?: number;
    attempts?: number;
    abstained?: boolean;
    backendVersion?: string;
    bins?: { confidence?: number; accuracy?: number; n?: number }[];
}

// Pure mapping of CalibrationResponse -> CalibrationHeadline. Missing fields =>
// honest abstain (abstained defaults true, numbers zero, no bins).
export function mapCalibrationResponse(
    resp: CalibrationResponseLike,
): CalibrationHeadline {
    return {
        abstained: resp.abstained ?? true,
        brier: resp.brier ?? 0,
        ece: resp.ece ?? 0,
        attempts: resp.attempts ?? 0,
        bins: (resp.bins ?? []).map((b) => ({
            confidence: b.confidence ?? 0,
            accuracy: b.accuracy ?? 0,
            n: b.n ?? 0,
        })),
    };
}

// Calibration loader (Home caller). Scoped to the profile's weighted leaf topics
// so the number reflects exam-relevant problems; empty topics => all attempts.
export async function loadCalibration(
    profile: ExamProfile,
): Promise<CalibrationHeadline> {
    const leafIds = profile.topics.filter((t) => t.ets_weight > 0).map((t) => t.id);
    const resp = await getCalibration({ topics: leafIds, minAttempts: 0 });
    return mapCalibrationResponse(resp as unknown as CalibrationResponseLike);
}
