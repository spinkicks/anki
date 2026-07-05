# Copyright: Speedrun contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Spec §7g robustness harness: crash x20 durability + AI-offline scores.

One reproducible harness, two parts, one command.

Part 1 -- crash x20 (durability / zero corruption)
--------------------------------------------------
Simulate an abrupt crash mid-review 20 times and prove the collection stays
intact each time. Each iteration:

  1. copies a freshly-seeded template collection (the real GRE-Math seed apkg,
     imported once WITH scheduling into a template, then copied per iteration
     so the run is fast and deterministic-enough to reproduce);
  2. spawns a SUBPROCESS (this same file, ``--child``) that opens the copy and
     answers cards in a tight loop -- real ``col.sched.answerCard`` calls, which
     go through the Rust ``Collection::transact`` path (a genuine DB write, so a
     write may be in flight);
  3. hard-kills the child mid-review (``Popen.kill()`` -> ``TerminateProcess`` on
     Windows, ``SIGKILL`` on POSIX) after a short *seeded-random* delay, so a
     write is plausibly in flight when the process dies;
  4. reopens the collection in the parent and runs the integrity check
     (``col.fix_integrity()`` == the backend fsck / ``check_database``), asserting
     it reports no problems and that the DB opens cleanly.

This tests SQLite durability under abrupt termination (WAL / rollback journal),
which is the real robustness claim. Timing-based kills are inherently a bit
stochastic; the ``--seed`` flag pins the RNG so a given run reproduces, and 20
iterations across a randomized delay window make an in-flight write plausible.

Part 2 -- AI-offline degrades cleanly while scores still compute
----------------------------------------------------------------
With the external AI/RAG service DOWN (its default state -- nothing is started
on its port here), assert the three ENGINE scores still compute without a crash,
a hang, or any network dependency. We call the exact backend RPCs the desktop
dashboard uses -- ``get_topic_mastery`` / ``get_performance_readiness`` /
``get_calibration`` on ``col._backend`` (the mediasrv dashboard posts to these
same raw RPCs; see ``qt/aqt/mediasrv.py`` ``exposed_backend_list``). They must
return (abstain or real numbers) with no exception. This proves the AI service
is truly external: the scores are engine-only.

Run (Windows), from ``repos/anki``::

    ANKI_TEST_MODE=1 PYTHONPATH="pylib;out/pylib;out/qt;out/qt/tools" \
        out/pyenv/Scripts/python.exe speedrun/eval/crash_offline_test.py

