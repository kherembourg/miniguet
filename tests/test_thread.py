import json, unittest

import thread
from thread import last_exchange, screen_excerpt
from tests.fakes import FakeHandler, FakeSrv


class ThreadTest(unittest.TestCase):
    def test_last_exchange_pairs_me_then_agent(self):
        m = [(1, "user", "a"), (2, "assistant", "b"), (3, "user", "c"), (4, "assistant", "d")]
        r = last_exchange(m)
        self.assertEqual((r["me"]["text"], r["agent"]["text"]), ("c", "d"))

    def test_agent_before_me_still_shown_when_no_reply_yet(self):
        r = last_exchange([(1, "assistant", "b"), (2, "user", "c")])
        self.assertEqual(r["agent"]["text"], "b")

    def test_last_exchange_truncates(self):
        r = last_exchange([(1, "assistant", "x" * 900)])
        self.assertEqual(len(r["agent"]["text"]), 600)
        self.assertTrue(r["agent"]["truncated"])
        self.assertEqual(len(r["agent"]["full"]), 900)

    def test_empty(self):
        self.assertEqual(last_exchange([]), {"me": None, "agent": None})

    def test_screen_excerpt_strips_frames_and_prompt(self):
        s = screen_excerpt(["Réponse de l'agent", "╭────╮", "│ > tape ici │", "╰────╯", "❯ ", ""])
        self.assertEqual(s, "Réponse de l'agent")

    def test_route_remote_uses_screen(self):
        srv = FakeSrv(screen=["fin de l'écran"])
        thread.register(srv)
        code, _, body = srv.ROUTES["GET"]["/api/thread"](FakeHandler("/api/thread?address=m1/t16"), "")
        d = json.loads(body)
        self.assertIsNone(d["me"])
        self.assertTrue(d["agent"]["screen"])
        self.assertEqual(d["agent"]["text"], "fin de l'écran")

    def test_route_local_uses_transcript(self):
        srv = FakeSrv(pids={"t1": 7}, msgs={7: [(1, "user", "salut"), (2, "assistant", "bonjour")]})
        thread.register(srv)
        d = json.loads(srv.ROUTES["GET"]["/api/thread"](FakeHandler("/api/thread?address=t1"), "")[2])
        self.assertEqual((d["me"]["text"], d["agent"]["text"]), ("salut", "bonjour"))
        self.assertEqual(srv.reads, 0)

    def test_route_unreadable_screen_gives_nulls(self):
        srv = FakeSrv(screen_error=RuntimeError("not_found"))
        thread.register(srv)
        d = json.loads(srv.ROUTES["GET"]["/api/thread"](FakeHandler("/api/thread?address=old-1"), "")[2])
        self.assertEqual(d, {"me": None, "agent": None})


if __name__ == "__main__":
    unittest.main()
