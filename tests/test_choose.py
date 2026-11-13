import os, re, unittest

from choose import check_choice, menu_hash, parse_menu

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


if __name__ == "__main__":
    unittest.main()
