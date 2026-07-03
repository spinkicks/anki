// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Speedrun "The Map" — RPC loader. Pure layout/graph logic lives in ./layout.

import { loadProfile, loadRows } from "@speedrun/data";

import { layoutNodes, type MapView } from "./graph";

export async function loadMap(examId = "gre_math"): Promise<MapView | null> {
    const profile = await loadProfile(examId);
    if (!profile) return null;
    const rows = await loadRows(profile);
    return layoutNodes(rows, profile);
}
