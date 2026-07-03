// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pure geometry for the calibration reliability diagram. Type-only imports so
// it unit-tests without the protobuf build.

import type { ReliabilityBin } from "@speedrun/data";

export interface PlottedBin {
    cx: number;
    cy: number;
    r: number;
    overconfident: boolean;
    bin: ReliabilityBin;
}

export interface ChartGeom {
    size: number;
    pad: number;
}

/** Map calibration bins to SVG coordinates. x = stated confidence, y = actual
 * accuracy (SVG y grows downward, so accuracy is flipped). Radius ∝ sqrt(n). */
export function plotBins(
    bins: ReliabilityBin[],
    geom: ChartGeom,
): PlottedBin[] {
    const { size, pad } = geom;
    const span = size - pad * 2;
    const maxN = Math.max(1, ...bins.map((b) => b.n));
    return bins
        .filter((b) => b.n > 0)
        .map((b) => ({
            cx: pad + clamp01(b.confidence) * span,
            cy: pad + (1 - clamp01(b.accuracy)) * span,
            r: 4 + 7 * Math.sqrt(b.n / maxN),
            // Overconfident = stated confidence exceeded actual accuracy.
            overconfident: b.confidence - b.accuracy > 0.05,
            bin: b,
        }));
}

function clamp01(v: number): number {
    return Math.max(0, Math.min(1, v));
}
