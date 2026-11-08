# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Hamdy Abou El Anein
"""Shardturn two-player card-game rules, independent from the graphical interface.

The engine deliberately permits a Wild Draw Four bluff: its legality is only
revealed when the next player challenges it. No AI policy lives in this module.

Developer: Hamdy Abou El Anein
Contact: info@daylightlinux.ch
"""

from dataclasses import dataclass
from random import Random
from typing import List, Optional

COLORS = ("red", "yellow", "green", "blue")
COLOR_NAMES = {"red": "Coral", "yellow": "Amber", "green": "Jade", "blue": "Iris"}
VALUE_NAMES = {"skip": "Pause", "reverse": "Reverse", "draw2": "+2",
               "wild": "Wild", "wild4": "+4"}
PLAYER_NAMES = ("You", "The computer")


@dataclass(frozen=True)
class Card:
    color: Optional[str]
    value: str

    @property
    def label(self):
        name = VALUE_NAMES.get(self.value, self.value)
        return name if self.color is None else "{} {}".format(COLOR_NAMES[self.color], name)

    @property
    def points(self):
        if self.value.isdigit():
            return int(self.value)
        return 50 if self.color is None else 20


@dataclass(frozen=True)
class PendingWild4:
    attacker: int
    defender: int
    illegal: bool
    previous_color: str
    # Hand at the time of the play is the evidence required by the official rule.
    evidence: tuple


def make_deck():
    cards = []
    for color in COLORS:
        cards.append(Card(color, "0"))
        for value in [str(n) for n in range(1, 10)] + ["skip", "reverse", "draw2"]:
            cards.extend([Card(color, value), Card(color, value)])
    cards.extend(Card(None, "wild") for _ in range(4))
    cards.extend(Card(None, "wild4") for _ in range(4))
    return cards


