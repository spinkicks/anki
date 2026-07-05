# Copyright: Speedrun contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pytest coverage for the spec §7g robustness harness.

The full 20-iteration crash suite is the deliverable and is run via the
standalone harness (``speedrun/eval/crash_offline_test.py``); this test keeps
``pytest`` honest by exercising the SAME code paths in a fast smoke:

  * Part 1 -- a small number of real crash-injection iterations, each asserting
    the reopened collection passes ``fix_integrity`` (the fsck). Set
    ``SPEEDRUN_7G_FULL=1`` to run the full 20 here too.
  * Part 2 -- the three engine scores compute with the AI service DOWN
    (no network dependency), returning without raising.

Both call the harness functions directly, so a regression in the durability or
offline-score paths fails ``pytest`` as well as the standalone run.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Load the harness module from speedrun/eval/ (not on sys.path as a package).
_ANKI_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = _ANKI_ROOT / "speedrun" / "eval" / "crash_offline_test.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("speedrun_crash_offline", _HARNESS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


harness = _load_harness()


def _full() -> bool:
    return os.environ.get("SPEEDRUN_7G_FULL") == "1"


def test_crash_injection_keeps_collection_intact(tmp_path):
    """Hard-kill a mid-review child N times; every reopen must fsck-clean."""
    import random

    n = harness.DEFAULT_CRASHES if _full() else 3
    template = tmp_path / "template.anki2"
    harness.build_template_collection(template)

    rng = random.Random(7)
    ok = 0
    for i in range(1, n + 1):
        res = harness.crash_once(i, template, rng)
        assert res["db_opened"], f"iter {i}: collection failed to reopen: {res}"
        assert res["integrity_ok"], f"iter {i}: integrity check failed: {res}"
        if res["integrity_ok"]:
            ok += 1
    assert ok == n


def test_ai_offline_scores_compute_without_crash_or_network():
    """With the external AI service down, all three engine scores return."""
    result = harness.run_offline_scores()
    assert result["ai_service_running"] is False
    assert result["all_scores_returned"], (
        f"an engine score raised with AI offline: {result.get('errors')}"
    )
    scores = result["scores"]
    assert scores["topic_mastery"]["returned"]
    assert scores["performance_readiness"]["returned"]
    assert scores["calibration"]["returned"]
    # Fresh seed => honest abstain (a valid "computed" outcome; the claim is
    # no-crash / no-network, not that numbers exist yet).
    assert scores["calibration"]["backend_version"], "engine version must round-trip"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
