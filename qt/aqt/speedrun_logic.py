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

from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.decks import DeckId


class MiniMockDecision(NamedTuple):
    # "importNeeded": Problems subdeck absent, or present but every problem card
    #                 is suspended (nothing to mock) -> prompt import.
    # "ready":        the subdeck has at least one non-suspended problem card ->
    #                 build the filtered deck and launch the reviewer.
    status: Literal["importNeeded", "ready"]
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

    A mini-mock draws problems from the ``problems_deck_name`` subdeck. If that
    subdeck doesn't exist yet (bank not imported) or holds zero *non-suspended*
    cards, there's nothing to mock, so we report ``importNeeded`` and the caller
    surfaces the same honest banner used by START RUN. Otherwise ``ready``.

    Unlike START RUN, we don't gate on scheduler due counts here: a mock is a
    fresh timed pass over the whole problem bank, so mere presence of a
    non-suspended problem card is enough.
    """
    deck_id = col.decks.id_for_name(problems_deck_name)
    if deck_id is None:
        return MiniMockDecision("importNeeded")
    # find_cards over the subdeck excluding suspended cards; zero -> nothing to
    # mock. Quote the deck name because it contains "::" and spaces.
    if not col.find_cards(f'deck:"{problems_deck_name}" -is:suspended'):
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