class ShardturnGame:
    """A round. Players 0 (human) and 1 (computer); a match is managed by the UI.

    Public action methods raise ValueError for invalid input. `draw()` draws one
    card and offers it only if playable; otherwise the turn advances at once.
    A playable drawn card can be played or retained using `pass_turn()`.
    """

    def __init__(self, seed=None, dealer=None):
        self.rng = Random(seed)
        self.dealer = self.rng.randrange(2) if dealer is None else dealer
        if self.dealer not in (0, 1):
            raise ValueError("Invalid dealer.")
        self.hands = [[], []]
        self.draw_pile = make_deck()
        self.rng.shuffle(self.draw_pile)
        for _ in range(7):
            self.hands[1 - self.dealer].append(self.draw_pile.pop())
            self.hands[self.dealer].append(self.draw_pile.pop())
        while self.draw_pile[-1].value == "wild4":
            self.rng.shuffle(self.draw_pile)
        self.discard_pile = [self.draw_pile.pop()]
        self.current = 1 - self.dealer
        self.current_color = self.top.color
        self.phase = "play"
        self.drawn_index = None
        self.pending_wild4 = None
        self.pending_draw2 = None
        self.uno_vulnerable = None
        self.winner = None
        self.round_points = 0
        self.messages = []
        self.last_drawn = None
        self.last_challenge = None
        self.empty_draw_turns = 0
        self._log("Seven cards each. Starting card: {}.".format(self.top.label))
        if self.top.value == "wild":
            self.phase = "opening_color"
            self._log("{}: choose the starting color.".format(PLAYER_NAMES[self.current]))
        elif self.top.value == "draw2":
            self._take_cards(self.current, 2)
            self._log("The starting +2 makes the first player draw two cards and skip a turn.")
            self.current = self.dealer
        elif self.top.value in ("skip", "reverse"):
            self.current = self.dealer
            self._log("The starting action card skips the first player's turn.")

    @property
    def top(self):
        return self.discard_pile[-1]

    def _log(self, message):
        self.messages.append(message)

    def _require_turn(self):
        if self.phase not in ("play", "drawn"):
            raise ValueError("This action is not available right now.")

    def _begin_action(self):
        # The missed-LAST CARD window closes when the next player actually acts.
        if self.uno_vulnerable is not None and self.uno_vulnerable != self.current:
            self.uno_vulnerable = None
        self.last_challenge = None

    def _next(self):
        self.current = 1 - self.current
        self.phase = "play"
        self.drawn_index = None

    def _take_cards(self, player, count):
        taken = []
        for _ in range(count):
            if not self.draw_pile and len(self.discard_pile) > 1:
                self.draw_pile = self.discard_pile[:-1]
                self.discard_pile = [self.discard_pile[-1]]
                self.rng.shuffle(self.draw_pile)
                self._log("The discard pile is shuffled to refill the draw pile.")
            if not self.draw_pile:
                break
            card = self.draw_pile.pop()
            self.hands[player].append(card)
            taken.append(card)
        if self.uno_vulnerable == player and len(self.hands[player]) != 1:
            self.uno_vulnerable = None
        return taken

    def choose_opening_color(self, color):
        if self.phase != "opening_color" or color not in COLORS:
            raise ValueError("Choose one of the four colors.")
        self.current_color = color
        self.phase = "play"
        self._log("Starting color: {}.".format(COLOR_NAMES[color]))

    def is_playable(self, index, allow_bluff=True):
        if self.phase not in ("play", "drawn"):
            return False
        if not isinstance(index, int) or isinstance(index, bool):
            return False
        hand = self.hands[self.current]
        if not 0 <= index < len(hand):
            return False
        if self.phase == "drawn" and index != self.drawn_index:
            return False
        card = hand[index]
        if card.value == "wild4":
            return allow_bluff or not any(c.color == self.current_color for c in hand)
        return (card.color is None or card.color == self.current_color
                or card.value == self.top.value)

    def legal_indices(self, allow_bluff=True):
        return [i for i in range(len(self.hands[self.current])) if self.is_playable(i, allow_bluff)]

    def _either_hand_can_play(self):
        # A voluntary empty draw does not prove that its player has no move.
        # Inspect both hands, independently of current turn/drawn-card state.
        return any(card.color is None or card.color == self.current_color
                   or card.value == self.top.value
                   for hand in self.hands for card in hand)

    def play(self, index, color=None, announce_uno=False):
        self._require_turn()
        if not self.is_playable(index):
            raise ValueError("This card cannot be played right now.")
        hand = self.hands[self.current]
        card = hand[index]
        if card.color is None and color not in COLORS:
            raise ValueError("A Wild card needs a chosen color.")
        if card.color is not None and color is not None:
            raise ValueError("Only Wild cards let you choose a color.")
        actor = self.current
        old_color = self.current_color
        illegal = card.value == "wild4" and any(c.color == old_color for c in hand)
        evidence = tuple(c for i, c in enumerate(hand) if i != index)
        self._begin_action()
        hand.pop(index)
        self.discard_pile.append(card)
        self.current_color = card.color if card.color is not None else color
        self.phase = "play"
        self.drawn_index = None
        self.empty_draw_turns = 0
        self._log("{}: {}{}.".format(PLAYER_NAMES[actor], card.label,
                  " → " + COLOR_NAMES[color] if card.color is None else ""))
        if len(hand) == 1:
            self.uno_vulnerable = None if announce_uno else actor
            if announce_uno:
                self._log("{}: LAST CARD!".format(PLAYER_NAMES[actor]))
        elif self.uno_vulnerable == actor:
            self.uno_vulnerable = None
        if card.value == "wild4":
            self.pending_wild4 = PendingWild4(actor, 1 - actor, illegal, old_color, evidence)
            self.current = 1 - actor
            self.phase = "wild4"
            self._log("{} must accept four cards or challenge the +4.".format(PLAYER_NAMES[self.current]))
            return
        if card.value == "draw2":
            # Resolve as a separate next-player action so a missed LAST CARD announcement can be
            # caught before that player starts drawing the forced penalty.
            self.pending_draw2 = actor
            self.current = 1 - actor
            self.phase = "draw2"
            self._log("{} must draw two cards and skip a turn.".format(PLAYER_NAMES[self.current]))
            return
        elif card.value in ("skip", "reverse"):
            self._log("With two players, {} skips the opponent's turn.".format(card.label))
        else:
            self._next()
        if not hand:
            self._finish_round(actor)

    def draw(self):
        if self.phase != "play":
            raise ValueError("You cannot draw right now.")
        self._begin_action()
        actor = self.current
        taken = self._take_cards(actor, 1)
        if not taken:
            self.empty_draw_turns += 1
            self._log("{}: empty draw pile, turn passed.".format(PLAYER_NAMES[actor]))
            self._next()
            if self.empty_draw_turns >= 2 and not self._either_hand_can_play():
                self.phase = "stalled"
                self._log("No card can be played. The round is a draw.")
            return None
        self.empty_draw_turns = 0
        self.last_drawn = (actor, taken[0])
        self.drawn_index = len(self.hands[actor]) - 1
        self.phase = "drawn"
        self._log("{}: one card drawn.".format(PLAYER_NAMES[actor]))
        if not self.is_playable(self.drawn_index):
            self._next()
        return taken[0]

    def pass_turn(self):
        if self.phase != "drawn":
            raise ValueError("Draw a card before passing.")
        self._begin_action()
        self._log("{}: drawn card kept, turn passed.".format(PLAYER_NAMES[self.current]))
        self._next()

    def resolve_wild4(self, challenge=False):
        if self.phase != "wild4" or self.pending_wild4 is None:
            raise ValueError("There is no +4 penalty to resolve.")
        pending = self.pending_wild4
        self._begin_action()
        self.pending_wild4 = None
        self.phase = "play"
        if challenge and pending.illegal:
            self._take_cards(pending.attacker, 4)
            self.current = pending.defender
            self.last_challenge = {"success": True, "evidence": pending.evidence,
                                   "color": pending.previous_color, "attacker": pending.attacker}
            self._log("Challenge won! The +4 was illegal: its player draws four cards.")
        else:
            count = 6 if challenge else 4
            self._take_cards(pending.defender, count)
            self.current = pending.attacker
            if challenge:
                self.last_challenge = {"success": False, "evidence": pending.evidence,
                                       "color": pending.previous_color, "attacker": pending.attacker}
                self._log("Challenge lost: draw six cards and skip your turn.")
            else:
                self._log("+4 accepted: draw four cards and skip your turn.")
        if not self.hands[pending.attacker]:
            self._finish_round(pending.attacker)

    def resolve_draw2(self):
        if self.phase != "draw2" or self.pending_draw2 is None:
            raise ValueError("There is no +2 penalty to resolve.")
        attacker = self.pending_draw2
        defender = 1 - attacker
        self._begin_action()
        self._take_cards(defender, 2)
        self.pending_draw2 = None
        self.current = attacker
        self.phase = "play"
        self.drawn_index = None
        self._log("{}: two cards drawn, turn skipped.".format(PLAYER_NAMES[defender]))
        if not self.hands[attacker]:
            self._finish_round(attacker)

    def call_uno(self, player=0):
        if player not in (0, 1) or len(self.hands[player]) != 1:
            raise ValueError("Announce LAST CARD when you have one card left.")
        if self.uno_vulnerable != player:
            raise ValueError("LAST CARD is already announced or the catch window has closed.")
        self.uno_vulnerable = None
        self._log("{}: LAST CARD!".format(PLAYER_NAMES[player]))

    def catch_uno(self, catcher=None):
        catcher = self.current if catcher is None else catcher
        if (catcher not in (0, 1) or self.uno_vulnerable is None
                or self.uno_vulnerable == catcher or self.phase in ("round_over", "stalled")):
            raise ValueError("There is no missed LAST CARD announcement to catch.")
        offender = self.uno_vulnerable
        self.uno_vulnerable = None
        self._take_cards(offender, 2)
        self._log("{}: missed LAST CARD, two penalty cards drawn.".format(PLAYER_NAMES[offender]))

    def _finish_round(self, winner):
        self.winner = winner
        self.round_points = sum(c.points for c in self.hands[1 - winner])
        self.phase = "round_over"
        self.drawn_index = None
        self.uno_vulnerable = None
        self._log("{}: round won, {} points scored.".format(PLAYER_NAMES[winner], self.round_points))
