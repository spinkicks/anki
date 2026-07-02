# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Python integration test for the read-time due-card interleave (Phase 1).

Drives the real scheduler: makes review-due cards across two topics, opts into the
feature via the synced `speedrun:review_interleave` config (Full), builds the queue
through `get_queued_cards`, and asserts the interleave property (no two adjacent
same-topic). This is the "+1 Python integration" acceptance for the engine change
(the pure ordering + wrapper are covered by rslib unit tests).
"""

from __future__ import annotations

from anki.consts import CARD_TYPE_REV
from anki.consts import QUEUE_TYPE_REV
from tests.shared import getEmptyCol


def _add_review_due_card(col, front: str, tag: str, today: int) -> None:
    nt = col.models.current()
    note = col.new_note(nt)
    note.fields[0] = front
    col.add_note(note, col.decks.get_current_id())
    note.tags = [tag]
    col.update_note(note)
    card = note.cards()[0]
    card.type = CARD_TYPE_REV
    card.queue = QUEUE_TYPE_REV
    card.due = today  # due today => gathered as a review
    card.ivl = 1
    col.update_card(card)


def _topic_of(col, card_id: int) -> str:
    tags = col.get_card(card_id).note().tags
    return "calc" if "calc" in tags else "linear_algebra"


def test_review_interleave_full_no_two_adjacent_same_topic():
    col = getEmptyCol()
    try:
        today = col.sched.today
        # 3 calc + 2 linear_algebra, added grouped (calc first).
        for front, tag in [
            ("c1", "calc"),
            ("c2", "calc"),
            ("c3", "calc"),
            ("la1", "linear_algebra"),
            ("la2", "linear_algebra"),
        ]:
            _add_review_due_card(col, front, tag, today)

        # Opt into Full weakness×weight interleave via the synced config.
        col.set_config(
            "speedrun:review_interleave",
            {"mode": 0, "weights": [["calc", 0.9], ["linear_algebra", 0.1]]},
        )

        queued = col.sched.get_queued_cards(fetch_limit=10)
        order = [_topic_of(col, qc.card.id) for qc in queued.cards]
        assert len(order) == 5, f"expected all 5 reviews queued, got {order}"

        # Interleave property: 3+2 round-robins to c,la,c,la,c => zero adjacencies.
        adjacent_same = sum(1 for i in range(1, len(order)) if order[i] == order[i - 1])
        assert adjacent_same == 0, f"expected topic interleave, got {order}"
    finally:
        col.close()


def test_review_interleave_absent_config_is_noop():
    # Without the config key the queue build must be untouched Anki behavior
    # (feature off by default). We only assert the build succeeds and returns the
    # cards — the ordering is Anki's default (not our interleave).
    col = getEmptyCol()
    try:
        today = col.sched.today
        for front, tag in [("c1", "calc"), ("c2", "calc"), ("la1", "linear_algebra")]:
            _add_review_due_card(col, front, tag, today)
        queued = col.sched.get_queued_cards(fetch_limit=10)
        assert len(queued.cards) == 3
    finally:
        col.close()
