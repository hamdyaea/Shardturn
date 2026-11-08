"""Exercise the real UI opponent without opening or rendering a Tk window.

The referee keeps the complete game state. The AI receives audited views that
allow public counts and its own cards, but reject reading hidden information.
"""
import collections
import pathlib
import random
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from shardturn import ShardturnApp
from shardturn_engine import COLORS, ShardturnGame, make_deck


class CountOnly:
    def __init__(self, cards):
        self.cards = cards

    def __len__(self):
        return len(self.cards)

    def __iter__(self):
        raise AssertionError("The AI tried to inspect hidden cards")

    def __getitem__(self, _index):
        raise AssertionError("The AI tried to inspect hidden cards")


class AuditedHands:
    def __init__(self, game):
        self.game = game

    def __getitem__(self, player):
        return self.game.hands[1] if player == 1 else CountOnly(self.game.hands[0])

    def __iter__(self):
        raise AssertionError("The AI tried to inspect both hands")


class AuditedChallenge:
    def __init__(self, pending):
        self.pending = pending

    def __getattr__(self, name):
        if name in ("illegal", "evidence"):
            raise AssertionError("The AI tried to read the hidden +4 verdict")
        return getattr(self.pending, name)


class AuditedGame:
    """Actions are referee calls; direct AI reads cannot reveal hidden cards."""
    def __init__(self, game):
        self.referee = game

    def __getattr__(self, name):
        if name == "hands":
            return AuditedHands(self.referee)
        if name == "draw_pile":
            return CountOnly(self.referee.draw_pile)
        if name == "pending_wild4" and self.referee.pending_wild4 is not None:
            return AuditedChallenge(self.referee.pending_wild4)
        if name in ("last_drawn", "rng"):
            raise AssertionError("The AI tried to read private referee information")
        return getattr(self.referee, name)


class HeadlessRoot:
    def __init__(self):
        self.jobs = {}
        self.serial = 0

    def after(self, _delay, callback):
        self.serial += 1
        token = "after-{}".format(self.serial)
        self.jobs[token] = callback
        return token

    def after_cancel(self, token):
        self.jobs.pop(token, None)

    def run(self, token):
        self.jobs.pop(token)()


def headless_app(seed):
    app = ShardturnApp.__new__(ShardturnApp)
    app.root = HeadlessRoot()
    app.rng = random.Random(seed)
    app.game = AuditedGame(ShardturnGame(seed=seed))
    app.ai_job = app.uno_job = None
    app.overlay = app.help_window = app.hover = None
    app.uno_armed = False
    app.status = ""
    app.scores = [0, 0]
    app.scored = False
    app.render = lambda: None
    app.refresh()
    return app


class OpponentIntegrationTests(unittest.TestCase):
    def test_two_hundred_rounds_with_hidden_information_and_full_rules(self):
        expected = collections.Counter(make_deck())
        coverage = collections.Counter()
        for seed in range(200):
            with self.subTest(seed=seed):
                app = headless_app(seed)
                game = app.game.referee
                human_rng = random.Random(seed + 6000)
                for step in range(10000):
                    self.assertEqual(collections.Counter(sum(game.hands, []) +
                                     game.draw_pile + game.discard_pile), expected)
                    if game.phase in ("round_over", "stalled"):
                        if game.winner is not None:
                            self.assertEqual(app.scores[game.winner], game.round_points)
                        break
                    coverage[game.phase] += 1

                    # The human can catch an AI omission even off turn after a
                    # Skip, or before choosing whether to contest an AI +4.
                    if game.uno_vulnerable == 1 and human_rng.random() < .85:
                        game.catch_uno(catcher=0)
                        coverage["human_catches_ai"] += 1
                        app.refresh()

                    # Sometimes a human remembers LAST CARD late; sometimes the
                    # computer's actual scheduled catch action runs first.
                    if game.uno_vulnerable == 0 and human_rng.random() < .35:
                        game.call_uno(0)
                        coverage["late_uno"] += 1
                        app.refresh()
                    if game.current == 1:
                        self.assertIsNotNone(app.ai_job)
                        was_vulnerable = game.uno_vulnerable == 0
                        app.root.run(app.ai_job)
                        if was_vulnerable:
                            coverage["ai_catches_human"] += 1
                        continue
                    if game.uno_vulnerable == 0 and app.uno_job is not None:
                        app.root.run(app.uno_job)
                        coverage["ai_catches_off_turn"] += 1
                    if game.phase == "opening_color":
                        game.choose_opening_color(human_rng.choice(COLORS))
                    elif game.phase == "draw2":
                        game.resolve_draw2()
                    elif game.phase == "wild4":
                        challenge = human_rng.random() < .5
                        game.resolve_wild4(challenge=challenge)
                        if challenge:
                            coverage["challenge_won" if game.last_challenge["success"]
                                     else "challenge_lost"] += 1
                    else:
                        # Include voluntary draws, legal +4 plays, attempted
                        # +4 bluffs, and both keeping/playing drawn cards.
                        moves = game.legal_indices(allow_bluff=True)
                        if moves and human_rng.random() < .9:
                            index = human_rng.choice(moves)
                            card = game.hands[0][index]
                            announce = human_rng.random() > .25
                            game.play(index, human_rng.choice(COLORS)
                                      if card.color is None else None, announce)
                            if card.value == "wild4" and game.pending_wild4.illegal:
                                coverage["human_bluffs"] += 1
                            if announce:
                                coverage["uno_declared"] += 1
                        elif game.phase == "drawn":
                            game.pass_turn()
                        else:
                            game.draw()
                    app.refresh()
                else:
                    self.fail("Round {} failed to terminate".format(seed))
        for event in ("draw2", "wild4", "drawn", "opening_color", "human_bluffs",
                      "challenge_won", "challenge_lost", "late_uno", "uno_declared",
                      "human_catches_ai", "ai_catches_human", "ai_catches_off_turn"):
            self.assertGreater(coverage[event], 0, "Missing scenario: " + event)


if __name__ == "__main__":
    unittest.main()
