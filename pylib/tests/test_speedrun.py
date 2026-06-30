# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

# Import tests.shared first: it imports anki.collection, priming a pre-existing
# import cycle so `from anki.decks import DeckId` works even when this test runs
# in isolation (anki.decks-first triggers anki.cards partial-init otherwise).
from tests.shared import getEmptyCol

from anki.decks import DeckId


def test_coverage_rpc_end_to_end():
    col = getEmptyCol()
    try:
        # Empty collection => nothing covered, but the engine answers with a version.
        resp = col.speedrun.coverage(["calc", "linear_algebra"])
        assert resp.total == 2
        assert resp.covered == 0
        assert resp.percent == 0.0
        assert resp.backend_version  # non-empty proves OUR rslib answered

        # Add a note tagged calc::integration.
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = "integral of 1/x"
        note["Back"] = "ln|x| + C"
        note.tags = ["calc::integration"]
        col.add_note(note, DeckId(1))

        resp = col.speedrun.coverage(["calc", "linear_algebra"])
        assert resp.covered == 1
        assert resp.total == 2
        assert abs(resp.percent - 50.0) < 1e-9

        # No-corruption gate (read-only RPC must not have touched the DB).
        assert col.db.scalar("pragma integrity_check") == "ok"
    finally:
        col.close()
