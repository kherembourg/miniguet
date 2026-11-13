"""Last message from the user and last reply of an agent (GET /api/thread). Pure core, wired by register(srv)."""
import json, re
from urllib.parse import parse_qs, urlparse

FRAME = re.compile(r"^[\s│╭╰─┌└┐┘╮╯]+$")
PROMPT = re.compile(r"^[>❯]")


def _msg(m, limit):
    ts, _, text = m
    return {"text": text[:limit], "ts": ts, "truncated": len(text) > limit, "full": text}


def last_exchange(msgs, limit=600):
    """{"me", "agent"}: my last message, and the agent's last one after it (else its last one)."""
    me_i = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i][1] == "user"), None)
    after = msgs[me_i + 1:] if me_i is not None else msgs
    agent = next((m for m in reversed(after) if m[1] == "assistant"), None) \
        or next((m for m in reversed(msgs) if m[1] == "assistant"), None)
    return {"me": _msg(msgs[me_i], limit) if me_i is not None else None,
            "agent": _msg(agent, limit) if agent else None}


def screen_excerpt(lines, limit=600):
    """The end of a screen without frames, prompt and trailing blank lines (limit=None: all of it)."""
    keep = [ln.rstrip() for ln in lines if not FRAME.match(ln) and not PROMPT.match(ln.strip(" │"))]
    text = "\n".join(keep).strip()
    return text if limit is None else text[-limit:]


def register(srv):
    def thread_route(h, body):
        addr = parse_qs(urlparse(h.path).query).get("address", [""])[0]
        pid = srv.pid_of(addr)
        if pid:
            out = last_exchange(srv.messages(pid))
        else:   # another machine's session, or the old herdr: only the screen is known
            try:
                full = screen_excerpt(srv.read_screen(addr), None)
            except Exception:
                full = ""
            out = {"me": None, "agent": None}
            if full:
                a = {"text": full[-600:], "ts": None, "truncated": len(full) > 600, "full": full, "screen": True}
                out["agent"] = a
        return 200, "application/json", json.dumps(out, ensure_ascii=False).encode()

    srv.ROUTES["GET"]["/api/thread"] = thread_route
