// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
import { getCoverage, getExamProfile, getPerformanceReadiness, getTopicMastery } from "@generated/backend";

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

// Future columns (scaffolding; always abstains today).
export async function loadScaffold(profile: ExamProfile) {
    const leafIds = profile.topics.filter((t) => t.ets_weight > 0).map((t) => t.id);
    return await getPerformanceReadiness({ topics: leafIds });
}

export interface ScaffoldCell {
    abstained: boolean;
}
export interface TopicScaffoldRow {
    performance: ScaffoldCell;
    readiness: ScaffoldCell;
}

export async function loadScaffoldMap(
    profile: ExamProfile,
): Promise<Map<string, TopicScaffoldRow>> {
    const resp = await loadScaffold(profile);
    const map = new Map<string, TopicScaffoldRow>();
    for (const t of resp.topics) {
        map.set(t.topic, {
            performance: { abstained: t.performance?.abstained ?? true },
            readiness: { abstained: t.readiness?.abstained ?? true },
        });
    }
    return map;
}
