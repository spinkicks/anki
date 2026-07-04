# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Pure, Qt-free decision logic for the Speedrun Home "START RUN" button.

Kept separate from the Qt dialog (``speedrun.py``) so it can be unit-tested with
a real ``Collection`` and no ``QApplication``.

The whole point of this module is the scheduler API choice. Due counts MUST come
from ``col.sched.deck_due_tree`` (which calls the backend with ``now=int_time``
so counts are computed for *today*), NOT ``col.decks.deck_tree`` (which passes
``now=0`` — the backend then returns a purely *structural* tree whose
new/review/learn counts are all ZERO). Reading counts off the structural tree
made START RUN always report "all caught up", so it never launched study. This
module is the single place that decision is made, and the regression tests in
``qt/tests/test_speedrun.py`` pin the correct behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.decks import DeckId

# ---- Installer seed-deck auto-import -----------------------------------------
#
# The desktop installer ships this .apkg inside the packaged app resources so a
# grader who installs the MSI has the GRE-Math deck ALREADY loaded on first
# launch (zero manual import). The first-run hook in main.py — placed next to
# the existing Speedrun Home auto-open (post-sync, inside the `not safeMode`
# guard) — resolves the bundled apkg and imports it exactly once. The functions
# below hold the Qt-free decision + import logic so they can be unit-tested with
# a real Collection and no QApplication (see qt/tests/test_speedrun.py).

# Basename of the bundled seed .apkg. The build copies it into the aqt data
# folder (out/qt/_aqt/data in dev; _aqt/data inside the packaged wheel/MSI), so
# aqt_data_path() locates it in BOTH environments. See build/configure/src/aqt.rs.
SEED_APKG_NAME = "gre_math_seed.apkg"

# The exam deck the seed apkg creates. Single source of truth for the deck name
# used by the idempotency check (mirrors SpeedrunHome.EXAM_DECK in speedrun.py).
EXAM_DECK_NAME = "Speedrun::GRE Math"


def _aqt_data_dir() -> Path | None:
    """Return the packaged aqt data dir (``_aqt/data``), or None if unavailable.

    Isolated (and free of Qt) so tests can monkeypatch it. In a packaged
    install this is the app resources dir; in dev it is ``out/qt/_aqt/data``.
    """
    try:
        from aqt.utils import aqt_data_path

        return aqt_data_path()
    except Exception:
        # aqt_data_path can warn+return Path(".") under bare unit tests; any
        # failure here just means "no packaged dir" -> fall back to dev paths.
        return None


def _dev_repo_seed_paths() -> list[Path]:
    """Candidate in-repo dev paths for the seed apkg (``speedrun/out/…``).

    Only used as a fallback when the packaged resource is absent (running from a
    source checkout that hasn't copied the apkg into the data folder yet).
    Isolated so tests can monkeypatch it.
    """
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    # Walk up from qt/aqt/ looking for a repo root that contains speedrun/out.
    for parent in here.parents:
        candidate = parent / "speedrun" / "out" / SEED_APKG_NAME
        candidates.append(candidate)
    return candidates


def speedrun_seed_apkg_path() -> str | None:
    """Resolve the bundled seed .apkg, packaged path first then dev fallback.

    Returns an existing file path, or None if the apkg is nowhere to be found
    (in which case the first-run hook simply no-ops — never a crash).
    """
    data_dir = _aqt_data_dir()
    if data_dir is not None:
        packaged = data_dir / SEED_APKG_NAME
        if packaged.is_file():
            return str(packaged)
    for dev in _dev_repo_seed_paths():
        if dev.is_file():
            return str(dev)
    return None


