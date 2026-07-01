# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from anki.decks import DeckId
from tests.shared import getEmptyCol


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


def test_topic_mastery_abstains_and_is_read_only():
    col = getEmptyCol()
    try:
        # A note tagged calc::limits, never reviewed => no memory state.
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = "definition of a limit"
        note["Back"] = "epsilon-delta"
        note.tags = ["calc::limits"]
        col.add_note(note, DeckId(1))

        resp = col.speedrun.topic_mastery(["calc::limits", "linear_algebra::eigen"])
        assert len(resp.topics) == 2
        limits = resp.topics[0]
        assert limits.topic == "calc::limits"
        assert limits.cards_with_data == 0
        assert limits.graded_reviews == 0
        assert limits.abstained is True
        assert (limits.mastered_lower, limits.mastered_upper) == (0.0, 1.0)
        assert resp.backend_version  # proves OUR rslib answered

        # Read-only RPC must not have touched the DB.
        assert col.db.scalar("pragma integrity_check") == "ok"
    finally:
        col.close()


def test_exam_profile_round_trips_via_config():
    col = getEmptyCol()
    try:
        assert col.speedrun.exam_profile("gre_math").profile_json == ""
        col.speedrun.set_exam_profile('{"exam_id":"gre_math","topics":[]}')
        resp = col.speedrun.exam_profile("gre_math")
        assert resp.exam_id == "gre_math"
        assert '"exam_id":"gre_math"' in resp.profile_json
        assert col.db.scalar("pragma integrity_check") == "ok"
    finally:
        col.close()