Exits non-zero on ANY integrity failure or if the offline scores raise. Writes
an aggregate ``speedrun/eval/crash-offline-results.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from anki.collection import (
    Collection,
    ImportAnkiPackageOptions,
    ImportAnkiPackageRequest,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EXAM_DECK = "Speedrun::GRE Math"
# Topics present in the seed deck (used for the offline score calls). Any topic
# is fine -- fresh seed abstains honestly; the point is the call returns.
SEED_TOPICS = ["calc::single_var::integration", "linear_algebra::matrices"]

DEFAULT_CRASHES = 20
# Randomized kill-delay window (seconds). Wide enough that the kill lands while
# the child is still churning through answer_card transacts on the ~99-card deck.
KILL_DELAY_MIN = 0.02
KILL_DELAY_MAX = 0.35

_THIS_FILE = Path(__file__).resolve()
# repos/anki  (speedrun/eval/crash_offline_test.py -> up 2 dirs)
_ANKI_ROOT = _THIS_FILE.parents[2]


def _seed_apkg_path() -> Path:
    """Locate the shipped GRE-Math seed apkg (built env reuse -- no rebuild)."""
    p = _ANKI_ROOT / "speedrun" / "out" / "gre_math_seed.apkg"
    if not p.exists():
        raise SystemExit(f"seed apkg not found at {p}")
    return p


# ---------------------------------------------------------------------------
# Template collection: import the seed once, WITH scheduling, then bump the
# per-day new-card limit and select the exam deck so cards are actually
# answerable. Copies of this file are what each crash iteration operates on.
# ---------------------------------------------------------------------------


def build_template_collection(dest: Path) -> None:
    """Create a ready-to-review .anki2 at *dest* from the seed apkg."""
    if dest.exists():
        dest.unlink()
    col = Collection(str(dest))
    try:
        req = ImportAnkiPackageRequest(
            package_path=str(_seed_apkg_path()),
            options=ImportAnkiPackageOptions(
                with_scheduling=True,
                merge_notetypes=False,
                update_notes=0,
                update_notetypes=0,
            ),
        )
        col.import_anki_package(req)

        did = col.decks.id_for_name(EXAM_DECK)
        if did is None:
            raise SystemExit(f"exam deck {EXAM_DECK!r} missing after seed import")
        col.decks.set_current(did)
        # Fresh import defaults to 20 new/day; lift it so the child has a long
        # queue to churn through (keeps a write plausibly in flight at kill time).
        conf = col.decks.config_dict_for_deck_id(did)
        conf["new"]["perDay"] = 9999
        conf["rev"]["perDay"] = 9999
        col.decks.update_config(conf)
    finally:
        col.close()


# ---------------------------------------------------------------------------
# Child worker: answer cards forever (real transacts). Killed mid-loop.
# ---------------------------------------------------------------------------


def run_child(col_path: str) -> int:
    """Open *col_path* and answer cards in a loop until killed.

    Every ``answerCard`` is a real scheduler mutation that goes through the Rust
    ``Collection::transact`` path -> an actual DB write. We never close cleanly;
    the parent hard-kills us. If the deck is ever exhausted we re-select the deck
    and keep going so there is always a write to interrupt.
    """
    col = Collection(col_path)
    did = col.decks.id_for_name(EXAM_DECK)
    if did is not None:
        col.decks.set_current(did)
    # Signal readiness so the parent starts its kill timer only once we are
    # genuinely answering (stdout is line-buffered via flush).
    sys.stdout.write("READY\n")
    sys.stdout.flush()

    while True:
        card = col.sched.getCard()
        if card is None:
            # Queue drained; reset current deck and loop (keeps writes flowing).
            if did is not None:
                col.decks.set_current(did)
            card = col.sched.getCard()
            if card is None:
                # Truly nothing left to answer: spin cheaply so we can still be
                # killed "mid-review" of the session (rare on a 99-card deck).
                time.sleep(0.001)
                continue
        # ease 3 == Good. Real transact write.
        col.sched.answerCard(card, 3)


# ---------------------------------------------------------------------------
# Part 1 -- crash x20
# ---------------------------------------------------------------------------


def _spawn_child(col_path: str) -> subprocess.Popen:
    env = dict(os.environ)
    env["ANKI_TEST_MODE"] = "1"
    # Inherit the ninja PYTHONPATH the parent was launched with.
    return subprocess.Popen(
        [sys.executable, str(_THIS_FILE), "--child", "--col", col_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _wait_ready(proc: subprocess.Popen, timeout: float = 30.0) -> bool:
    """Block until the child prints READY (it is now answering)."""
    assert proc.stdout is not None
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            return proc.poll() is None  # pipe closed; only ok if still alive
        if line.strip() == b"READY":
            return True
    return False


def crash_once(iteration: int, template: Path, rng: random.Random) -> dict:
    """Run one crash iteration; return a result dict."""
    tmpdir = tempfile.mkdtemp(prefix=f"speedrun7g_{iteration:02d}_")
    col_path = os.path.join(tmpdir, "collection.anki2")
    shutil.copy(str(template), col_path)

    result: dict = {"iteration": iteration}
    proc = _spawn_child(col_path)
    try:
        ready = _wait_ready(proc)
        result["child_ready"] = ready
        # Let the child answer for a seeded-random slice of time so the kill
        # lands while a transact write is plausibly in flight, then hard-kill.
        delay = rng.uniform(KILL_DELAY_MIN, KILL_DELAY_MAX)
        result["kill_delay_s"] = round(delay, 4)
        time.sleep(delay)

        killed_alive = proc.poll() is None
        result["killed_while_running"] = killed_alive
        proc.kill()  # TerminateProcess (Windows) / SIGKILL (POSIX)
        proc.wait(timeout=15)
        # Negative return code == died from a signal (POSIX). On Windows kill()
        # sets exit code 1. Either way it did NOT close the collection cleanly.
        result["child_returncode"] = proc.returncode
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=15)

    # --- Reopen in the parent and run the integrity check (the fsck). ---
    integrity_ok = False
    problems = ""
    open_ok = False
    try:
        col = Collection(col_path)
        open_ok = True
        try:
            problems, integrity_ok = col.fix_integrity()
        finally:
            col.close()
    except Exception as exc:  # noqa: BLE001 -- report, never mask
        problems = f"reopen/fsck raised: {exc!r}"

    result["db_opened"] = open_ok
    result["integrity_ok"] = bool(integrity_ok and open_ok)
    # fix_integrity always appends a "rebuilt" line; only surface it on failure.
    if not result["integrity_ok"]:
        result["problems"] = problems

    shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def run_crash_suite(n: int, seed: int) -> dict:
    rng = random.Random(seed)
    template_dir = tempfile.mkdtemp(prefix="speedrun7g_template_")
    template = Path(template_dir) / "template.anki2"
    print(f"[part1] building seeded template collection at {template} ...")
    build_template_collection(template)

    iterations: list[dict] = []
    ok_count = 0
    hit_while_running = 0
    for i in range(1, n + 1):
        res = crash_once(i, template, rng)
        iterations.append(res)
        if res["integrity_ok"]:
            ok_count += 1
        if res.get("killed_while_running"):
            hit_while_running += 1
        status = "OK" if res["integrity_ok"] else "CORRUPT/FAIL"
        print(
            f"[part1] crash {i:2d}/{n}: "
            f"delay={res.get('kill_delay_s')}s "
            f"child_rc={res.get('child_returncode')} "
            f"opened={res.get('db_opened')} integrity={status}"
        )

    shutil.rmtree(template_dir, ignore_errors=True)
    return {
        "n_crashes": n,
        "integrity_ok_count": ok_count,
        "killed_while_running_count": hit_while_running,
        "seed": seed,
        "all_ok": ok_count == n,
        "iterations": iterations,
    }


# ---------------------------------------------------------------------------
# Part 2 -- AI-offline scores
# ---------------------------------------------------------------------------


def run_offline_scores() -> dict:
    """Call the three engine scores with the AI service DOWN; assert no crash.

    Uses a fresh seed import (no network, no AI process). Each RPC must return;
    a fresh seed abstains honestly (no graded reviews yet), which is a valid
    "computed" outcome -- the claim is *no crash / no hang / no network dep*.
    """
    tmpdir = tempfile.mkdtemp(prefix="speedrun7g_offline_")
    col_path = os.path.join(tmpdir, "collection.anki2")
    result: dict = {"ai_service_running": False}
    col = Collection(col_path)
    try:
        req = ImportAnkiPackageRequest(
            package_path=str(_seed_apkg_path()),
            options=ImportAnkiPackageOptions(
                with_scheduling=True,
                merge_notetypes=False,
                update_notes=0,
                update_notetypes=0,
            ),
        )
        col.import_anki_package(req)

        scores: dict = {}
        errors: dict = {}

        # 1) Topic mastery (FSRS memory aggregate).
        try:
            tm = col._backend.get_topic_mastery(
                topics=SEED_TOPICS, mastery_threshold=0.9, min_reviews=20
            )
            scores["topic_mastery"] = {
                "returned": True,
                "n_topics": len(tm.topics),
                "abstained": [t.abstained for t in tm.topics],
            }
        except Exception as exc:  # noqa: BLE001
            errors["topic_mastery"] = repr(exc)

        # 2) Performance + Readiness.
        try:
            pr = col._backend.get_performance_readiness(topics=SEED_TOPICS)
            scores["performance_readiness"] = {
                "returned": True,
                "overall_abstained": pr.overall_readiness.abstained,
                "abstain_reason": pr.abstain_reason,
            }
        except Exception as exc:  # noqa: BLE001
            errors["performance_readiness"] = repr(exc)

        # 3) Calibration (self-rated confidence).
        try:
            cal = col._backend.get_calibration(topics=[], min_attempts=20)
            scores["calibration"] = {
                "returned": True,
                "abstained": cal.abstained,
                "attempts": cal.attempts,
                "backend_version": bool(cal.backend_version),
            }
        except Exception as exc:  # noqa: BLE001
            errors["calibration"] = repr(exc)

        result["scores"] = scores
        result["errors"] = errors
        result["all_scores_returned"] = len(errors) == 0 and len(scores) == 3
        # Which of the three abstained (fresh seed => all should, honestly).
        result["abstained"] = {
            "topic_mastery": scores.get("topic_mastery", {}).get("abstained"),
            "performance_readiness": scores.get("performance_readiness", {}).get(
                "overall_abstained"
            ),
            "calibration": scores.get("calibration", {}).get("abstained"),
        }
    finally:
        col.close()
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Spec 7g crash + AI-offline harness")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--col", help=argparse.SUPPRESS)
    ap.add_argument(
        "--crashes",
        type=int,
        default=DEFAULT_CRASHES,
        help="number of crash iterations (default 20)",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=7,
        help="RNG seed for the (inherently stochastic) kill delays; pin to reproduce",
    )
    ap.add_argument(
        "--out",
        default=str(_THIS_FILE.parent / "crash-offline-results.json"),
        help="aggregate results JSON path",
    )
    args = ap.parse_args()

    if args.child:
        if not args.col:
            print("--child requires --col", file=sys.stderr)
            return 2
        return run_child(args.col)

    print("=" * 70)
    print("Speedrun spec 7g robustness harness")
    print(
        "  Part 1: crash x{}  (SQLite durability under abrupt kill)".format(
            args.crashes
        )
    )
    print("  Part 2: AI-offline engine scores (external-AI proof)")
    print("=" * 70)

    part1 = run_crash_suite(args.crashes, args.seed)

    print("-" * 70)
    print("[part2] calling engine scores with AI service DOWN ...")
    part2 = run_offline_scores()
    for name, info in part2.get("scores", {}).items():
        print(f"[part2] {name}: returned={info.get('returned')} {info}")
    for name, err in part2.get("errors", {}).items():
        print(f"[part2] {name}: ERROR {err}")

    aggregate = {
        "spec": "7g",
        "n_crashes": part1["n_crashes"],
        "integrity_ok_count": part1["integrity_ok_count"],
        "killed_while_running_count": part1["killed_while_running_count"],
        "crash_seed": part1["seed"],
        "crash_all_ok": part1["all_ok"],
        "offline_scores_ok": part2["all_scores_returned"],
        "offline_abstained": part2["abstained"],
        "detail": {"part1_iterations": part1["iterations"], "part2": part2},
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")

    print("=" * 70)
    print("SUMMARY")
    print(f"  Part 1  crashes         : {part1['n_crashes']}")
    print(
        f"  Part 1  integrity ok    : "
        f"{part1['integrity_ok_count']}/{part1['n_crashes']}"
    )
    print(
        f"  Part 1  killed running  : "
        f"{part1['killed_while_running_count']}/{part1['n_crashes']} "
        f"(kill landed while child was answering)"
    )
    print(
        f"  Part 2  offline scores  : {'PASS' if part2['all_scores_returned'] else 'FAIL'}"
    )
    print(f"  results JSON            : {out_path}")
    print("=" * 70)

    crash_pass = part1["all_ok"]
    offline_pass = part2["all_scores_returned"]
    if crash_pass and offline_pass:
        print("RESULT: PASS")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
