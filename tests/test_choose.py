import json, os, re, unittest

import choose
from choose import check_choice, menu_hash, parse_menu
from tests.fakes import FakeHandler, FakeSrv

SCREENS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo", "screens")


def load(name):
    with open(os.path.join(SCREENS, name)) as f:
        return f.read().splitlines()


def with_command(lines, cmd, width=190):
    """Replace the command of the Bash screen by `cmd`, cut in lines like the terminal does."""
    i = lines.index(" ls /tmp")
    return lines[:i] + [" " + cmd[k:k + width] for k in range(0, len(cmd), width)] + lines[i + 1:]


def yes_no_permission():
    """The write menu without its middle option: a plain Yes / No permission menu."""
    out = []
    for ln in load("perm-write.txt"):
        if re.match(r"^\s*2\.\s", ln):
            continue
        out.append(re.sub(r"^(\s*)3\.", r"\g<1>2.", ln))
    return out


class ParseTest(unittest.TestCase):
    def test_parses_bash_menu(self):
        p = parse_menu(load("perm-bash.txt"), "permission")
        self.assertEqual(p["kind"], "permission")
        self.assertEqual(p["tool"], "Bash command")
        self.assertIn("ls /tmp", p["detail"])
        self.assertEqual([o["role"] for o in p["options"]][0], "approve")
        self.assertEqual(p["options"][-1]["role"], "deny")
        self.assertTrue(all(o["key"].isdigit() for o in p["options"]))

    def test_parses_three_options_with_always(self):
        roles = [o["role"] for o in parse_menu(load("perm-write.txt"), "permission")["options"]]
        self.assertEqual(roles, ["approve", "always", "deny"])

    def test_yes_no_permission_menu_is_approve_deny(self):
        p = parse_menu(yes_no_permission(), "permission")
        self.assertEqual([o["role"] for o in p["options"]], ["approve", "deny"])

    def test_parses_three_option_choice_menu(self):
        p = parse_menu(load("question-3.txt"), "question")
        self.assertEqual(p["kind"], "question")
        self.assertEqual([o["role"] for o in p["options"]], ["choice"] * 3)
        self.assertEqual([o["label"] for o in p["options"]], ["Red", "Green", "Blue"])   # as displayed
        self.assertEqual(p["question"], "Which color do you pick: red, green, or blue?")

    def test_question_yes_no_menu_gives_choices_not_roles(self):
        p = parse_menu(load("question-yesno.txt"), "question")
        self.assertEqual([(o["label"], o["role"]) for o in p["options"]], [("Yes", "choice"), ("No", "choice")])

    def test_free_text_option_is_not_a_button(self):
        p = parse_menu(load("question-3.txt"), "question")
        self.assertTrue(p["free_text"])
        self.assertFalse([o for o in p["options"] if "Type something" in o["label"] or "Chat about" in o["label"]])
        lines = [ln.replace("Type something.", "Autre") for ln in load("question-3.txt")]
        q = parse_menu(lines, "question")
        self.assertTrue(q["free_text"])
        self.assertEqual(len(q["options"]), 3)

    def test_multi_select_menu_is_unsupported(self):
        p = parse_menu(load("question-multi.txt"), "question")
        self.assertEqual(p["options"], [])
        self.assertEqual(p["kind"], "question")

    def test_plain_screen_has_no_menu(self):
        self.assertIsNone(parse_menu(load("plain.txt"), "permission"))

    def test_unrecognised_menu(self):
        lines = ["Quelques options :", "  1. une", "  2. deux", "  3. trois"]
        self.assertIsNone(parse_menu(lines, "question"))

    def test_incomplete_request_is_unrecognised(self):
        lines = load("perm-bash.txt")
        top = next(i for i, ln in enumerate(lines) if ln.startswith("─" * 20))
        p = parse_menu(lines[top + 1:], "permission")      # the frame's top edge scrolled out of the lines read
        self.assertEqual(p["options"], [])
        self.assertTrue(parse_menu(load("perm-bash.txt"), "permission")["options"])   # complete capture: buttons

    def test_long_detail_is_truncated_for_display_only(self):
        cmd = "echo " + "x" * 895
        p = parse_menu(with_command(load("perm-bash.txt"), cmd), "permission")
        self.assertLessEqual(len(p["detail"]), 400)
        self.assertTrue(p["truncated"])
        self.assertIn(cmd, p["full"].replace("\n", ""))

    def test_hash_changes_after_400_chars(self):
        a = with_command(load("perm-bash.txt"), "echo " + "x" * 400 + " A")
        b = with_command(load("perm-bash.txt"), "echo " + "x" * 400 + " B")
        self.assertNotEqual(menu_hash(parse_menu(a, "permission")), menu_hash(parse_menu(b, "permission")))

    def test_hash_ignores_footer_change(self):
        a = load("perm-bash.txt")
        b = a + ["  ✻ 12s · esc to interrupt"]
        self.assertEqual(menu_hash(parse_menu(a, "permission")), menu_hash(parse_menu(b, "permission")))

    def test_hash_ignores_rotating_tip(self):
        a = load("perm-bash.txt")
        b = [ln.replace("Tip: auto mode handles these prompts for you — choose \"switch to auto mode\" below",
                        "Tip: shift+tab cycles the permission mode") for ln in a]
        self.assertNotEqual(a, b)
        self.assertEqual(menu_hash(parse_menu(a, "permission")), menu_hash(parse_menu(b, "permission")))

    def test_check_refuses_unknown_key(self):
        lines = load("perm-bash.txt")
        opt, err = check_choice("blocked", "permission", lines, "9", menu_hash(parse_menu(lines, "permission")))
        self.assertIsNone(opt)
        self.assertIn("option", err)

    def test_check_refuses_changed_hash(self):
        lines = load("perm-bash.txt")
        opt, err = check_choice("blocked", "permission", lines, "1", "deadbeef")
        self.assertIsNone(opt)
        self.assertIn("a changé", err)

    def test_check_refuses_not_blocked(self):
        lines = load("perm-bash.txt")
        self.assertIsNone(check_choice("done", None, lines, "1", menu_hash(parse_menu(lines, "permission")))[0])

    def test_check_refuses_unsupported_menu(self):
        lines = load("question-multi.txt")
        opt, err = check_choice("blocked", "question", lines, "1", menu_hash(parse_menu(lines, "question")))
        self.assertIsNone(opt)
        self.assertTrue(err)

    def test_check_accepts(self):
        lines = load("perm-bash.txt")
        opt, err = check_choice("blocked", "permission", lines, "1", menu_hash(parse_menu(lines, "permission")))
        self.assertIsNone(err)
        self.assertEqual(opt["role"], "approve")

    def test_check_accepts_question_yes_no_as_choice(self):
        lines = load("question-yesno.txt")
        opt, err = check_choice("blocked", "question", lines, "2", menu_hash(parse_menu(lines, "question")))
        self.assertIsNone(err)
        self.assertEqual((opt["label"], opt["role"]), ("No", "choice"))


