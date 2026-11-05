"""Sessions of the old herdr CLI (0.9.x) shown on the board, read-only (list / read commands only).

`herdr pane read` takes 0.4-1.3 s, so a background thread polls the CLI and the screens;
the agent source registered in server.py only reads that cache and never blocks.
"""
import glob, json, os, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor

HERDR = "/opt/homebrew/bin/herdr"
APPS = {"claude": "claude-code", "codex": "codex"}
EVERY = 2        # seconds between polls of the agent list
SCREEN_TTL = 15  # a "done" screen is re-read at least this often (always, when its state changed)

_lock = threading.Lock()
_snap = []       # agents of the last good poll, without q
_screens = {}    # address -> (state_change_seq, read_ts, lines)
_track = {}      # address -> {"seq", "status", "since", "turn"}


def _cli(*args):
    r = subprocess.run([HERDR, *args], capture_output=True, text=True, timeout=3, check=True)
    return json.loads(r.stdout)["result"]


def _read(pane):
    r = subprocess.run([HERDR, "pane", "read", pane, "--lines", "150"], capture_output=True, text=True, timeout=3, check=True)
    return r.stdout.splitlines()


def _claude_sessions():
    """sessionId -> (pid, statusUpdatedAt ms) from ~/.claude/sessions/<pid>.json (latest file wins)."""
    out = {}
    for f in glob.glob(os.path.expanduser("~/.claude/sessions/*.json")):
        try:
            with open(f) as fh:
                d = json.load(fh)
            if d["sessionId"] not in out or d["updatedAt"] > out[d["sessionId"]][2]:
                out[d["sessionId"]] = (d["pid"], d["statusUpdatedAt"], d["updatedAt"])
        except Exception:
            pass
    return out


def _poll():
    agents = _cli("agent", "list")["agents"]
    spaces = {w["workspace_id"]: w["label"] for w in _cli("workspace", "list")["workspaces"]}
    tabs = {t["tab_id"]: t["label"] for t in _cli("tab", "list")["tabs"]}
    sess = _claude_sessions()
    now = int(time.time() * 1000)
    snap = []
    for a in agents:
        # "hd-*" are workers delegated by another agent (herdr-delegate): sub-agents, not shown
        if a.get("agent") not in APPS or (a.get("name") or "").startswith("hd-"):
            continue
        addr = "h:" + a["pane_id"]
        st = "working" if a.get("agent_status") == "working" else "done"
        sid = (a.get("agent_session") or {}).get("value")
        pid, seen_ms, _ = sess.get(sid, (None, None, None))
        tr = _track.get(addr)
        if not tr:  # first sight: seed from Claude's own status time so a restart keeps the same since_ms
            tr = _track[addr] = {"seq": a["state_change_seq"], "status": st, "since": seen_ms or now, "turn": 0}
        elif tr["seq"] != a["state_change_seq"]:
            if tr["status"] == "working" and st == "done":
                tr["turn"] += 1
            tr.update(seq=a["state_change_seq"], status=st, since=now)
        tr["status"] = st
        snap.append({
            "address": addr, "pane": a["pane_id"], "seq": a["state_change_seq"], "pid": pid,
            "space": spaces.get(a["workspace_id"], a["workspace_id"]), "tab": tabs.get(a["tab_id"], ""),
            "title": a.get("terminal_title_stripped") or "", "agent": APPS[a["agent"]], "status": st,
            "msg": "attend une validation" if a.get("agent_status") == "blocked" else "",
            "since_ms": tr["since"], "turn": tr["turn"], "cwd": a.get("cwd", ""),
        })
    alive = {r["address"] for r in snap}
    for d in (_track, _screens):
        for k in [k for k in d if k not in alive]:
            del d[k]
    with _lock:
        _snap[:] = snap
    return snap


def _screen(r):
    try:
        _screens[r["address"]] = (r["seq"], time.time(), _read(r["pane"]))
    except Exception:
        pass  # keep the previous screen, if any


def _loop():
    pool = ThreadPoolExecutor(max_workers=4)
    while True:
        try:
            snap = _poll()
            now = time.time()
            stale = [r for r in snap if r["status"] == "done"
                     and ((_screens.get(r["address"]) or (None, 0))[0] != r["seq"]
                          or now - _screens[r["address"]][1] > SCREEN_TTL)]
            list(pool.map(_screen, stale))
        except Exception:
            with _lock:  # CLI or server down: the board shows nothing from the old herdr
                _snap.clear()
        time.sleep(EVERY)


def register(srv):
    def source(_terminals):
        with _lock:
            snap = list(_snap)
        out = []
        for r in snap:
            addr = r["address"]
            if r["status"] == "done":
                sc = _screens.get(addr)
                if sc:
                    t = {"address": addr, "turn": r["turn"], "status_ms": r["since_ms"]}
                    if r["pid"]:
                        t["foreground"] = {"pid": r["pid"]}
                    q = srv.questions_for(t, reader=lambda _a, lines=sc[2]: lines)
                else:
                    q = {"draft": "", "bg": {"monitors": 0, "shells": 0}, "pending": True}
            else:
                q = {"carry": srv.filt(addr, srv.LAST[addr])} if addr in srv.LAST else None
            out.append({
                "address": addr, "space": r["space"], "tab": r["tab"], "title": r["title"],
                "agent": r["agent"], "status": r["status"], "msg": r["msg"], "since_ms": r["since_ms"],
                "unseen": False, "cwd": r["cwd"], "subagents": {}, "deadline": srv.DL.get(addr),
                "dismissed": srv.DISM.get(addr, []), "source": "herdr-cli", "q": q,
            })
        return out

    srv.AGENT_SOURCES.append(source)
    threading.Thread(target=_loop, daemon=True).start()
