"""Google Calendar busy intervals for Miniguet (meetings only: no titles are ever stored).

The calendar comes through the claude.ai Google Calendar connector, called headless with `claude -p`
(same pattern as server.py). Result cached in ~/.local/state/herdr-board/gcal.json:
    {"days": {"2026-11-05": {"fetched_ms": ..}},        # days already fetched (past days are never refetched)
     "events": [{"start_ms", "end_ms", "type", "attendees", "response"}], "error": str|None, "fetched_ms": ..}
Public: busy(start_ms, end_ms) -> [(start_ms, end_ms)] clipped intervals, merged.
Registered from stats.register(): it plugs into stats.BUSY_SOURCES so that meetings are subtracted from the
presence and waiting-time measures. Named gcal.py on purpose: `calendar.py` would shadow the stdlib module.
"""
import datetime, json, os, re, subprocess, threading, time

STATE = os.path.expanduser("~/.local/state/herdr-board/gcal.json")
SCRATCH = os.environ.get("HERDR_BOARD_CWD") or os.path.expanduser("~/.local/state/herdr-board/scratch")   # private working folder
os.makedirs(SCRATCH, mode=0o700, exist_ok=True)
MIN_ATTENDEES = 2      # a timed event counts as a meeting when it has at least 2 attendees (you included), or is out of office
REFRESH_S = 1800       # today and the next days are refetched every 30 min
LOOKBACK_DAYS = 15
AHEAD_DAYS = 2

_lock = threading.Lock()
_data = {"days": {}, "events": [], "error": None, "fetched_ms": 0}

PROMPT = """Use the Google Calendar list_events tool on the primary calendar (calendarId "primary") for events between {start} and {end} (local time, no UTC offset in the arguments), orderBy startTime, pageSize 250, and follow nextPageToken until done. Include out-of-office events.
Output ONLY a JSON array, no prose, no markdown fence. One object per TIMED event (skip all-day events, events I declined, events marked free/transparent, working-location events):
{{"start": ISO 8601 with offset, "end": ISO 8601 with offset, "type": "DEFAULT" or "OUT_OF_OFFICE" or "FOCUS_TIME", "response": my response (accepted/tentative/needsAction/organizer), "attendees": number of attendees including me}}.
Never include titles, descriptions, attendee names or links. If there is no event, output [].
"""


def _load():
    global _data
    try:
        with open(STATE) as f:
            _data = json.load(f)
    except Exception:
        pass


def _save():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_data, f)
    os.replace(tmp, STATE)


def _ms(iso):
    return int(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _fetch(d0, d1):
    """Events starting in [d0, d1) (dates). Raises on any problem so that a bad answer is never cached."""
    p = PROMPT.format(start=d0.isoformat() + "T00:00:00", end=d1.isoformat() + "T00:00:00")
    r = subprocess.run(
        ["claude", "-p", "--model", "sonnet", "--no-session-persistence", "--settings", '{"disableAllHooks":true}',
         "--setting-sources", "user", "--disable-slash-commands", "--tools", "", "--allowedTools", "mcp__claude_ai_Google_Calendar__list_events"],
        input=p, capture_output=True, text=True, timeout=180, cwd=SCRATCH)
    txt = re.sub(r"^```(?:json)?|```$", "", r.stdout.strip(), flags=re.M).strip()
    arr = json.loads(txt)
    if not isinstance(arr, list):
        raise ValueError("not a list")
    lo = int(datetime.datetime.combine(d0, datetime.time()).timestamp() * 1000) - 86400000
    hi = int(datetime.datetime.combine(d1, datetime.time()).timestamp() * 1000) + 86400000
    out = []
    for e in arr:
        s, t = _ms(e["start"]), _ms(e["end"])
        if not (t > s and lo <= s <= hi):
            raise ValueError("implausible event")
        out.append({"start_ms": s, "end_ms": t, "type": str(e.get("type") or "DEFAULT"),
                    "attendees": int(e.get("attendees") or 0), "response": str(e.get("response") or "")})
    return out


def refresh():
    """Fetch what is missing in the lookback window plus today..today+AHEAD_DAYS (always refetched)."""
    today = datetime.date.today()
    want = [today + datetime.timedelta(days=i) for i in range(-LOOKBACK_DAYS, AHEAD_DAYS + 1)]
    with _lock:
        have = set(_data["days"])
    missing = [d for d in want if d.isoformat() not in have and d < today]
    live = [d for d in want if d >= today]
    chunks = []
    for group in (missing, live):      # contiguous runs of at most 7 days per call
        group = sorted(group)
        i = 0
        while i < len(group):
            j = i
            while j + 1 < len(group) and (group[j + 1] - group[i]).days < 7 and (group[j + 1] - group[j]).days == 1:
                j += 1
            chunks.append((group[i], group[j] + datetime.timedelta(days=1)))
            i = j + 1
    err = None
    for d0, d1 in chunks:
        try:
            evs = _fetch(d0, d1)
        except Exception as e:
            err = f"{d0}..{d1}: {str(e)[:150]}"
            continue
        lo_ms = int(datetime.datetime.combine(d0, datetime.time()).timestamp() * 1000)
        hi_ms = int(datetime.datetime.combine(d1, datetime.time()).timestamp() * 1000)
        with _lock:
            keep = [e for e in _data["events"] if not (lo_ms <= e["start_ms"] < hi_ms)]
            _data["events"] = keep + [e for e in evs if lo_ms <= e["start_ms"] < hi_ms]
            n = (d1 - d0).days
            for k in range(n):
                _data["days"][(d0 + datetime.timedelta(days=k)).isoformat()] = {"fetched_ms": int(time.time() * 1000)}
            _data["fetched_ms"] = int(time.time() * 1000)
            _save()
    with _lock:
        _data["error"] = err
        _save()
    return err


def busy(start_ms, end_ms):
    with _lock:
        evs = list(_data["events"])
    iv = []
    for e in evs:
        if not (e["type"] == "OUT_OF_OFFICE" or (e["type"] == "DEFAULT" and e["attendees"] >= MIN_ATTENDEES)):
            continue
        s, t = max(e["start_ms"], start_ms), min(e["end_ms"], end_ms)
        if t > s:
            iv.append((s, t))
    iv.sort()
    out = []
    for s, t in iv:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], t))
        else:
            out.append((s, t))
    return out


def _loop():
    while True:
        try:
            refresh()
        except Exception as e:
            print("gcal refresh failed:", e, flush=True)
        time.sleep(REFRESH_S)


def register(srv, stats=None):
    _load()
    if stats is not None:
        busy.version = lambda: _data.get("fetched_ms", 0)   # lets stats.py invalidate its cache when the calendar changes
        stats.BUSY_SOURCES.append(busy)

    def status(h, body):
        meetings = len(busy(0, 1 << 62))      # takes the lock itself: never call it while holding it
        with _lock:
            d = {"fetched_ms": _data.get("fetched_ms"), "error": _data.get("error"),
                 "days": len(_data["days"]), "events": len(_data["events"]), "meetings": meetings}
        return 200, "application/json", json.dumps(d).encode()

    srv.ROUTES["GET"]["/api/calendar/status"] = status
    threading.Thread(target=_loop, daemon=True).start()