NOW = 5000   # status_ms of the blocked session in the fake snapshot


class RouteTest(unittest.TestCase):
    def setUp(self):
        choose.CHOSEN.clear()

    def srv(self, screen="perm-bash.txt", kind="permission", state="blocked", status_ms=NOW, screens=None):
        term = {"address": "t3", "state": "live", "status": {"state": state, "kind": kind}, "status_ms": status_ms,
                "labels": {"where": "outils / 1"}}
        srv = FakeSrv(screen=screens or load(screen), terms=[term])
        choose.register(srv)
        return srv

    def request(self, screen="perm-bash.txt", kind="permission", key="1", **over):
        d = {"address": "t3", "key": key, "menu_hash": menu_hash(parse_menu(load(screen), kind)), "since_ms": NOW}
        return dict(d, **over)

    def post(self, srv, d, paired=True):
        return json.loads(srv.ROUTES["POST"]["/api/choose"](FakeHandler("/api/choose", paired), json.dumps(d))[2])

    def test_annotate_adds_menu(self):
        srv = self.srv()
        a = [{"address": "t3", "status": "blocked", "kind": "permission", "since_ms": NOW}]
        choose.annotate(srv, [], a)
        self.assertEqual(a[0]["menu"]["options"][0]["role"], "approve")
        self.assertEqual(a[0]["menu"]["menu_hash"], menu_hash(parse_menu(load("perm-bash.txt"), "permission")))

    def test_annotate_registers_the_hook(self):
        srv = self.srv()
        a = [{"address": "t3", "status": "blocked", "kind": "permission", "since_ms": NOW}]
        for fn in srv.SNAPSHOT_HOOKS:
            fn([], a)
        self.assertIn("menu", a[0])

    def test_annotate_choice_menu(self):
        srv = self.srv("question-3.txt", "question")
        a = [{"address": "t3", "status": "blocked", "kind": "question", "since_ms": NOW}]
        choose.annotate(srv, [], a)
        self.assertEqual([o["role"] for o in a[0]["menu"]["options"]], ["choice"] * 3)

    def test_annotate_unrecognised_menu(self):
        srv = self.srv("plain.txt")
        a = [{"address": "t3", "status": "blocked", "kind": "permission", "since_ms": NOW}]
        choose.annotate(srv, [], a)
        self.assertEqual(a[0]["menu"], {"kind": "permission", "options": [], "menu_hash": None})

    def test_annotate_unreadable_screen(self):
        srv = self.srv()
        srv.screen_error = RuntimeError("boom")
        a = [{"address": "t3", "status": "blocked", "kind": "permission", "since_ms": NOW}]
        choose.annotate(srv, [], a)
        self.assertEqual(a[0]["menu"]["options"], [])

    def test_annotate_leaves_other_sessions_alone(self):
        srv = self.srv()
        a = [{"address": "t3", "status": "blocked", "kind": "auth"}, {"address": "t4", "status": "done", "kind": None}]
        choose.annotate(srv, [], a)
        self.assertNotIn("menu", a[0])
        self.assertNotIn("menu", a[1])
        self.assertEqual(srv.reads, 0)

    def test_choose_requires_pairing(self):
        srv = self.srv()
        r = self.post(srv, self.request(), paired=False)
        self.assertIn("non appairé", r["error"])
        self.assertEqual(srv.keys_sent, [])

    def test_choose_sends_the_key(self):
        srv = self.srv()
        r = self.post(srv, self.request())
        self.assertEqual(r, {"ok": True, "label": "Yes"})
        self.assertEqual(srv.keys_sent, [("t3", "1")])

    def test_choose_refuses_changed_menu(self):
        srv = self.srv()
        r = self.post(srv, self.request(menu_hash="x"))
        self.assertIn("a changé", r["error"])
        self.assertEqual(srv.keys_sent, [])

    def test_choose_refuses_stale_generation(self):
        srv = self.srv(status_ms=NOW + 1)   # same menu, but the session moved on since the card was drawn
        r = self.post(srv, self.request())
        self.assertIn("avancé", r["error"])
        self.assertEqual((srv.keys_sent, srv.reads), ([], 0))

    def test_choose_refuses_missing_since_ms(self):
        srv = self.srv()
        d = self.request()
        del d["since_ms"]
        self.assertIn("avancé", self.post(srv, d)["error"])
        self.assertEqual(srv.keys_sent, [])

    def test_choose_rereads_screen_before_keys(self):
        other = with_command(load("perm-bash.txt"), "rm -rf /tmp/x")   # the request changed after the card was drawn
        srv = self.srv(screens=other)
        r = self.post(srv, self.request())
        self.assertIn("a changé", r["error"])
        self.assertEqual((srv.keys_sent, srv.reads), ([], 1))

    def test_choose_refuses_unknown_session(self):
        srv = self.srv()
        r = self.post(srv, self.request(address="t99"))
        self.assertIn("inconnue", r["error"])
        self.assertEqual(srv.keys_sent, [])

    def test_choose_refuses_not_blocked(self):
        srv = self.srv(state="done", kind=None)
        self.assertTrue(self.post(srv, self.request())["error"])
        self.assertEqual(srv.keys_sent, [])

    def test_choose_question_menu(self):
        srv = self.srv("question-3.txt", "question")
        r = self.post(srv, self.request("question-3.txt", "question", key="2"))
        self.assertEqual(r, {"ok": True, "label": "Green"})
        self.assertEqual(srv.keys_sent, [("t3", "2")])

    def test_choose_twice_sends_once(self):
        srv = self.srv()
        d = self.request()
        self.post(srv, d)
        r = self.post(srv, d)
        self.assertEqual(len(srv.keys_sent), 1)
        self.assertIn("déjà", r["error"])

    def test_choose_failed_keys_is_reported_and_not_remembered(self):
        srv = self.srv()
        srv.keys_error = "terminal introuvable"
        d = self.request()
        self.assertIn("terminal introuvable", self.post(srv, d)["error"])
        srv.keys_error = None
        self.assertEqual(self.post(srv, d)["ok"], True)

    def test_choose_logs(self):
        srv = self.srv()
        self.post(srv, self.request())
        with open(srv.SENTF) as f:
            e = json.loads(f.read().splitlines()[-1])
        self.assertEqual((e["choose"], e["role"], e["kind"], e["address"], e["label"]), ("1", "approve", "permission", "t3", "Yes"))
        self.assertEqual(e["space"], "outils / 1")


if __name__ == "__main__":
    unittest.main()
