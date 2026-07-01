# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
import json
from pathlib import Path

PROFILE = Path(__file__).resolve().parent.parent / "exam_profiles" / "gre_math.json"


def _load():
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def test_ids_unique():
    ids = [t["id"] for t in _load()["topics"]]
    assert len(ids) == len(set(ids))


def test_leaf_weights_sum_to_one():
    total = sum(t["ets_weight"] for t in _load()["topics"])
    assert abs(total - 1.0) < 1e-3


def test_prereqs_reference_existing_ids():
    topics = _load()["topics"]
    ids = {t["id"] for t in topics}
    for t in topics:
        for p in t["prereqs"]:
            assert p in ids, f"{t['id']} references missing prereq {p}"


def test_prereq_graph_is_acyclic():
    topics = _load()["topics"]
    edges = {t["id"]: list(t["prereqs"]) for t in topics}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in edges}

    def visit(n):
        color[n] = GRAY
        for m in edges[n]:
            if color[m] == GRAY:
                raise AssertionError(f"cycle via {n}->{m}")
            if color[m] == WHITE:
                visit(m)
        color[n] = BLACK

    for tid in edges:
        if color[tid] == WHITE:
            visit(tid)
