# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

# Pre-import anki.collection to resolve the circular import that arises when
# anki.decks is the first anki submodule imported in a fresh Python process.
# (anki.decks -> anki.cards -> anki.collection -> ... -> anki.cards.Card fails
# because anki.cards is only partially initialised at that point.)
import anki.collection  # noqa: F401
