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
    def listed(addr):
        """Only what the board lists: a live top-level agent of herdr, or an agent a module contributes (old herdr)."""
        terms = srv.snapshot()
        if any(t["address"] == addr and srv.main_agent(t) for t in terms):
            return True
        for fn in srv.AGENT_SOURCES:
            try:
                if any(a["address"] == addr for a in fn(terms)):
                    return True
            except Exception:
                pass
        return False

    def from_screen(addr):
        try:
            full = screen_excerpt(srv.read_screen(addr), None)
        except Exception:
            full = ""
        a = {"text": full[-600:], "ts": None, "truncated": len(full) > 600, "full": full, "screen": True}
        return {"me": None, "agent": a if full else None}

    def thread_route(h, body):
        addr = parse_qs(urlparse(h.path).query).get("address", [""])[0]
        if not listed(addr):
            return 404, "application/json", json.dumps({"error": "session inconnue"}).encode()
        pid = srv.pid_of(addr)
        out = last_exchange(srv.messages(pid)) if pid else {"me": None, "agent": None}
        if not out["me"] and not out["agent"]:   # another machine, the old herdr, or a session with no Claude transcript (Codex)
            out = from_screen(addr)
        return 200, "application/json", json.dumps(out, ensure_ascii=False).encode()

    srv.ROUTES["GET"]["/api/thread"] = thread_route