def maybe_import_seed_deck(
    col: Collection, exam_deck_name: str, apkg_path: str | None
) -> bool:
    """Idempotently import the bundled seed deck. Returns True iff it imported.

    Guards, in order:
    * ``apkg_path`` falsy or not an existing file -> no-op (bundle missing).
    * the exam deck already exists -> SKIP (idempotent; never re-import/dup).
    * otherwise import the apkg; any import error is swallowed so a bad/corrupt
      bundle can NEVER crash the launch sequence.

    safeMode / config gating live at the CALL SITE (main.py), mirroring the
    Speedrun Home auto-open hook — this function stays a pure col operation.
    """
    if not apkg_path or not os.path.isfile(apkg_path):
        return False
    # Idempotency: if the exam deck is already present, the deck was imported on
    # a previous launch (or the user made it) — do nothing.
    if col.decks.id_for_name(exam_deck_name) is not None:
        return False
    try:
        from anki.collection import (
            ImportAnkiPackageOptions,
            ImportAnkiPackageRequest,
        )

        # Import the notes/cards/decks as-is. The seed is built with genanki (no
        # scheduling info), so with_scheduling stays False; merge_notetypes False
        # keeps the seed's blessed notetypes intact.
        request = ImportAnkiPackageRequest(
            package_path=apkg_path,
            options=ImportAnkiPackageOptions(
                merge_notetypes=False,
                with_scheduling=False,
                with_deck_configs=False,
            ),
        )
        col.import_anki_package(request)
    except Exception:
        # A failed import must NOT crash first launch. Report "did not import".
        return False
    # Confirm the deck actually landed before claiming success.
    return col.decks.id_for_name(exam_deck_name) is not None


# A mini-mock must draw at least one problem, and a filtered-deck search term
# with limit=0 pulls zero cards -> Anki raises FilteredDeckError
# (SearchReturnedNoCards) and the launch crashes. Clamp the config-driven size
# to a sane [floor, cap] window so a bad/absent config value can never take the
# search-term limit out of range. The cap is a generous upper bound (a single
# timed mini-mock is a short pass, not the whole bank).
MINI_MOCK_SIZE_FLOOR = 1
MINI_MOCK_SIZE_CAP = 500


def clamp_mini_mock_size(size: int) -> int:
    """Clamp a config-driven mini-mock size into ``[floor, cap]``.

    Guards the ``limit=0`` (and negative/absurd) crash: see the constants above.
    """
    return max(MINI_MOCK_SIZE_FLOOR, min(int(size), MINI_MOCK_SIZE_CAP))


class MiniMockDecision(NamedTuple):
    # "importNeeded":     Problems subdeck absent, or present but holding zero
    #                     problem cards at all (bank not imported) -> prompt import.
    # "noActiveProblems": subdeck present AND has problem cards, but every one is
    #                     suspended (0 active) -> the mock search
    #                     `deck:"…Problems" -is:suspended` returns nothing. Honest:
    #                     tell the user to UNSUSPEND, not to import.
    # "ready":            the subdeck has at least one non-suspended problem card
    #                     -> build the filtered deck and launch the reviewer.
    status: Literal["importNeeded", "noActiveProblems", "ready"]
    # Resolved Problems subdeck id; only set for "ready" (else None).
    deck_id: DeckId | None = None


class StartRunDecision(NamedTuple):
    # "importNeeded": exam deck absent      -> prompt the user to import it
    # "caughtUp":     deck present, 0 due   -> honest banner (+ Custom Study)
    # "ready":        cards due             -> launch the reviewer on `deck_id`
    status: Literal["importNeeded", "caughtUp", "ready"]
    # New cards remaining today; only meaningful for "caughtUp" (else 0).
    new_left: int = 0
    # Resolved exam deck id; only set for "ready" (else None).
    deck_id: DeckId | None = None


def decide_start_run(col: Collection, exam_deck_name: str) -> StartRunDecision:
    """Decide, honestly, what START RUN should do for ``exam_deck_name``.

    Counts come from the scheduler's due tree so they reflect what is actually
    due right now (see the module docstring for why this matters).
    """
    deck_id = col.decks.id_for_name(exam_deck_name)
    if deck_id is None:
        return StartRunDecision("importNeeded")
    node = col.sched.deck_due_tree(deck_id)
    if node is None:
        return StartRunDecision("caughtUp")
    due = node.new_count + node.review_count + node.learn_count
    if due == 0:
        return StartRunDecision("caughtUp", new_left=node.new_count)
    return StartRunDecision("ready", deck_id=deck_id)


