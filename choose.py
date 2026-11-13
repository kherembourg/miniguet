"""Answer the numbered menus of Claude Code (permission requests and choice menus) from the board.

Pure core (no import of server.py): read the menu on a screen, hash the whole request, check before a key is sent.
"""
import hashlib, json, re

OPTION = re.compile(r"^\s*(?:❯\s*)?(\d)\.\s+(.+?)\s*$")
FRAME_TOP = re.compile(r"^─{20,}\s*$")           # top edge of the request frame
FRAME_LINE = re.compile(r"^[\s│╭╰─╌┌└┐┘╮╯]*$")    # frame and separator lines
FREE_TEXT = re.compile(r"^(?:other|type something|autre|chat about this|discuter)\b", re.I)
MULTI = re.compile(r"^(?:\[[ xX✔]?\]|[☐◻☑✔])")
DETAIL_MAX = 400
LOOKBACK = 15


def _role(label):
    low = label.lower()
    if low.startswith("no"):
        return "deny"
    if low.startswith("yes"):
        # only a plain "Yes" answers this one request; "Yes, and don't ask again", "Yes, allow … from this project",
        # "Yes, and switch to …" also change what is allowed afterwards
        return "approve" if re.fullmatch(r"yes\W*", low) else "always"
    return None


def parse_menu(lines, kind):
    """The numbered menu at the bottom of `lines`, or None. `kind` is what herdr reported ("permission" or "question").
    Unsupported or incomplete menus come back with `options: []` (the page says "Réponds dans le terminal")."""
    first = None
    for i in range(len(lines) - 1, -1, -1):
        m = OPTION.match(lines[i])
        if m and m.group(1) == "1":
            first = i
            break
    if first is None:
        return None
    opts = []
    for ln in lines[first:]:
        m = OPTION.match(ln)
        if m and int(m.group(1)) == len(opts) + 1:
            opts.append({"key": m.group(1), "label": m.group(2)})
    if len(opts) < 2:
        return None
    q = next((i for i in range(first - 1, max(first - LOOKBACK, 0) - 1, -1) if lines[i].rstrip().endswith("?")), None)
    if q is None:
        return None
    question = lines[q].strip()
    top = next((i for i in range(q - 1, -1, -1) if FRAME_TOP.match(lines[i])), None)
    p = {"kind": kind, "tool": "", "question": question, "detail": "", "full": "", "truncated": False, "options": []}
    if top is None:   # the top of the request is not on the screen read: never offer a button for a request not seen in full
        return p
    body = [ln for ln in lines[top + 1:q] if ln.strip() and not FRAME_LINE.match(ln) and not ln.strip().startswith("Tip:")]
    if kind == "permission" and body:
        p["tool"], body = body[0].strip(), body[1:]
    p["full"] = "\n".join(ln.strip() for ln in body)
    p["detail"] = p["full"][:DETAIL_MAX]
    p["truncated"] = len(p["full"]) > DETAIL_MAX
    if any(MULTI.match(o["label"]) for o in opts):
        return p   # multiple choices: not supported
    if any(FREE_TEXT.match(o["label"]) for o in opts):
        p["free_text"] = True
        opts = [o for o in opts if not FREE_TEXT.match(o["label"])]
    for o in opts:
        o["role"] = _role(o["label"]) if kind == "permission" else "choice"
    if kind == "permission":
        roles = {o["role"] for o in opts}
        if "approve" not in roles or "deny" not in roles:
            return p
    elif kind != "question":
        return p
    p["options"] = opts
    return p


def menu_hash(p):
    """SHA-1 of the whole request that was read (not of the screen: the footer moves without the request changing)."""
    body = [p["kind"], p["tool"], p["question"], p["full"], [(o["key"], o["label"]) for o in p["options"]]]
    return hashlib.sha1(json.dumps(body, ensure_ascii=False).encode()).hexdigest()


def check_choice(state, kind, lines, key, expected_hash):
    """(option, None) if pressing `key` answers the very request the user saw, else (None, message)."""
    if state != "blocked":
        return None, "la session n'attend plus de réponse"
    p = parse_menu(lines, kind)
    if not p or not p["options"]:
        return None, "menu non reconnu : réponds dans le terminal"
    if menu_hash(p) != expected_hash:
        return None, "la demande a changé depuis l'affichage : relis-la"
    opt = next((o for o in p["options"] if o["key"] == key), None)
    if not opt:
        return None, "cette option n'est pas proposée"
    return opt, None
