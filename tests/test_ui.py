"""Integration tests with real Tk widgets; run under a graphical display."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shardturn_engine import Card, ShardturnGame
from shardturn import Painter, ShardturnApp


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform in ("win32", "darwin"),
                     "A graphical display is needed for the Tk integration tests")
class InterfaceTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.app = ShardturnApp(self.root, seed=41)
        self.app.cancel_ai()
        self.root.update()

    def tearDown(self):
        self.app.cancel_ai()
        if self.app.resize_job is not None:
            self.root.after_cancel(self.app.resize_job)
        self.root.destroy()

    def arrange(self, human, ai, current=0):
        self.app.cancel_ai()
        game = ShardturnGame(seed=2, dealer=1)
        game.hands = [list(human), list(ai)]
        game.discard_pile = [Card("red", "5")]
        game.draw_pile = [Card("green", "8")] * 35
        game.current_color = "red"
        game.current = current
        game.phase = "play"
        game.pending_draw2 = None
        game.pending_wild4 = None
        game.drawn_index = None
        game.uno_vulnerable = None
        game.winner = None
        game.messages = []
        self.app.game = game
        self.app.overlay = None
        self.app.uno_armed = False
        self.app.scored = False
        self.app.render()
        return game

    def test_click_places_a_human_card(self):
        g = self.arrange([Card("red", "3"), Card("blue", "7")], [Card("green", "2")])
        region = next(r for r in self.app.regions if r[4] == "card" and r[5] == 0)
        x = (region[0]+region[2])/2*self.app.scale+self.app.ox
        y = (region[1]+region[3])/2*self.app.scale+self.app.oy
        self.app.canvas.event_generate("<Button-1>", x=round(x), y=round(y))
        self.root.update()
        self.assertEqual(g.top, Card("red", "3"))
        self.assertEqual(len(g.hands[0]), 1)

    def test_computer_cards_never_reach_face_renderer(self):
        secret = Card("blue", "7")
        self.arrange([Card("red", "3")], [secret] * 14)
        rendered = []
        original = Painter.card
        def record(painter, *args, **kwargs):
            rendered.append(kwargs)
            return original(painter, *args, **kwargs)
        with patch.object(Painter, "card", record):
            self.app.render()
        self.assertFalse(any(r.get("card") is secret for r in rendered))
        self.assertEqual(sum(r.get("back", False) for r in rendered), 14)  # 13 backs + stock

    def test_wild_color_choice_and_cancel_do_not_lose_card(self):
        g = self.arrange([Card(None, "wild"), Card("blue", "7")], [Card("green", "2")])
        self.app.dispatch("card", 0)
        self.assertEqual(len(g.hands[0]), 2)
        self.assertEqual(self.app.overlay, ("color", 0))
        self.app.dispatch("cancel_overlay")
        self.assertEqual(len(g.hands[0]), 2)
        self.app.dispatch("uno")
        self.app.dispatch("card", 0)
        self.app.dispatch("color", "blue")
        self.assertEqual(g.current_color, "blue")
        self.assertIsNone(g.uno_vulnerable)
        self.assertIsNone(self.app.overlay)

    def test_drawn_card_restriction_and_pass(self):
        g = self.arrange([Card("red", "3"), Card("blue", "7")], [Card("green", "2")])
        g.draw_pile.append(Card("red", "9"))
        self.app.dispatch("draw")
        self.assertEqual(g.phase, "drawn")
        self.app.dispatch("card", 0)
        self.assertEqual(g.top, Card("red", "5"))
        self.app.dispatch("pass")
        self.assertEqual(len(g.hands[0]), 3)
        self.assertEqual(g.current, 1)

    def test_catch_ai_uno_during_ai_replay(self):
        g = self.arrange([Card("green", "9")], [Card("red", "skip"), Card("blue", "7")], current=1)
        g.play(0)
        self.app.refresh()
        self.assertEqual(g.current, 1)
        self.assertTrue(any(r[4] == "catch" for r in self.app.regions))
        self.app.dispatch("catch")
        self.assertEqual(len(g.hands[1]), 3)
        self.assertEqual(g.current, 1)

    def test_ai_catches_human_uno_while_human_replays(self):
        g = self.arrange([Card("red", "skip"), Card("blue", "7")], [Card("green", "9")])
        self.app.dispatch("card", 0)
        self.assertEqual(g.current, 0)
        self.assertIsNotNone(self.app.uno_job)
        self.app.cancel_ai()
        self.app.ai_catch_uno()
        self.assertEqual(len(g.hands[0]), 3)
        self.assertIsNone(g.uno_vulnerable)

    def test_late_uno_keyboard_works_on_pending_wild4(self):
        g = self.arrange([Card(None, "wild4"), Card("blue", "7")], [Card("green", "9")])
        self.app.dispatch("card", 0)
        self.app.dispatch("color", "blue")
        self.assertEqual(g.uno_vulnerable, 0)
        self.app.on_key(SimpleNamespace(keysym="l"))
        self.assertIsNone(g.uno_vulnerable)

    def test_catch_ai_before_accepting_wild4(self):
        g = self.arrange([Card("green", "9")], [Card(None, "wild4"), Card("blue", "7")], current=1)
        g.play(0, color="blue")
        self.app.refresh()
        self.assertTrue(any(r[4] == "catch" for r in self.app.regions))
        self.app.dispatch("catch")
        self.assertEqual(len(g.hands[1]), 3)
        self.app.dispatch("accept4")
        self.assertEqual(len(g.hands[0]), 5)

    def test_wild4_challenge_is_adjudicated_without_revealing_hand(self):
        secret = Card("red", "7")
        g = self.arrange([Card("blue", "6")], [Card(None, "wild4"), secret], current=1)
        g.play(0, color="green", announce_uno=True)
        self.app.refresh()
        self.app.dispatch("challenge4")
        self.assertEqual(len(g.hands[1]), 5)
        self.assertEqual(g.current, 0)
        visible = " ".join(str(self.app.canvas.itemcget(i, "text"))
                           for i in self.app.canvas.find_all() if self.app.canvas.type(i) == "text")
        self.assertNotIn(secret.label, visible)
        self.assertIn("Challenge won", visible)

    def test_draw2_waits_for_acknowledgement_then_returns_to_ai(self):
        g = self.arrange([Card("green", "9")], [Card("red", "draw2"), Card("blue", "7")], current=1)
        g.play(0, announce_uno=True)
        self.app.refresh()
        self.assertEqual(len(g.hands[0]), 1)
        self.app.dispatch("draw")
        self.assertEqual(len(g.hands[0]), 3)
        self.assertEqual(g.current, 1)

    def test_empty_draw_does_not_report_a_previous_human_card(self):
        previous_draw = Card("blue", "1")
        g = self.arrange([Card("red", "3"), previous_draw], [Card("green", "9")])
        g.last_drawn = (0, previous_draw)
        g.draw_pile = []
        # Only the visible top discard remains, so recycling cannot supply a
        # card. A playable human card keeps this from being a terminal state.
        before = list(g.hands[0])
        self.app.dispatch("draw")
        self.assertEqual(g.hands[0], before)
        self.assertEqual(g.current, 1)
        self.assertEqual(g.phase, "play")
        self.assertIn("empty", self.app.status.lower())
        self.assertNotIn(previous_draw.label, self.app.status)

    def test_final_draw2_scores_only_once_after_ai_draws(self):
        g = self.arrange([Card("red", "draw2")], [Card("blue", "7")])
        self.app.scores = [0, 0]
        self.app.dispatch("card", 0)
        self.assertEqual(self.app.scores, [0, 0])
        self.app.cancel_ai()
        self.app.ai_step()
        self.assertEqual(g.phase, "round_over")
        self.assertEqual(self.app.scores, [23, 0])
        self.app.refresh()
        self.assertEqual(self.app.scores, [23, 0])

    def test_page_keyboard_selects_visible_card(self):
        g = self.arrange([Card("green", "9")] * 10 + [Card("red", "3")], [Card("blue", "8")])
        self.app.change_page(1)
        self.app.on_key(SimpleNamespace(keysym="1"))
        self.assertEqual(g.top, Card("red", "3"))
        self.assertEqual(len(g.hands[0]), 10)


if __name__ == "__main__":
    unittest.main()
