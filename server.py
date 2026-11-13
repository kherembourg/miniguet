#!/usr/bin/env python3
"""THROWAWAY SPIKE: desk board for Herdr agents waiting on you.

Reads the Herdr app state via `hc events` (first line = full snapshot) and
serves a single page. Stdlib only.

    python3 server.py                 # http://127.0.0.1:8765
    python3 server.py --host 0.0.0.0  # reachable from a tablet on your LAN
"""
import argparse, datetime, difflib, glob, hmac, importlib, json, os, re, secrets, shutil, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cfaccess

HC = os.path.expanduser("~/.local/bin/hc")
HERE = os.path.dirname(os.path.abspath(__file__))
# MINIGUET_DEMO=<folder>: sample data instead of Herdr (terminals.json, screens/, transcripts/), state kept in <folder>/state
DEMO = os.path.abspath(os.environ["MINIGUET_DEMO"]) if os.environ.get("MINIGUET_DEMO") else None


def demo_log(line):
    with open(os.path.join(DEMO, "out.log"), "a") as f:
        f.write(line.replace("\n", "\\n") + "\n")


def snapshot():
    if DEMO:
        with open(os.path.join(DEMO, "terminals.json")) as f:
            return [_remote(t) for t in json.load(f)["terminals"]]
    p = subprocess.Popen([HC, "events"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        line = p.stdout.readline()
    finally:
        p.kill()
        p.wait()
    return [_remote(t) for t in json.loads(line)["terminals"]]


def _remote(t):
    """Terminals of other machines added with `hc machine add` have addresses like "m5/t7". Their pid is only
    meaningful over there: drop it, or it would be looked up in this Mac's ~/.claude/sessions (a matching pid
    would attach the wrong conversation). Prefix the space name with the machine, so the board says where it runs."""
    addr = t.get("address") or ""
    if "/" in addr:
        machine = addr.split("/", 1)[0]
        if t.get("foreground"):
            t["foreground"] = {k: v for k, v in t["foreground"].items() if k != "pid"}
        labels = t.setdefault("labels", {})
        if labels.get("where") and not labels["where"].startswith(machine + " · "):
            labels["where"] = f"{machine} · {labels['where']}"
    return t


STATE_DIR = os.path.join(DEMO, "state") if DEMO else os.path.expanduser("~/.local/state/herdr-board")
if DEMO and not os.path.isdir(STATE_DIR):   # first launch: the state starts as a copy of <folder>/seed/
    shutil.copytree(os.path.join(DEMO, "seed"), STATE_DIR)
    for _n in os.listdir(STATE_DIR):   # dates and paths that cannot be written in a tracked file
        _p = os.path.join(STATE_DIR, _n)
        if _n.endswith(".json"):
            with open(_p) as _f:
                _s = _f.read()
            with open(_p, "w") as _f:
                _f.write(_s.replace("{today}", time.strftime("%Y-%m-%d")).replace("{repo}", HERE))
# working folder of the `claude -p` calls: private (0700) and user-owned, never a shared /tmp where another user could plant a .claude/settings.json
SCRATCH = os.environ.get("HERDR_BOARD_CWD") or os.path.join(STATE_DIR, "scratch")
os.makedirs(SCRATCH, mode=0o700, exist_ok=True)
POOL = ThreadPoolExecutor(max_workers=4)
CACHE = {}   # key -> {"open": [...], "answered": [...]} | {"error": str}
INFLIGHT = set()
MEM = os.path.join(STATE_DIR, "memory.json")
try:
    with open(MEM) as f:
        LAST = json.load(f)   # addr -> last good analysis, shown dimmed while the agent works
except Exception:
    LAST = {}


DLF = os.path.join(os.path.dirname(MEM), "deadlines.json")
try:
    with open(DLF) as f:
        DL = json.load(f)   # addr -> {"date": "YYYY-MM-DD", "note": str}
except Exception:
    DL = {}


def save_dl():
    os.makedirs(os.path.dirname(DLF), exist_ok=True)
    tmp = DLF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(DL, f, ensure_ascii=False)
    os.replace(tmp, DLF)


DIF = os.path.join(os.path.dirname(MEM), "dismissed.json")
try:
    with open(DIF) as f:
        DISM = json.load(f)   # addr -> [item texts the user removed from the board]
except Exception:
    DISM = {}


def save_dism():
    os.makedirs(os.path.dirname(DIF), exist_ok=True)
    tmp = DIF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(DISM, f, ensure_ascii=False)
    os.replace(tmp, DIF)


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


SNZF = os.path.join(os.path.dirname(MEM), "snooze.json")
SNZ = load_json(SNZF)        # addr -> {"until": epoch_ms}: session hidden at the bottom until then
SNZIF = os.path.join(os.path.dirname(MEM), "snooze_items.json")
SNZI = load_json(SNZIF)      # addr -> {item text: until epoch_ms}


def filt(addr, res):
    """Drop items the user dismissed or snoozed (does not mutate res)."""
    now_ms = time.time() * 1000
    bad = set(DISM.get(addr, ())) | {t for t, u in SNZI.get(addr, {}).items() if u > now_ms}
    if not res or not bad:
        return res
    r = dict(res)
    for k in ("open", "todo"):
        if k in r:
            r[k] = [x for x in r[k] if x not in bad]
    return r


def save_mem():
    os.makedirs(os.path.dirname(MEM), exist_ok=True)
    tmp = MEM + ".tmp"
    with open(tmp, "w") as f:
        json.dump(LAST, f, ensure_ascii=False)
    os.replace(tmp, MEM)
DRAFT_SEEN = {}  # addr -> (draft, first_seen_ts)
LOCK = threading.Lock()

PROMPT = """Voici la fin de l'écran d'une session d'agent de code (Claude Code ou Codex).
L'agent a terminé son tour. Dis ce qu'il attend de l'utilisateur.

Réponds UNIQUEMENT par un JSON : {"open": [...], "todo": [...], "answered": [...]}
- "open" : décisions, questions ou validations que l'agent demande à l'utilisateur
  et qui n'ont PAS reçu de réponse. Une ligne courte et autonome chacune, en français,
  formulée comme une question (ex. "Lancer la passe d'allègement de la PR 946 ?").
  Chaque ligne fait 12 mots maximum : va droit au sujet, sans contexte ni explication.
  Reformule aussi de cette façon les points de l'analyse précédente.
  Ne mets rien si l'agent annonce seulement qu'il attend un autre agent, un
  build, la CI ou un rapport : ce n'est pas l'utilisateur qu'il attend.
- "todo" : actions que l'agent demande à l'utilisateur de faire lui-même, hors
  réponse à une question (tester quelque chose, vérifier, installer, revenir le voir
  après un essai). Une ligne courte à l'infinitif (ex. "Tester sur la tablette, puis revenir").
  Ne mets pas ici ce qui est déjà dans "open".
- "answered" : questions posées par l'agent plus haut dans l'écran et auxquelles
  l'utilisateur a déjà répondu (message de l'utilisateur visible après la question).
{draft}{prev}
Écran :
{screen}
"""


def read_screen(addr):
    if DEMO:
        try:
            with open(os.path.join(DEMO, "screens", addr.replace("/", "_") + ".txt")) as f:
                return f.read().splitlines()
        except OSError:
            return []
    out = subprocess.run([HC, "read", addr], capture_output=True, text=True, timeout=3).stdout
    return out.splitlines()


STALL = {}   # addr -> [status_ms, screen hash, when it last changed, when last read]; memory only


def stalled_min(addr, status_ms, now):
    """Minutes (once >= 30) a working agent's screen has stayed the same; the screen is read at most every 30 s."""
    s = STALL.get(addr)
    if not s or s[0] != status_ms:
        s = STALL[addr] = [status_ms, None, now, 0]
    if now - s[3] >= 30:
        try:  # digits and spinner glyphs out: the elapsed-time counter keeps ticking while the agent is stuck
            h = hash(re.sub(r"[\d·✢✳✶✻✽*]+", "", "\n".join(read_screen(addr)[-30:])))
        except Exception:
            h = s[1]
        s[3] = now
        if h != s[1]:
            s[1], s[2] = h, now
    m = int((now - s[2]) // 60)
    return m if m >= 30 else None


def find_draft(lines):
    for ln in reversed(lines[-6:]):
        m = re.match(r"^\s*❯\s*(.*\S)\s*$", ln)
        if m:
            d = m.group(1)
            return "" if re.fullmatch(r"[<\d;Mm]+", d) else d   # leftover mouse-wheel escape codes are not a draft
    return ""


TRANS = {}   # path -> (mtime, size, msgs)
CLAUDE = os.path.expanduser("~/.claude")


def transcript_path(pid):
    if DEMO:
        p = os.path.join(DEMO, "transcripts", f"{pid}.jsonl")
        return p if os.path.isfile(p) else None
    try:
        with open(f"{CLAUDE}/sessions/{pid}.json") as f:
            sid = json.load(f)["sessionId"]
        m = glob.glob(f"{CLAUDE}/projects/*/{sid}.jsonl")
        return m[0] if m else None
    except Exception:
        return None


def _text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def messages(pid):
    """[(ts_ms, 'user'|'assistant', text)] of the plain-text turns of the Claude Code session behind a pid."""
    p = transcript_path(pid)
    if not p:
        return []
    st = os.stat(p)
    c = TRANS.get(p)
    if c and c[0] == st.st_mtime and c[1] == st.st_size:
        return c[2]
    out = []
    with open(p) as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") not in ("user", "assistant") or o.get("isSidechain") or o.get("isMeta"):
                continue
            t = _text((o.get("message") or {}).get("content")).strip()
            if not t or t.startswith("<") or "<system-reminder>" in t[:40]:
                continue
            try:
                ms = int(datetime.datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                continue
            out.append((ms, o["type"], t))
    TRANS[p] = (st.st_mtime, st.st_size, out)
    return out


_TOK = re.compile(r"[a-zàâçéèêëîïôûùüÿ0-9_\-\.]{4,}")


def _overlap(item, text):
    ti = set(_TOK.findall(item.lower()))
    return len(ti & set(_TOK.findall(text.lower()))) / len(ti) if ti else 0.0


def source_index(item, msgs, thr=0.6):
    """Index of the earliest assistant message that raises this item (token overlap), or None."""
    for i, (_, role, t) in enumerate(msgs):
        if role == "assistant" and _overlap(item, t) >= thr:
            return i
    return None


def analyze(key, screen_tail, draft, pid=None):
    try:
        with LOCK:
            old = LAST.get(key[0]) or {}
        olditems = [("question", x) for x in old.get("open", [])] + [("à faire", x) for x in old.get("todo", [])]
        pv = ""
        if olditems:
            pv = ("\nPoints restés ouverts lors de l'analyse précédente :\n"
                  + "\n".join(f"- ({k}) {x}" for k, x in olditems)
                  + "\nGarde chacun de ces points dans \"open\" (question) ou \"todo\" (à faire) tant que "
                    "l'écran ne montre pas que l'utilisateur y a répondu, l'a fait ou l'a abandonné, ou que l'agent "
                    "ne l'a déclaré résolu. S'il est réglé, mets-le dans \"answered\". Un nouveau message de l'agent "
                    "sur un autre sujet ne règle PAS un ancien point. Ajoute aussi les nouveaux points du dernier message.\n")
        with LOCK:
            ign = list(DISM.get(key[0], []))
        if ign:
            pv += ("\nPoints que l'utilisateur a retirés (ne plus les lister, même reformulés) :\n"
                   + "\n".join(f"- {x}" for x in ign) + "\n")
        d = f"\nL'utilisateur a tapé ce texte dans la zone de saisie, pas encore envoyé : « {draft} »\n" if draft else ""
        p = PROMPT.replace("{draft}", d).replace("{prev}", pv).replace("{screen}", screen_tail)
        r = subprocess.run(
            ["claude", "-p", "--model", "haiku", "--no-session-persistence",
             "--settings", '{"disableAllHooks":true}', "--setting-sources", "user",
             "--disable-slash-commands", "--tools", ""],   # no project settings, no built-in tools: text in, text out
            input=p, capture_output=True, text=True, timeout=90, cwd=SCRATCH)
        txt = re.sub(r"^```(?:json)?|```$", "", r.stdout.strip(), flags=re.M).strip()
        j = json.loads(txt)
        res = {"open": [str(x) for x in j.get("open", [])],
               "todo": [str(x) for x in j.get("todo", [])],
               "answered": [str(x) for x in j.get("answered", [])]}
        # first-seen time per item: inherit from a matching earlier item (even if rephrased), else
        # the moment the agent finished the turn that raised it (status_ms); 0 = unknown (legacy memory)
        old_ts = old.get("ts", {})
        olds = [x for x in old.get("open", []) + old.get("todo", [])]
        ts = {}
        for x in res["open"] + res["todo"]:
            if x in old_ts:
                ts[x] = old_ts[x]
            elif x in olds:
                ts[x] = 0
            else:
                best = max(olds, key=lambda o: difflib.SequenceMatcher(None, o.lower(), x.lower()).ratio(), default=None)
                if best and difflib.SequenceMatcher(None, best.lower(), x.lower()).ratio() >= 0.55:
                    ts[x] = old_ts.get(best, 0)
                else:
                    ts[x] = key[2] or 0
        if pid:
            try:
                ms = messages(pid)
                for x in ts:
                    i = source_index(x, ms)
                    if i is not None:
                        ts[x] = ms[i][0]
            except Exception:
                pass
        res["ts"] = ts
        res["tkey"] = [key[1], key[2]]
    except Exception as e:
        res = {"error": str(e)[:200]}
    with LOCK:
        CACHE[key] = res
        if "error" not in res:
            LAST[key[0]] = res
            try:
                save_mem()
            except Exception:
                pass
        INFLIGHT.discard(key)


def questions_for(t, reader=None):
    """reader(addr) -> list of screen lines; default reads a Herdr app terminal with hc."""
    addr = t["address"]
    lines = (reader or read_screen)(addr)
    draft = find_draft(lines)
    now = time.time()
    prev = DRAFT_SEEN.get(addr)
    if not prev or prev[0] != draft:
        DRAFT_SEEN[addr] = (draft, now)
    stable = now - DRAFT_SEEN[addr][1] >= 4  # wait until typing pauses
    key = (addr, t.get("turn"), t.get("status_ms"), draft if stable else None)
    with LOCK:
        res = CACHE.get(key)
        last = LAST.get(addr)
        if res is None and last and not key[3] and last.get("tkey") == [key[1], key[2]]:
            res = CACHE[key] = last   # same turn as the saved analysis (e.g. after a restart): no need to redo it
        if res is None and key not in INFLIGHT:
            INFLIGHT.add(key)
            tail = "\n".join(lines[-150:])
            POOL.submit(analyze, key, tail, draft if stable else "", (t.get("foreground") or {}).get("pid"))
    if res is None:  # fall back to the last known result for this turn while recomputing
        with LOCK:
            for k, v in CACHE.items():
                if k[:3] == key[:3] and "error" not in v:
                    res = v
    foot = "\n".join(lines[-4:])
    mo = re.search(r"(\d+)\s+monitors?", foot)
    sh = re.search(r"(\d+)\s+shells?", foot)
    out = {"draft": draft, "bg": {"monitors": int(mo.group(1)) if mo else 0,
                                  "shells": int(sh.group(1)) if sh else 0}}
    with LOCK:
        if res:
            out.update(filt(addr, res))
        elif LAST.get(addr):   # analysis of a new turn still running: keep showing the previous points meanwhile
            out.update(filt(addr, LAST[addr]))
            out["stale"] = True
        else:
            out["pending"] = True
    return out


def prune_snoozes(live, now_ms):
    """Forget snoozes of closed spaces and expired ones."""
    with LOCK:
        a1 = [a for a, v in SNZ.items() if a not in live or v["until"] <= now_ms]
        for a in a1:
            del SNZ[a]
        if a1:
            save_json(SNZF, SNZ)
        n = 0
        for a in list(SNZI):
            keep = {t: u for t, u in SNZI[a].items() if u > now_ms} if a in live else {}
            n += len(keep) != len(SNZI[a])
            if keep:
                SNZI[a] = keep
            else:
                del SNZI[a]
        if n:
            save_json(SNZIF, SNZI)


def main_agent(t):
    """A live top-level agent of the Herdr app: what the board lists (sub-agents and plain programs are not)."""
    return not t.get("parent") and t.get("state") == "live" and bool(t.get("status"))


def build_state():
    now = time.time()
    now_ms = int(now * 1000)
    terms = snapshot()
    live = {t["address"] for t in terms if t.get("state") == "live"}
    extra = []   # agents contributed by modules (e.g. sessions of the old herdr CLI)
    for fn in AGENT_SOURCES:
        try:
            extra += fn(terms)
        except Exception as e:
            print("agent source failed:", fn, e, flush=True)
    live |= {e["address"] for e in extra}
    prune_snoozes(live, now_ms)
    for a in [a for a in STALL if a not in live]:
        del STALL[a]
    with LOCK:  # a closed space leaves the live list: forget its memory
        stale = [a for a in LAST if a not in live]
        for a in stale:
            del LAST[a]
        for k in [k for k in CACHE if k[0] not in live]:
            del CACHE[k]
    for a in [a for a in DISM if a not in live]:
        del DISM[a]
        try:
            save_dism()
        except Exception:
            pass
    gone = [a for a in DL if a not in live]
    for a in gone:
        del DL[a]
    if gone:
        try:
            save_dl()
        except Exception:
            pass
    if stale:
        try:
            save_mem()
        except Exception:
            pass
    subs = {}
    for t in terms:
        if t.get("parent") and t.get("state") == "live" and t.get("status"):
            subs.setdefault(t["parent"], []).append(t["status"]["state"])
    agents = []
    for t in terms:
        if not main_agent(t):
            continue
        where = (t.get("labels") or {}).get("where", "?")
        space, _, tab = where.rpartition(" / ")
        seen = int((t.get("labels") or {}).get("herdr.seen", "0") or 0)
        st = t["status"]["state"]
        counts = {}
        for s in subs.get(t["address"], []):
            counts[s] = counts.get(s, 0) + 1
        agents.append({
            "address": t["address"],
            "space": space or where,
            "tab": tab,
            "title": t.get("title") or "",
            "agent": t["status"].get("app", ""),
            "status": st,
            "msg": t["status"].get("msg", ""),
            "since_ms": t.get("status_ms"),
            "unseen": st == "done" and t.get("turn", 0) > seen,
            "cwd": t.get("cwd", ""),
            "deadline": DL.get(t["address"]),
            "dismissed": DISM.get(t["address"], []),
            "subagents": counts,
            "stalled_min": stalled_min(t["address"], t.get("status_ms"), now) if st == "working" else None,
            "q": questions_for(t) if st == "done" else ({"carry": filt(t["address"], LAST[t["address"]])} if t["address"] in LAST else None),
        })
    agents += extra
    for a in agents:  # also for agents contributed by modules
        a.setdefault("snooze", SNZ.get(a["address"]))
        a.setdefault("snoozed", [{"text": t, "until": u} for t, u in list(SNZI.get(a["address"], {}).items())])
    for fn in SNAPSHOT_HOOKS:  # extension point: modules observe every state build
        try:
            fn(terms, agents)
        except Exception as e:
            print("snapshot hook failed:", fn, e, flush=True)
    return {"now_ms": now_ms, "agents": agents, "links": LINKS}


INFO = {}   # (addr, item) -> (n_msgs, result)
INFO_PROMPT = """Tu aides un utilisateur à se rappeler le contexte d'un point resté en attente dans une conversation avec un agent de code.
Date et heure actuelles : {now}.

Point en attente (posé par l'agent) : « {item} »

Message de l'agent où ce point a été soulevé ({when}) :
{source}

Échanges qui ont suivi (du plus ancien au plus récent) :
{after}

Réponds UNIQUEMENT par un JSON : {{"contexte": str, "depuis": str, "verdict": str, "preuve": str}}
- "contexte" : 2 à 4 phrases en français simple. De quoi parle ce point, pourquoi l'agent le demande, ce qu'il faut décider ou faire. Autonome : l'utilisateur a tout oublié.
- "depuis" : 1 à 2 phrases sur ce qui s'est passé ensuite en rapport avec ce point (réponse de l'utilisateur, action de l'agent, changement de sujet). "Rien depuis." si rien.
- "verdict" : "ouvert" (toujours à traiter), "probablement réglé", "probablement périmé" ou "incertain".
- "preuve" : si le verdict n'est pas "ouvert", la phrase ou le fait précis des échanges qui le justifie, sinon "".
Ne devine pas : si les échanges ne montrent rien, verdict "ouvert" ou "incertain".
"""


def clip(t, n):
    return t if len(t) <= n else t[:n] + " […]"


def info_for(addr, item, pid):
    ms = messages(pid) if pid else []
    if not ms:
        return {"error": "conversation introuvable"}
    k = (addr, item)
    hit = INFO.get(k)
    if hit and hit[0] == len(ms):
        return hit[1]
    i = source_index(item, ms, 0.5)
    if i is None:
        i = max(len(ms) - 40, 0)
    fmt = lambda ts: datetime.datetime.fromtimestamp(ts / 1000).strftime("%d/%m %H:%M")
    after = ms[i + 1:][-40:]
    p = INFO_PROMPT.format(
        now=datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), item=item, when=fmt(ms[i][0]),
        source=clip(ms[i][2], 5000),
        after="\n\n".join(f"[{fmt(a)}] {'UTILISATEUR' if r == 'user' else 'AGENT'} : {clip(t, 800)}" for a, r, t in after) or "(rien)")
    try:
        j = ask_sonnet(p)
        res = {k2: str(j.get(k2, "")) for k2 in ("contexte", "depuis", "verdict", "preuve")}
        res["raised"] = ms[i][0]
    except Exception as e:
        return {"error": str(e)[:200]}
    INFO[k] = (len(ms), res)
    return res


def ask_sonnet(prompt):
    """JSON answer of `claude -p --model sonnet` (the only place conversation content is sent)."""
    if DEMO:
        raise RuntimeError("démo : pas d'appel à Claude")
    r = subprocess.run(
        ["claude", "-p", "--model", "sonnet", "--no-session-persistence",
         "--settings", '{"disableAllHooks":true}', "--setting-sources", "user",
             "--disable-slash-commands", "--tools", ""],   # no project settings, no built-in tools: text in, text out
        input=prompt, capture_output=True, text=True, timeout=150, cwd=SCRATCH)
    return json.loads(re.sub(r"^```(?:json)?|```$", "", r.stdout.strip(), flags=re.M).strip())


def pid_of(addr):
    for t in snapshot():
        if t["address"] == addr:
            return (t.get("foreground") or {}).get("pid")
    return None


RESUME = {}   # addr -> (n_msgs, result)
RESUME_PROMPT = """Tu aides un utilisateur à reprendre une conversation avec un agent de code qu'il a laissée de côté.
Date et heure actuelles : {now}.

Début de la conversation (premier message de l'utilisateur) :
{first}

Derniers échanges (du plus ancien au plus récent) :
{last}

Réponds UNIQUEMENT par un JSON : {{"objectif": str, "avancement": str, "bloquant": str, "prochaine_etape": str}}
Chaque valeur : UNE phrase courte en français simple (20 mots maximum), autonome : l'utilisateur a tout oublié.
- "objectif" : ce que l'utilisateur cherche à obtenir dans cette conversation.
- "avancement" : ce qui a été fait jusqu'ici.
- "bloquant" : ce qui empêche d'avancer (souvent une réponse ou une action attendue de l'utilisateur). "Rien." si rien.
- "prochaine_etape" : la prochaine chose à faire, et par qui.
Ne devine pas : appuie-toi seulement sur les échanges.
"""


def resume_for(addr, pid):
    ms = messages(pid) if pid else []
    if not ms:
        return {"error": "conversation introuvable"}
    hit = RESUME.get(addr)
    if hit and hit[0] == len(ms):
        return hit[1]
    fmt = lambda ts: datetime.datetime.fromtimestamp(ts / 1000).strftime("%d/%m %H:%M")
    first = next((t for _, r, t in ms if r == "user"), "(aucun)")
    p = RESUME_PROMPT.format(
        now=datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), first=clip(first, 3000),
        last="\n\n".join(f"[{fmt(a)}] {'UTILISATEUR' if r == 'user' else 'AGENT'} : {clip(t, 800)}" for a, r, t in ms[-40:]))
    try:
        j = ask_sonnet(p)
        res = {k: str(j.get(k, "")) for k in ("objectif", "avancement", "bloquant", "prochaine_etape")}
    except Exception as e:
        return {"error": str(e)[:200]}
    RESUME[addr] = (len(ms), res)
    return res


def resume_route(h, body):
    addr = str(json.loads(body)["address"])
    return 200, "application/json", json.dumps(resume_for(addr, pid_of(addr)), ensure_ascii=False).encode()


SENTF = os.path.join(os.path.dirname(MEM), "sent.jsonl")
SEND_MAX = 4000
SEND_LOCK = threading.Lock()
SENT = {}   # addr -> status_ms of the turn we already answered: a double tap must not send twice


def send_check(addr, text, since_ms):
    """(terminal, None) if `text` may be typed into session `addr` now, else (terminal|None, {"error": reason})."""
    if not text.strip():
        return None, {"error": "message vide"}
    if text.lstrip()[:1] in ("!", "/"):   # an agent CLI runs "!cmd" as a shell command and "/cmd" as a slash command
        return None, {"error": "le message commence par « ! » ou « / » : l'agent l'exécuterait comme une commande, envoi refusé"}
    if len(text) > SEND_MAX:
        return None, {"error": f"message trop long ({len(text)} caractères, {SEND_MAX} au plus)"}
    t = next((t for t in snapshot() if t["address"] == addr), None)
    if not t or not main_agent(t):   # whitelist: only a session the board lists from the Herdr app
        return None, {"error": "session inconnue ou fermée : envoi refusé"}
    st = t["status"]["state"]
    if st == "working":
        return t, {"error": "la session travaille : attends qu'elle ait fini son tour"}
    if st != "done":
        return t, {"error": f"la session est « {st} », pas au repos : envoi refusé"}
    if SENT.get(addr) == t.get("status_ms"):
        return t, {"error": "un message vient déjà d'être envoyé à cette session : attends sa réponse"}
    if since_ms is not None and since_ms != t.get("status_ms"):
        # the agent took another turn since the preview: the questions may be stale
        return t, {"error": "la session a avancé depuis l'aperçu : relis, puis appuie à nouveau sur Envoyer pour confirmer",
                   "since_ms": t.get("status_ms")}
    draft = find_draft(read_screen(addr))
    if draft:
        return t, {"error": f"une réponse est déjà tapée dans la session (« {clip(draft, 80)} ») : envoie-la ou efface-la d'abord"}
    return t, None


PAIRF = os.path.join(STATE_DIR, "pair_token")


def pair_token():
    """Secret that remote devices (the tablet, over Tailscale) must present to send text to agents. Created once, 0600."""
    try:
        with open(PAIRF) as f:
            t = f.read().strip()
            if t:
                return t
    except OSError:
        pass
    t = secrets.token_urlsafe(24)
    os.makedirs(STATE_DIR, exist_ok=True)
    fd = os.open(PAIRF, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t)
    return t


PAIR = pair_token()


def paired(h):
    """The Mac itself (loopback) is trusted; any other client must carry the pairing cookie.
    Requests through the Cloudflare Tunnel also arrive on loopback (from cloudflared): they are never the Mac."""
    if h.client_address[0] in ("127.0.0.1", "::1") and not cfaccess.via_tunnel(h.headers):
        return True
    if cfaccess.via_tunnel(h.headers) and cfaccess.identity(h.headers):
        return True   # Cloudflare Access already proved who this is (passkey, allowed e-mail): stronger than the cookie
    m = re.search(r"(?:^|;\s*)mg_pair=([^;]+)", h.headers.get("Cookie") or "")
    return bool(m) and hmac.compare_digest(m.group(1), PAIR)


def hc_send(addr, text):
    """Type `text` into session `addr` with hc: the error message, or None when it went through."""
    if DEMO:
        demo_log(f"send {addr} {text}")
        return None
    r = subprocess.run([HC, "send", "--", addr, text], capture_output=True, text=True, timeout=60)
    if r.returncode:
        try:
            return json.loads(r.stdout)["error"]["message"]
        except Exception:
            return (r.stdout or r.stderr).strip()[:200] or f"hc send a échoué ({r.returncode})"
    return None


def send_route(h, body):
    if not paired(h):
        return 200, "application/json", json.dumps({"error": "appareil non appairé : ouvre l'adresse d'appairage (scripts/pair-url.sh sur le Mac) sur cet appareil"}, ensure_ascii=False).encode()
    d = json.loads(body)
    addr, text = str(d.get("address", "")), str(d.get("text", ""))
    qs = [str(x) for x in d.get("questions") or []]
    with SEND_LOCK:
        t, err = send_check(addr, text, d.get("since_ms"))
        if err:
            return 200, "application/json", json.dumps(err, ensure_ascii=False).encode()
        err = hc_send(addr, text)
        if not err:
            SENT[addr] = t.get("status_ms")
        entry = {"ts": int(time.time() * 1000), "address": addr, "space": (t.get("labels") or {}).get("where"),
                 "text": text, "questions": qs}
        if err:
            entry["error"] = err   # logged too: a failed send may still have reached the terminal
        with LOCK:
            os.makedirs(os.path.dirname(SENTF), exist_ok=True)
            with open(SENTF, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    out = {"error": "envoi échoué : " + err} if err else {"ok": True}
    return 200, "application/json", json.dumps(out, ensure_ascii=False).encode()


# ---- extension points for optional modules (stats.py, oldherdr.py, daily.py ...) ----
ROUTES = {"GET": {}, "POST": {}}   # path -> fn(handler, body: str) -> (status, content_type, bytes)
AGENT_SOURCES = []                 # fn(terminals) -> [agent dict, same schema as build_state agents]
SNAPSHOT_HOOKS = []                # fn(terminals, agents) called on every build_state
LINKS = []                         # [(label, href)] shown in the page header


SNZLOG = os.path.join(os.path.dirname(MEM), "snooze_log.jsonl")


def log_snooze(addr, until):
    """Append-only history of session snoozes {ts, address, space, session, until|null}: stats.py subtracts
    snoozed periods from the waiting time. Best effort, never blocks the snooze itself."""
    try:
        space = sid = None
        for t in snapshot():
            if t["address"] == addr:
                space = (t.get("labels") or {}).get("where")
                pid = (t.get("foreground") or {}).get("pid")
                if pid:
                    with open(f"{CLAUDE}/sessions/{pid}.json") as f:
                        sid = json.load(f)["sessionId"]
        with open(SNZLOG, "a") as f:
            f.write(json.dumps({"ts": int(time.time() * 1000), "address": addr, "space": space,
                                "session": sid, "until": int(until) if until else None}, ensure_ascii=False) + "\n")
    except Exception as e:
        print("snooze log failed:", e, flush=True)


def snooze_route(h, body):
    d = json.loads(body)
    addr, until = d["address"], d.get("until_ms")
    log_snooze(addr, until)
    with LOCK:
        if until:
            SNZ[addr] = {"until": int(until)}
        else:
            SNZ.pop(addr, None)
        save_json(SNZF, SNZ)
    return 200, "application/json", b"{}"


def snooze_item_route(h, body):
    d = json.loads(body)
    addr, text, until = d["address"], str(d["text"]), d.get("until_ms")
    with LOCK:
        m = SNZI.setdefault(addr, {})
        if until:
            m[text] = int(until)
        else:
            m.pop(text, None)
        if not m:
            del SNZI[addr]
        save_json(SNZIF, SNZI)
    return 200, "application/json", b"{}"


def sections_route(h, body):
    """address -> {section, since_ms, q, todo, deadline}: the board's grouping, for other clients (the Herdr app sidebar mod)."""
    now_ms = int(time.time() * 1000)
    out = {}
    for a in build_state()["agents"]:
        q = a.get("q") or {}
        st = a["status"]
        mine = st == "error" or (st == "done" and (not a.get("q") or q.get("pending") or q.get("error")
                                                   or q.get("open") or q.get("todo")))
        z = a.get("snooze")
        sec = "snoozed" if z and z.get("until", 0) > now_ms else "deadline" if a.get("deadline") else "mine" if mine else "rest"
        out[a["address"]] = {"section": sec, "since_ms": a.get("since_ms") or 0, "q": len(q.get("open") or []),
                             "todo": len(q.get("todo") or []), "deadline": (a.get("deadline") or {}).get("date")}
    return 200, "application/json", json.dumps(out).encode()


ROUTES["GET"]["/api/sections"] = sections_route
ROUTES["POST"]["/api/snooze"] = snooze_route
ROUTES["POST"]["/api/snooze-item"] = snooze_item_route
ROUTES["POST"]["/api/send"] = send_route
ROUTES["POST"]["/api/resume"] = resume_route


def load_modules():
    # the demo loads only the new modules: the others have their own production paths, background tasks and `claude -p` calls
    for name in ("thread", "choose", "voice") if DEMO else ("stats", "oldherdr", "daily", "backup"):
        try:
            importlib.import_module(name).register(sys.modules[__name__])
            print("module loaded:", name, flush=True)
        except ModuleNotFoundError as e:
            if e.name != name:
                raise
        except Exception as e:
            print("module failed:", name, e, flush=True)


def host_ok(host):
    """Accept only the names this board is meant to be reached by. A web page cannot make a browser send a
    forged Host, so this also stops DNS-rebinding (evil.example resolving to 127.0.0.1)."""
    h = (host or "").rsplit(":", 1)[0] if not (host or "").startswith("[") else (host or "").split("]")[0] + "]"
    h = h.lower().strip("[]")
    if h in ("localhost", "::1"):
        return True
    if cfaccess.configured() and h == cfaccess.public_host():   # Cloudflare Tunnel name (Access token checked in guard)
        return True
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", h):
        a, b = int(h.split(".")[0]), int(h.split(".")[1])
        return a == 127 or (a == 100 and 64 <= b <= 127)   # loopback, Tailscale CGNAT range
    return "." not in h or h.endswith(".ts.net")           # single-label MagicDNS name, or <name>.<tailnet>.ts.net


class H(BaseHTTPRequestHandler):
    def guard(self):
        """True if the request may proceed. POSTs act on agents (send text, snooze...), so a cross-site page
        must never be able to trigger them: refuse a forged Host and any cross-origin / cross-site request."""
        origin, host = self.headers.get("Origin"), self.headers.get("Host")
        bad = not host_ok(host)
        if not bad and origin and origin != "null":
            bad = (origin.split("://", 1)[-1].lower() != (host or "").lower())
        if not bad and self.headers.get("Sec-Fetch-Site") == "cross-site":
            # a top-level GET navigation may come from another site (the Cloudflare Access login redirects back here):
            # GETs only read, and the other site cannot read the answer. Everything else cross-site is refused.
            nav = (self.command == "GET" and self.headers.get("Sec-Fetch-Mode") == "navigate"
                   and self.headers.get("Sec-Fetch-Dest") == "document")
            bad = not nav
        if not bad and origin == "null":
            bad = True
        if not bad and cfaccess.via_tunnel(self.headers) and not cfaccess.identity(self.headers):
            bad = True                                             # through Cloudflare: a valid Access token is mandatory
        if bad:
            self.send(403, "text/plain", b"forbidden")
        return not bad

    def log_message(self, fmt, *a):
        # spike: keep an access log so we can see who reaches the server
        try:
            fd = os.open(os.path.join(STATE_DIR, "access.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {self.headers.get('Cf-Connecting-Ip') or self.client_address[0]} {fmt % a} UA={self.headers.get('User-Agent','')[:80]}\n")
        except Exception:
            pass

    def send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.guard():
            return
        fn = ROUTES["POST"].get(self.path.split("?")[0])
        if fn:
            try:
                code, ct, body = fn(self, self.rfc_body(int(self.headers.get("Content-Length", "0"))))
                return self.send(code, ct, body)
            except Exception as e:
                return self.send(500, "application/json", json.dumps({"error": str(e)}).encode())
        if self.path == "/api/info":
            try:
                d = json.loads(self.rfc_body(int(self.headers.get("Content-Length", "0"))))
                return self.send(200, "application/json", json.dumps(info_for(d["address"], str(d["text"]), pid_of(d["address"]))).encode())
            except Exception as e:
                return self.send(400, "application/json", json.dumps({"error": str(e)}).encode())
        if self.path == "/api/dismiss":
            try:
                d = json.loads(self.rfc_body(int(self.headers.get("Content-Length", "0"))))
                addr, text, undo = d["address"], str(d["text"]), bool(d.get("undo"))
                with LOCK:
                    L = DISM.setdefault(addr, [])
                    if undo and text in L:
                        L.remove(text)
                    elif not undo and text not in L:
                        L.append(text)
                    if not L:
                        DISM.pop(addr, None)
                    save_dism()
                return self.send(200, "application/json", b"{}")
            except Exception as e:
                return self.send(400, "application/json", json.dumps({"error": str(e)}).encode())
        if self.path != "/api/deadline":
            return self.send(404, "text/plain", b"not found")
        try:
            n = int(self.headers.get("Content-Length", "0"))
            d = json.loads(self.rfc_body(n))
            addr, date, note = d["address"], d.get("date") or "", (d.get("note") or "")[:200]
            with LOCK:
                if date:
                    time.strptime(date, "%Y-%m-%d")
                    DL[addr] = {"date": date, "note": note}
                else:
                    DL.pop(addr, None)
                save_dl()
            self.send(200, "application/json", b"{}")
        except Exception as e:
            self.send(400, "application/json", json.dumps({"error": str(e)}).encode())

    def rfc_body(self, n):
        return self.rfile.read(n).decode()

    def do_GET(self):
        if not self.guard():
            return
        q = parse_qs(urlparse(self.path).query)
        if q.get("pair") and hmac.compare_digest(q["pair"][0], PAIR):   # pairing link: remember this device, then go home
            self.send_response(302)
            secure = "; Secure" if cfaccess.via_tunnel(self.headers) else ""
            self.send_header("Set-Cookie", f"mg_pair={PAIR}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000{secure}")
            self.send_header("Location", "/")
            self.end_headers()
            return
        if self.path.split("?")[0] in ("/stats", "/daily", "/daily/history") and "embed=1" not in self.path:
            with open(os.path.join(HERE, "index.html"), "rb") as f:   # the shell reopens the page in its overlay (music keeps playing)
                return self.send(200, "text/html; charset=utf-8", f.read())
        fn = ROUTES["GET"].get(self.path.split("?")[0])
        if fn:
            try:
                code, ct, body = fn(self, "")
                return self.send(code, ct, body)
            except Exception as e:
                return self.send(500, "application/json", json.dumps({"error": str(e)}).encode())
        if self.path.startswith("/api/state"):
            try:
                self.send(200, "application/json", json.dumps(build_state()).encode())
            except Exception as e:  # spike: report, keep serving
                self.send(500, "application/json", json.dumps({"error": str(e)}).encode())
        elif self.path.split("?")[0] in ("/manifest.webmanifest", "/favicon.ico", "/apple-touch-icon.png") \
                or self.path.startswith("/assets/"):
            p = self.path.split("?")[0]
            if p == "/manifest.webmanifest":
                m = {"name": "Miniguet", "short_name": "Miniguet", "start_url": "/", "display": "standalone",
                     "background_color": "#0f1115", "theme_color": "#0f1115",
                     "icons": [{"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
                               {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
                               {"src": "/assets/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
                return self.send(200, "application/manifest+json", json.dumps(m).encode())
            root = os.path.realpath(os.path.join(HERE, "assets"))
            rel = unquote(p[len("/assets/"):])
            f = os.path.realpath(os.path.join(root, rel))   # sub-folders allowed, but never out of assets/ (.., %2e%2e, symlinks)
            ct = {"png": "image/png", "ico": "image/x-icon", "svg": "image/svg+xml", "js": "text/javascript",
                  "css": "text/css; charset=utf-8", "mp3": "audio/mpeg"}.get(f.rsplit(".", 1)[-1])
            if ct and "\0" not in rel and f.startswith(root + os.sep) and os.path.isfile(f):
                with open(f, "rb") as fh:
                    data = fh.read()
                rg = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
                if rg and (rg.group(1) or rg.group(2)):   # audio elements ask for byte ranges (seek, loop)
                    a = int(rg.group(1)) if rg.group(1) else max(len(data) - int(rg.group(2)), 0)
                    b = min(int(rg.group(2)), len(data) - 1) if rg.group(1) and rg.group(2) else len(data) - 1
                    if a > b:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{len(data)}")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Type", ct)
                    self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
                    self.send_header("Content-Length", str(b - a + 1))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    return self.wfile.write(data[a:b + 1])
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store" if ct != "audio/mpeg" else "max-age=86400")
                self.end_headers()
                return self.wfile.write(data)
            self.send(404, "text/plain", b"not found")
        elif self.path.split("?")[0] == "/classic" and os.path.isfile(os.path.join(HERE, "index-classic.html")):
            with open(os.path.join(HERE, "index-classic.html"), "rb") as f:
                self.send(200, "text/html; charset=utf-8", f.read())
        elif self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self.send(200, "text/html; charset=utf-8", f.read())
        else:
            self.send(404, "text/plain", b"not found")


TS_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def serve(host, port):
    ThreadingHTTPServer((host, port), H).serve_forever()


def serve_tailscale(port):
    """Bind to the Tailscale address only; it may not exist yet at boot, so retry."""
    warned = False
    while True:
        try:
            ip = None
            if os.path.exists(TS_CLI):   # ask Tailscale: another VPN may also use the 100.64/10 range
                r = subprocess.run([TS_CLI, "ip", "-4"], capture_output=True, text=True, timeout=10)
                m = re.search(r"^(100\.\d+\.\d+\.\d+)$", r.stdout, re.M)   # the GUI may print an error instead
                ip = m.group(1) if r.returncode == 0 and m else None
            if not ip:
                out = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True, timeout=10).stdout
                m = re.search(r"inet (100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+) ", out)  # CGNAT range Tailscale uses
                if not m:
                    raise RuntimeError("no tailscale interface yet")
                ip = m.group(1)
            print(f"herdr-board on http://{ip}:{port} (tailscale)", flush=True)
            return serve(ip, port)
        except Exception as e:
            if not warned:                                   # once: without Tailscale this would fill the log
                print("tailscale not ready (will keep retrying):", e, flush=True)
                warned = True
            time.sleep(10)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", action="append", help="repeatable; 'tailscale' = this Mac's Tailscale address")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--allow-lan", action="store_true", help="allow --host 0.0.0.0 (the board has no password: not recommended)")
    a = ap.parse_args()
    if not a.allow_lan and any(h in ("0.0.0.0", "::", "") for h in (a.host or [])):
        sys.exit("refusing to listen on all interfaces: the board has no password. Use --host 127.0.0.1 --host tailscale (or --allow-lan).")
    load_modules()
    hosts = a.host or ["127.0.0.1"]
    for h in hosts:
        if h == "tailscale":
            threading.Thread(target=serve_tailscale, args=(a.port,), daemon=True).start()
        else:
            print(f"herdr-board on http://{h}:{a.port}", flush=True)
            threading.Thread(target=serve, args=(h, a.port), daemon=True).start()
    while True:
        time.sleep(3600)