def decide_mini_mock(col: Collection, problems_deck_name: str) -> MiniMockDecision:
    """Decide, honestly, whether a timed mini-mock can launch.

    A mini-mock draws problems from the ``problems_deck_name`` subdeck. Three
    outcomes, kept distinct because they call for DIFFERENT user action:

    * ``importNeeded`` — the subdeck doesn't exist yet, or exists but holds zero
      problem cards at all: the bank hasn't been imported. Prompt import.
    * ``noActiveProblems`` — the subdeck DOES hold problem cards, but every one
      is suspended, so the mock search ``deck:"…Problems" -is:suspended`` returns
      nothing. Telling this user to "import" is dishonest — they need to
      UNSUSPEND. Reported separately so the caller can say so.
    * ``ready`` — at least one non-suspended problem card exists; build + launch.

    Unlike START RUN, we don't gate on scheduler due counts here: a mock is a
    fresh timed pass over the whole problem bank, so mere presence of a
    non-suspended problem card is enough.
    """
    deck_id = col.decks.id_for_name(problems_deck_name)
    if deck_id is None:
        return MiniMockDecision("importNeeded")
    # find_cards over the subdeck excluding suspended cards; zero active ->
    # nothing to mock. Quote the deck name because it contains "::" and spaces.
    if not col.find_cards(f'deck:"{problems_deck_name}" -is:suspended'):
        # Distinguish "no cards imported" from "all cards suspended": the former
        # is an import problem, the latter an unsuspend problem. Include-suspended
        # search over the same subdeck tells them apart.
        if col.find_cards(f'deck:"{problems_deck_name}"'):
            return MiniMockDecision("noActiveProblems")
        return MiniMockDecision("importNeeded")
    return MiniMockDecision("ready", deck_id=deck_id)


def build_mini_mock_deck(col: Collection, problems_deck_name: str, size: int) -> DeckId:
    """Build/refresh the "Speedrun Mini-Mock" filtered deck and return its id.

    The filtered deck pulls up to ``size`` random, non-suspended cards from the
    Problems subdeck. This uses Anki's normal, undo-safe filtered-deck build op.

    CRITICAL: ``config.reschedule`` MUST be True. The engine's Performance score
    and the Readiness give-up ``mini_mock_count`` only count revlog entries where
    ``has_rating_and_affects_scheduling()`` is true, i.e.
    ``has_rating() && !is_cramming()``. A filtered deck with ``reschedule=false``
    is preview/cram mode -> ``is_cramming()`` is true -> its reviews are EXCLUDED
    from those scores. Setting ``reschedule=True`` makes mock attempts actually
    feed Performance and the give-up counter (per-answer wall-clock still lands
    in ``revlog.taken_millis`` either way).
    """
    from anki.decks import DeckId, FilteredDeckConfig

    # Clamp defensively: a limit=0 (or negative) search term pulls zero cards and
    # makes Anki raise FilteredDeckError, crashing the launch. Clamp here too (not
    # only at the config read site) so this helper is safe for any caller.
    size = clamp_mini_mock_size(size)

    name = "Speedrun Mini-Mock"
    # Resolve an EXISTING mini-mock filtered deck by name and UPDATE it in place;
    # only create (deck_id=0) when none exists. Always passing DeckId(0) made Anki
    # create a fresh filtered deck each launch, auto-suffixing the name ("+", "++",
    # …) and orphaning prior decks (stranding their cards).
    existing = col.decks.id_for_name(name)
    deck = col.sched.get_or_create_filtered_deck(
        deck_id=existing if existing is not None else DeckId(0)
    )
    deck.name = name
    config = deck.config
    config.reschedule = True  # see docstring: mock attempts must score
    del config.search_terms[:]
    config.search_terms.append(
        FilteredDeckConfig.SearchTerm(
            search=f'deck:"{problems_deck_name}" -is:suspended',
            limit=size,
            order=FilteredDeckConfig.SearchTerm.Order.RANDOM,
        )
    )
    out = col.sched.add_or_update_filtered_deck(deck)
    # add_or_update_filtered_deck returns OpChangesWithId; .id is the new deck id.
    did = DeckId(out.id)
    if not did:  # defensive: resolve by name if the op didn't carry an id
        did = col.decks.id_for_name(deck.name) or did
    return did
