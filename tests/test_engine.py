"""Behavioral regression tests for the classic two-player rules."""
import collections
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from shardturn_engine import Card, ShardturnGame, make_deck


def setup_round(human, computer, top=Card("red", "5"), stock=None):
    game = ShardturnGame(seed=42, dealer=1)
    game.hands = [list(human), list(computer)]
    game.discard_pile = [top]
    game.current_color = top.color or "red"
    game.current = 0
    game.phase = "play"
    game.drawn_index = None
    game.pending_wild4 = None
    game.pending_draw2 = None
    game.uno_vulnerable = None
    game.winner = None
    game.round_points = 0
    game.messages = []
    game.draw_pile = list(stock if stock is not None else [Card("blue", "9")] * 30)
    return game


class RulesTests(unittest.TestCase):
    def test_classic_pack_and_conservation(self):
        deck = make_deck()
        self.assertEqual(len(deck), 108)
        counts = collections.Counter(deck)
        self.assertEqual(counts[Card("red", "0")], 1)
        self.assertEqual(counts[Card("blue", "draw2")], 2)
        self.assertEqual(counts[Card(None, "wild4")], 4)
        for seed in range(50):
            game = ShardturnGame(seed=seed)
            self.assertEqual(len(game.hands[game.dealer]), 7)
            self.assertEqual(collections.Counter(game.hands[0] + game.hands[1] + game.draw_pile + game.discard_pile), counts)
            self.assertNotEqual(game.top.value, "wild4")

    def test_two_player_skip_reverse_and_draw2_replay(self):
        for value in ("skip", "reverse", "draw2"):
            with self.subTest(value=value):
                game = setup_round([Card("red", value), Card("blue", "3")], [Card("green", "8")])
                game.play(0, announce_uno=True)
                if value == "draw2":
                    self.assertEqual(game.current, 1)
                    self.assertEqual(game.phase, "draw2")
                    self.assertEqual(len(game.hands[1]), 1)
                    game.resolve_draw2()
                self.assertEqual(game.current, 0)
                self.assertEqual(len(game.hands[1]), 3 if value == "draw2" else 1)

    def test_first_discard_applies_special_effects(self):
        observed = set()
        for seed in range(300):
            game = ShardturnGame(seed=seed, dealer=1)
            value = game.top.value
            observed.add(value)
            if value == "wild":
                self.assertEqual(game.phase, "opening_color")
                self.assertEqual(game.current, 0)
                game.choose_opening_color("yellow")
                self.assertEqual(game.phase, "play")
                self.assertEqual(game.current_color, "yellow")
            elif value == "draw2":
                self.assertEqual(game.current, 1)
                self.assertEqual(len(game.hands[0]), 9)
            elif value in ("skip", "reverse"):
                self.assertEqual(game.current, 1)
            else:
                self.assertEqual(game.current, 0)
        self.assertTrue({"wild", "draw2", "skip", "reverse"}.issubset(observed))

    def test_no_stacking_and_no_play_other_card_after_draw(self):
        game = setup_round([Card("red", "2"), Card("green", "5")], [Card("blue", "2")], stock=[Card("red", "9")])
        game.draw()
        self.assertEqual(game.phase, "drawn")
        self.assertEqual(game.legal_indices(), [2])
        before = list(game.hands[0])
        with self.assertRaises(ValueError):
            game.play(0)
        self.assertEqual(game.hands[0], before)
        game.pass_turn()
        self.assertEqual(game.current, 1)

    def test_draw_nonplayable_passes_and_playable_can_be_kept(self):
        game = setup_round([Card("red", "2")], [Card("green", "7")], stock=[Card("blue", "9")])
        game.draw()
        self.assertEqual(game.current, 1)
        self.assertEqual(game.phase, "play")

    def test_wild_requires_color_without_mutation(self):
        game = setup_round([Card(None, "wild"), Card("blue", "4")], [Card("green", "7")])
        before = (list(game.hands[0]), list(game.discard_pile), game.current)
        with self.assertRaises(ValueError):
            game.play(0)
        self.assertEqual((game.hands[0], game.discard_pile, game.current), before)
        game.play(0, "green", True)
        self.assertEqual(game.current_color, "green")
        self.assertEqual(game.current, 1)

    def test_successful_wild4_challenge(self):
        game = setup_round([Card(None, "wild4"), Card("red", "7")], [Card("blue", "6")])
        self.assertNotIn(0, game.legal_indices(allow_bluff=False))
        game.play(0, "green", True)
        self.assertEqual(game.phase, "wild4")
        game.resolve_wild4(challenge=True)
        self.assertEqual(game.current, 1)
        self.assertEqual(len(game.hands[0]), 5)
        self.assertEqual(len(game.hands[1]), 1)
        self.assertTrue(game.last_challenge["success"])

    def test_matching_value_and_wild_do_not_make_wild4_illegal(self):
        for other in (Card("blue", "5"), Card(None, "wild")):
            game = setup_round([Card(None, "wild4"), other], [Card("green", "3")])
            self.assertIn(0, game.legal_indices(False))
            game.play(0, "blue", True)
            game.resolve_wild4(challenge=True)
            self.assertEqual(len(game.hands[1]), 7)
            self.assertEqual(game.current, 0)
            self.assertFalse(game.last_challenge["success"])

    def test_wild4_accepted_skips_opponent(self):
        game = setup_round([Card(None, "wild4"), Card("red", "7")], [Card("blue", "3")])
        game.play(0, "blue", True)
        game.resolve_wild4()
        self.assertEqual(len(game.hands[1]), 5)
        self.assertEqual(game.current, 0)

    def test_finish_with_draw2_scores_penalty_cards(self):
        game = setup_round([Card("red", "draw2")], [Card("green", "3")], stock=[Card(None, "wild"), Card("blue", "4")])
        game.play(0)
        self.assertIsNone(game.winner)
        self.assertEqual(game.phase, "draw2")
        self.assertEqual(len(game.hands[1]), 1)
        game.resolve_draw2()
        self.assertEqual(game.phase, "round_over")
        self.assertEqual(game.round_points, 57)

    def test_finish_with_wild4_waits_for_resolution(self):
        game = setup_round([Card(None, "wild4")], [Card("green", "3")])
        game.play(0, "blue")
        self.assertIsNone(game.winner)
        self.assertEqual(game.phase, "wild4")
        game.resolve_wild4()
        self.assertEqual(game.winner, 0)
        self.assertEqual(game.round_points, 39)

    def test_uno_can_be_caught_or_declared_before_next_action(self):
        game = setup_round([Card("red", "2"), Card("green", "7")], [Card("red", "3"), Card("blue", "8")])
        game.play(0)
        self.assertEqual(game.uno_vulnerable, 0)
        game.catch_uno(1)
        self.assertEqual(len(game.hands[0]), 3)
        game = setup_round([Card("red", "2"), Card("green", "7")], [Card("red", "3"), Card("blue", "8")])
        game.play(0)
        game.call_uno(0)
        with self.assertRaises(ValueError):
            game.catch_uno(1)

    def test_uno_window_closes_when_next_player_acts(self):
        game = setup_round([Card("red", "2"), Card("green", "7")], [Card("red", "3"), Card("blue", "8")])
        game.play(0)
        game.play(0, announce_uno=True)
        with self.assertRaises(ValueError):
            game.catch_uno(1)

    def test_uno_window_on_wild4_closes_at_penalty_decision(self):
        game = setup_round([Card(None, "wild4"), Card("green", "7")], [Card("red", "3")])
        game.play(0, "blue")
        self.assertEqual(game.uno_vulnerable, 0)
        game.resolve_wild4()
        self.assertIsNone(game.uno_vulnerable)

    def test_draw2_cannot_be_stacked(self):
        game = setup_round([Card("red", "draw2"), Card("green", "1")], [Card("red", "draw2")])
        game.play(0, announce_uno=True)
        self.assertEqual(game.phase, "draw2")
        self.assertEqual(game.current, 1)
        self.assertEqual(game.legal_indices(), [])
        before = list(game.hands[1])
        with self.assertRaises(ValueError):
            game.play(0)
        self.assertEqual(game.hands[1], before)
        game.resolve_draw2()
        self.assertEqual(game.current, 0)
        self.assertEqual(len(game.hands[1]), 3)

    def test_uno_can_be_caught_before_draw2_penalty_begins(self):
        game = setup_round([Card("red", "draw2"), Card("green", "1")], [Card("blue", "3")])
        game.play(0)
        self.assertEqual(game.uno_vulnerable, 0)
        game.catch_uno(catcher=1)
        self.assertEqual(len(game.hands[0]), 3)
        self.assertEqual(game.phase, "draw2")
        game.resolve_draw2()
        self.assertEqual(len(game.hands[1]), 3)
        self.assertEqual(game.current, 0)

    def test_draw2_resolution_closes_uno_catch_window(self):
        game = setup_round([Card("red", "draw2"), Card("green", "1")], [Card("blue", "3")])
        game.play(0)
        game.resolve_draw2()
        self.assertIsNone(game.uno_vulnerable)
        with self.assertRaises(ValueError):
            game.catch_uno(catcher=1)

    def test_recycle_keeps_top_and_all_cards(self):
        game = setup_round([Card("blue", "2")], [Card("green", "8")], stock=[])
        game.discard_pile = [Card("yellow", "1"), Card("red", "5")]
        game.draw()
        self.assertEqual(game.top, Card("red", "5"))
        self.assertIn(Card("yellow", "1"), game.hands[0])
        self.assertEqual(len(game.discard_pile), 1)

    def test_repeated_voluntary_empty_draws_do_not_hide_opponent_move(self):
        game = setup_round([Card("red", "2")], [Card("blue", "8")], stock=[])
        game.draw()  # Player 0 voluntarily declines a playable red card.
        game.draw()  # Player 1 cannot move.
        game.draw()  # Player 0 voluntarily declines it again.
        self.assertEqual(game.phase, "play")
        self.assertEqual(game.current, 1)
        game.draw()
        game.play(0)
        self.assertEqual(game.winner, 0)

    def test_both_hands_unplayable_and_empty_stock_is_a_stalemate(self):
        game = setup_round([Card("green", "2")], [Card("blue", "8")], stock=[])
        game.draw()
        self.assertEqual(game.phase, "play")
        game.draw()
        self.assertEqual(game.phase, "stalled")
        self.assertIsNone(game.winner)
        self.assertEqual(game.round_points, 0)

    def test_seeded_rounds_conserve_pack_and_terminate(self):
        expected = collections.Counter(make_deck())
        for seed in range(60):
            game = ShardturnGame(seed=seed)
            for turn in range(4000):
                self.assertEqual(collections.Counter(sum(game.hands, []) + game.draw_pile + game.discard_pile), expected)
                if game.phase in ("round_over", "stalled"):
                    break
                if game.phase == "opening_color":
                    game.choose_opening_color("red")
                elif game.phase == "wild4":
                    game.resolve_wild4(challenge=(seed % 2 == 0))
                elif game.phase == "draw2":
                    game.resolve_draw2()
                else:
                    moves = game.legal_indices(False)
                    if moves:
                        i = moves[0]
                        card = game.hands[game.current][i]
                        game.play(i, "blue" if card.color is None else None, True)
                    elif game.phase == "drawn":
                        game.pass_turn()
                    else:
                        game.draw()
            else:
                self.fail("Round {} did not finish".format(seed))


if __name__ == "__main__":
    unittest.main()
