"""Statistiques de jonglage : présence, conversation directe, attente, travail des agents, jetons et coût.

Source : les journaux Claude Code (~/.claude/projects/*/*.jsonl et */<sessionId>/subagents/*.jsonl),
sessions vivantes ET fermées. On ne garde que horodatages, rôles, ids et compteurs de jetons, jamais le
contenu des messages. Ce sont des approximations tirées des journaux, pas du temps d'écran réel.

Conventions (reprises par la page /stats) :
  message humain   type "user" typé par l'utilisateur. Écartés (voir _skip_reason, comptes dans le rapport) :
                   sous-agents, retours d'outils, messages "méta" (retours de hooks, skills, images),
                   résumés de compactage, appels programmatiques (promptSource sdk/system), notifications de
                   tâches (origin autre que human), "[Request interrupted…]", "Stop hook feedback", "Base directory
                   for this skill", messages d'un autre agent (<hc from=…> ou "Assignment <id> Work only on…",
                   même collés dans un <pasted_content>), et les balises système : <bash-stdout/stderr>,
                   <local-command-*>, <command-name> (commandes locales /clear /model /mcp… : elles ne
                   s'adressent à aucun agent), <task-notification>, <system-reminder>…
                   Comptent comme humains : texte tapé, <pasted_content> (texte collé, un seul message), <bash-input>
                   (commande tapée avec "!") et <command-message> (commande slash qui lance un skill, ex. /github-review)
  sujet            nom du space Herdr de la session (mémorisé dans stats_names.json pour les spaces fermés),
                   sinon nom explicite de session, sinon titre auto du journal, sinon dossier + 8 car. de l'id.
                   Une session sans aucun message humain n'est jamais un sujet ; son travail est rattaché au nom
                   de son space Herdr s'il est connu, sinon à "Agents délégués"
  présence         tous les messages humains du jour, sessions confondues ; deux messages à moins de 15 min
                   sont dans le même bloc ; un bloc dure (dernier - premier message) + 2 min
  conversation     (clé JSON "actif_ms") écarts < 10 min entre messages consécutifs d'un même sujet, + 2 min par
  directe          série (suite de messages d'un sujet espacés de moins de 10 min) ; total du jour = union
  changement       deux messages humains consécutifs (tous sujets fusionnés) de sujets différents ;
                   rapide : < 5 min après le message précédent ; aller-retour : retour sur un sujet visité < 1 h avant
  attente          pour chaque session : dernier message texte de l'assistant d'un tour -> message humain
                   suivant, si l'écart < 4 h, et seulement la part entre 08:00 et 20:00 locales, moins les
                   périodes où la session était reportée (snooze_log.jsonl, voir _snoozed) ; ni la présence ni
                   le travail des agents ne sont touchés par les reports
  travail agents   pour chaque session (sous-agents inclus), somme des écarts < 15 min entre événements consécutifs
                   du journal (messages assistant, résultats d'outils) à l'intérieur d'un tour ; l'écart qui
                   précède un nouveau prompt n'est pas du travail. Les écarts de 15 min à 4 h dans un tour sont
                   des "pauses" (validation d'outil, processus de fond), comptées à part. Cumulé = somme des
                   sessions ("heures d'agents") ; réel = union des intervalles (au moins un agent travaillait)
  jetons / coût    un message API apparaît sur plusieurs lignes du journal : dédupliqué par message.id (ligne
                   la plus complète). Coût "équivalent API" au tarif public (PRICES, surchargeable par
                   ~/.local/state/herdr-board/prices.json), sans remises ; modèle inconnu ou mode rapide :
                   jetons comptés, coût signalé "non chiffré", jamais 0 silencieux
  jour             00:00-24:00 dans le fuseau local de la machine (changements d'heure gérés par mktime)

BUSY_SOURCES (globales à toutes les sessions) : liste de fonctions fn(start_ms, end_ms) -> [(debut_ms, fin_ms)] (réunions du calendrier, plus
tard). Leurs intervalles sont retirés de la conversation directe, de la présence et de l'attente (pas du
travail des agents ni du coût). Vide aujourd'hui.

window_stats(start_ms, end_ms) -> dict, mêmes mesures sur une fenêtre quelconque :
  {"debut_ms", "fin_ms",
   "messages": int, "sujets": int,                       # messages humains ; sujets distincts avec un message
   "changements": int, "rapides": int, "allers_retours": int,
   "actif_ms": int,                                      # conversation directe
   "presence_ms": int, "blocs": [{"debut_ms", "fin_ms", "messages"}],   # fin_ms = dernier message du bloc
   "attente_ms": int, "attente_reelle_ms": int,          # cumulée (somme des sessions) / réelle (union)
   "travail_ms": int, "travail_reel_ms": int, "pauses_ms": int,        # agents : cumulé / union / pauses
   "cout_usd": float,                                    # équivalent API, hors messages non chiffrés
   "jetons": {"entree", "sortie", "cache_lecture", "cache_ecriture"},
   "par_modele": [{"modele", "messages", "jetons": {...}, "cout_usd", "non_chiffres": int}],
   "non_chiffres": {"messages": int, "modeles": {modele: n}, "rapide": int},
   "serie_max": {"ms", "sujet", "debut_ms"} | None,      # plus longue série sans changement de contexte
   "par_sujet": [{"sujet", "messages", "actif_ms", "attente_ms", "travail_ms", "pauses_ms", "cout_usd", "series",
                  "premier_ms", "dernier_ms"}],          # trié par conversation directe puis travail ; premier/dernier = None sans message
   "series": [{"debut_ms", "fin_ms", "sujet", "messages"}]}   # chronologique : début de chaque série de travail
Le premier message de la fenêtre n'a pas de précédent : il ne compte pas comme changement.
Les journaux ne sont lus que par refresh() (thread de fond, toutes les 30 s) ; window_stats lit le cache.
"""
import bisect, calendar, datetime, glob, json, os, re, sys, threading, time
from urllib.parse import parse_qs, urlparse

CLAUDE = os.path.expanduser("~/.claude")
STATE = os.path.expanduser("~/.local/state/herdr-board")
NAMES_FILE = f"{STATE}/stats_names.json"
PRICES_FILE = f"{STATE}/prices.json"
SNOOZE_LOG = os.environ.get("HERDR_BOARD_SNOOZE_LOG", f"{STATE}/snooze_log.jsonl")   # écrit par server.py, lecture seule ici
GAP = 10 * 60_000        # écart max entre deux messages d'une même série
TAIL = 2 * 60_000        # ajouté à chaque série / bloc de présence
PRES_GAP = 15 * 60_000   # écart max entre deux messages d'un même bloc de présence
WORK_GAP = 15 * 60_000   # écart max entre deux événements pour compter comme du travail d'agent
FAST = 5 * 60_000
BACK = 60 * 60_000
MAX_WAIT = 4 * 3600_000
BIZ = (8, 20)
DEFAULT_DAYS, MAX_DAYS = 14, 60
DELEGATED = "Agents délégués"

# USD par million de jetons. Source : https://platform.claude.com/docs/en/about-claude/pricing (relevé le 2026-11-05).
# in = entrée, w5 / w1h = écriture de cache 5 min / 1 h, r = lecture de cache, out = sortie.
# "au_dela" : autre tarif quand l'invite (entrée + lecture + écriture de cache) dépasse "tokens".
def _p(i, w5, w1h, r, out, **kw):
    return {"in": i, "w5": w5, "w1h": w1h, "r": r, "out": out, **kw}
PRICES = {
    "source": "https://platform.claude.com/docs/en/about-claude/pricing", "date": "2026-11-05",
    "modeles": {
        "claude-fable-5-1": _p(10, 12.5, 20, 0.25, 50), "claude-fable-5": _p(10, 12.5, 20, 1, 50),
        "claude-opus-5-5": _p(4, 5, 8, 0.20, 20),
        **{f"claude-opus-{v}": _p(5, 6.25, 10, 0.50, 25) for v in ("5", "4-8", "4-7", "4-6", "4-5")},
        "claude-sonnet-5-5": _p(2, 2.5, 4, 0.10, 10), "claude-sonnet-5": _p(2, 2.5, 4, 0.20, 10),
        "claude-sonnet-4-6": _p(3, 3.75, 6, 0.30, 15), "claude-sonnet-4-5": _p(3, 3.75, 6, 0.30, 15),
        "claude-haiku-5-5": _p(0.10, 0.125, 0.20, 0.01, 0.50, au_dela=_p(0.50, 0.625, 1, 0.05, 2.50, tokens=100_000)),
        "claude-haiku-4-5": _p(1, 1.25, 2, 0.10, 5),
    }}

BUSY_SOURCES = []        # fn(start_ms, end_ms) -> [(debut_ms, fin_ms)]

_LOCK = threading.Lock()
_FILES = {}              # path -> (mtime, size, meta) ; meta = {"ev", "all", "usage", "title", "cwd"} (voir parse_file)
_NAMES = {}              # sid -> nom de sujet (space Herdr / nom explicite), persisté
_ALL = {"sig": None}     # données fusionnées pour la dernière signature de fichiers
_PRICES = {"mtime": None, "val": PRICES}
_READY = threading.Event()
_RESP = {}               # (days, sig, date, nb busy) -> réponse

_DEC = json.JSONDecoder()
_MID = re.compile(r'"id":"([^"]+)"')
_MOD = re.compile(r'"model":"([^"]*)"')
_UUID = re.compile(r'"uuid":"([^"]+)"')
_DAY = {}
_TAG = re.compile(r"<([A-Za-z_-]+)")
_AGENT = re.compile(r'<hc from=|Assignment [0-9a-f]{12,}\s+Work only on the assignment')
_SNZ = {"key": None, "val": {}}


def _ms(iso):
    """'2026-11-05T07:41:20.872Z' -> epoch ms (plus rapide que fromisoformat : appelé sur chaque ligne)."""
    if iso[-1] != "Z":
        return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)
    d = _DAY.get(iso[:10])
    if d is None:
        d = _DAY[iso[:10]] = calendar.timegm((int(iso[:4]), int(iso[5:7]), int(iso[8:10]), 0, 0, 0)) * 1000
    ms = int(iso[20:23].ljust(3, "0")) if iso[19] == "." else 0
    return d + int(iso[11:13]) * 3_600_000 + int(iso[14:16]) * 60_000 + int(iso[17:19]) * 1000 + ms


def _human_text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _skip_reason(line):
    """Raison pour laquelle une ligne "user" n'est pas un prompt (ni humain, ni automatique), d'après le texte brut."""
    if '"isSidechain":true' in line:
        return "sous-agent"
    if '"type":"tool_result"' in line:
        return "retour d'outil"
    if '"isMeta":true' in line:
        return "méta (retour de hook, skill, image…)"


def _not_human(o, t):
    """Raison pour laquelle un prompt n'est pas un message humain (None = c'est un message humain)."""
    kind = (o.get("origin") or {}).get("kind")
    if o.get("isCompactSummary"):
        return "résumé de compactage"
    if o.get("promptSource") in ("sdk", "system"):
        return "appel programmatique"
    if kind not in (None, "human"):
        return f"origine {kind}"
    if not t:
        return "sans texte"
    if t.startswith("Stop hook feedback"):
        return "retour de hook"
    if t.startswith("Base directory for this skill"):
        return "skill"
    if t.startswith("[Request interrupted"):
        return "interruption"
    tag = _TAG.match(t)
    if tag:
        tag = tag.group(1)
        if tag == "pasted_content":   # texte collé : humain, sauf message d'un autre agent (herdr-delegate, hc)
            return "message d'un autre agent" if _AGENT.search(t[:400]) else None
        if tag not in ("bash-input", "command-message"):
            return f"balise <{tag}>"
    elif "<system-reminder>" in t[:40]:
        return "balise <system-reminder>"


def parse_file(path):
    """-> {"ev": [(ms, 'h'|'a', sid, uuid)]  messages humains et messages texte de l'assistant,
           "all": [(ms, sid, boundary)]      tous les événements user/assistant (sous-agents inclus) ; boundary = nouveau prompt,
           "usage": [(ms, sid, modèle, entrée, sortie, cache_lecture, écr5m, écr1h, speed)]  dédupliqué par message.id,
           "title": {sid: ai-title}, "cwd": {sid: dossier}}"""
    ev, allev, best, title, cwd = [], [], {}, {}, {}
    with open(path, errors="replace") as f:
        for line in f:
            asst = '"type":"assistant"' in line
            # les enregistrements annexes commencent par {"type": (api-request-blob embarque des messages entiers)
            if line.startswith('{"type":"') or (not asst and '"type":"user"' not in line):
                if line.startswith('{"type":"ai-title"'):
                    try:
                        o = json.loads(line)
                        title[o["sessionId"]] = o["aiTitle"]
                    except (ValueError, KeyError):
                        pass
                continue
            i, j = line.find('"timestamp":"'), line.rfind('"sessionId":"')
            if i < 0 or j < 0:
                continue
            ms, sid = _ms(line[i + 13:line.index('"', i + 13)]), line[j + 13:j + 49]
            if asst:
                allev.append((ms, sid, False))
                if '"isSidechain":true' not in line and '"type":"text"' in line:   # fin de tour ; pas de json : lignes énormes
                    u = _UUID.search(line)
                    ev.append((ms, "a", sid, u.group(1) if u else None))
                _usage(line, ms, sid, best)
                continue
            boundary = _skip_reason(line) is None
            allev.append((ms, sid, boundary))
            if not boundary:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if _not_human(o, _human_text((o.get("message") or {}).get("content")).strip()) is None:
                if o.get("cwd"):
                    cwd.setdefault(sid, o["cwd"])
                ev.append((ms, "h", sid, o.get("uuid")))
    return {"ev": ev, "all": allev, "usage": list(best.values()), "title": title, "cwd": cwd}


def _usage(line, ms, sid, best):
    i = line.find('"message":{')
    j = line.find('"usage":{', i)
    if i < 0 or j < 0:
        return
    head = line[i:i + 500]
    mid, mod = _MID.search(head), _MOD.search(head)
    if not (mid and mod) or mod.group(1) == "<synthetic>":
        return
    u, _ = _DEC.raw_decode(line, j + 8)
    cc = u.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens") or 0, cc.get("ephemeral_1h_input_tokens") or 0
    w5 += max(0, (u.get("cache_creation_input_tokens") or 0) - w5 - w1)   # sans détail : tout en 5 min
    rec = (ms, sid, mod.group(1), u.get("input_tokens") or 0, u.get("output_tokens") or 0,
           u.get("cache_read_input_tokens") or 0, w5, w1, u.get("speed"))
    old = best.get(mid.group(1))
    if old is None or (rec[4], sum(rec[3:8])) > (old[4], sum(old[3:8])):
        best[mid.group(1)] = rec


def refresh(days=DEFAULT_DAYS):
    """Parse les journaux (et ceux des sous-agents) modifiés dans les N derniers jours (cache par chemin, mtime, taille)."""
    lim = time.time() - (days + 1) * 86400
    for p in glob.glob(f"{CLAUDE}/projects/*/*.jsonl") + glob.glob(f"{CLAUDE}/projects/*/*/subagents/*.jsonl"):
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_mtime < lim:
            continue
        c = _FILES.get(p)
        if c and c[0] == st.st_mtime and c[1] == st.st_size:
            continue
        try:
            meta = parse_file(p)
        except OSError:
            continue
        with _LOCK:
            _FILES[p] = (st.st_mtime, st.st_size, meta)


def _snoozed():
    """{sid: [(debut_ms, fin_ms)]} périodes de report (snooze) lues dans le journal du serveur (une ligne JSON par action).
    Un report va de son événement à min(until, événement suivant de la même adresse ou session) ; until null = annulation.
    Lignes sans session : ignorées (l'adresse et le nom de space ne suffisent pas à retrouver la session de façon fiable)."""
    try:
        st = os.stat(SNOOZE_LOG)
    except OSError:
        return {}
    key = (SNOOZE_LOG, st.st_mtime, st.st_size)
    if _SNZ["key"] != key:
        ev = []
        with open(SNOOZE_LOG) as f:
            for line in f:
                try:
                    o = json.loads(line)
                    ev.append((int(o["ts"]), o.get("address"), o.get("session"), o.get("until")))
                except (ValueError, KeyError, TypeError):
                    pass
        ev.sort(key=lambda e: e[0])
        out = {}
        for i, (ts, addr, sid, until) in enumerate(ev):
            if not sid or not until:
                continue
            nxt = next((e[0] for e in ev[i + 1:] if e[1] == addr or e[2] == sid), until)
            if min(until, nxt) > ts:
                out.setdefault(sid, []).append((ts, min(until, nxt)))
        _SNZ.update(key=key, val={k: [tuple(x) for x in _union(v)] for k, v in out.items()})
    return _SNZ["val"]


def _prices():
    """Tarifs par défaut, surchargés par prices.json (même forme que PRICES ; modèles fusionnés un à un)."""
    try:
        mt = os.stat(PRICES_FILE).st_mtime
    except OSError:
        mt = None
    if _PRICES["mtime"] != mt or _PRICES["val"] is None:
        val = {**PRICES, "modeles": dict(PRICES["modeles"])}
        if mt:
            try:
                with open(PRICES_FILE) as f:
                    o = json.load(f)
                val.update({k: o[k] for k in ("source", "date") if k in o}, fichier=True)
                val["modeles"].update(o.get("modeles", {}))
            except Exception as e:
                print("prices.json ignoré:", e, flush=True)
        _PRICES.update(mtime=mt, val=val)
    return _PRICES["val"]


def _cost(rec):
    """USD d'un message, ou None si non chiffrable (modèle inconnu, mode rapide)."""
    _, _, model, i, o, r, w5, w1, speed = rec
    if speed == "fast":
        return None
    P = _prices()["modeles"]
    keys = [k for k in P if model == k or model.startswith(k + "-") or model.startswith(k + "[")]
    if not keys:
        return None
    p = P[max(keys, key=len)]
    if p.get("au_dela") and i + r + w5 + w1 > p["au_dela"]["tokens"]:
        p = p["au_dela"]
    return (i * p["in"] + o * p["out"] + r * p["r"] + w5 * p["w5"] + w1 * p["w1h"]) / 1e6


def _data():
    """Humains, attentes, travail des agents et jetons de toutes les sessions en cache ; recalculé si un journal a changé."""
    with _LOCK:
        files = dict(_FILES)
    _prices()
    sig = hash((tuple(sorted((p, v[0], v[1]) for p, v in files.items())), _PRICES["mtime"]))
    global _ALL
    if _ALL["sig"] == sig:
        return _ALL
    seen, by_sid, ev_all, usage, title, cwd = set(), {}, {}, {}, {}, {}
    for v in files.values():
        m = v[2]
        title.update(m["title"])
        cwd.update(m["cwd"])
        for ts, role, sid, u in m["ev"]:
            if u:   # une session reprise peut recopier des messages d'un autre journal
                if u in seen:
                    continue
                seen.add(u)
            by_sid.setdefault(sid, []).append((ts, role))
        for ts, sid, boundary in m["all"]:
            ev_all.setdefault(sid, []).append((ts, boundary))
        for r in m["usage"]:   # le même message peut figurer dans plusieurs journaux (sous-agents)
            k = (r[0], r[1], r[2], r[3:8])
            usage[k] = r
    humans, waits = [], []
    for sid, evs in by_sid.items():
        evs.sort()
        last_a = None
        for ts, role in evs:
            if role == "h":
                humans.append((ts, sid))
                if last_a is not None and 0 < ts - last_a < MAX_WAIT:
                    waits.append((last_a, ts, sid))
                last_a = None
            else:
                last_a = ts
    humans.sort()
    work, pauses = [], []   # intervalles de travail d'agent (chaînes d'événements < WORK_GAP fusionnées) et pauses
    for sid, evs in ev_all.items():
        evs.sort()
        prev = cur = None
        for ts, boundary in evs:
            if prev is not None and ts > prev and not boundary:
                if ts - prev < WORK_GAP:
                    if cur and cur[1] == prev:
                        cur[1] = ts
                    else:
                        cur = [prev, ts, sid]
                        work.append(cur)
                elif ts - prev < MAX_WAIT:
                    pauses.append((prev, ts, sid))
            prev = ts
    work = sorted(map(tuple, work))
    costs = sorted(((r, _cost(r)) for r in usage.values()), key=lambda x: x[0][0])
    _ALL = dict(sig=sig, humans=humans, htimes=[h[0] for h in humans], human_sids={h[1] for h in humans},
                waits=waits, work=work, pauses=pauses, usage=costs, utimes=[c[0][0] for c in costs],
                title=title, cwd=cwd)  # remplacé d'un bloc : lecteurs concurrents
    return _ALL


def topic(sid, d):
    n = _NAMES.get(sid) or d["title"].get(sid)
    return n or f"{os.path.basename(d['cwd'].get(sid, '')) or '?'} · {sid[:8]}"


def work_topic(sid, d):
    """Sujet d'un travail d'agent : celui de la session, ou pour une session sans message humain son space Herdr."""
    return topic(sid, d) if sid in d["human_sids"] else (_NAMES.get(sid) or DELEGATED)


# ---- intervalles (ms) ----
def _union(iv):
    out = []
    for a, b in sorted(iv):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _clip(iv, lo, hi):
    return [(max(a, lo), min(b, hi)) for a, b in iv if min(b, hi) > max(a, lo)]


def _inter(iv, other):
    return [(max(a, c), min(b, e)) for a, b in iv for c, e in other if min(b, e) > max(a, c)]


def _minus(iv, busy):
    out = []
    for a, b in iv:
        cur = a
        for c, e in busy:
            if e <= cur or c >= b:
                continue
            if c > cur:
                out.append((cur, c))
            cur = max(cur, e)
        if cur < b:
            out.append((cur, b))
    return out


def _len(iv):
    return sum(b - a for a, b in _union(iv))


def _local_ms(d, h=0):
    return int(datetime.datetime(d.year, d.month, d.day, h).timestamp() * 1000)


def day_bounds(d):
    return _local_ms(d), _local_ms(d + datetime.timedelta(days=1))


def _biz(start, end):
    d = datetime.datetime.fromtimestamp(start / 1000).date()
    out = []
    while _local_ms(d) < end:
        out.append((_local_ms(d, BIZ[0]), _local_ms(d, BIZ[1])))
        d += datetime.timedelta(days=1)
    return out


def _busy(start, end):
    iv = []
    for fn in BUSY_SOURCES:
        try:
            iv += [(int(a), int(b)) for a, b in fn(start, end)]
        except Exception as e:
            print("busy source failed:", fn, e, flush=True)
    return [tuple(x) for x in _union(iv)]


def _new_topic(tp, first=None, last=None, n=0):
    return {"sujet": tp, "messages": n, "series": 0, "premier_ms": first, "dernier_ms": last, "_iv": [],
            "attente_ms": 0, "travail_ms": 0, "pauses_ms": 0, "cout_usd": 0.0}


def _zero():
    return {"entree": 0, "sortie": 0, "cache_lecture": 0, "cache_ecriture": 0}


def window_stats(start_ms, end_ms):
    d = _data()
    lo, hi = bisect.bisect_left(d["htimes"], start_ms), bisect.bisect_left(d["htimes"], end_ms)
    seq = [(ts, topic(sid, d)) for ts, sid in d["humans"][lo:hi]]
    busy = _busy(start_ms, end_ms)

    # changements de contexte, sur le flux fusionné
    sw = fast = back = 0
    last_seen, prev = {}, None
    for ts, tp in seq:
        if prev and tp != prev[1]:
            sw += 1
            fast += ts - prev[0] < FAST
            back += tp in last_seen and ts - last_seen[tp] <= BACK
        last_seen[tp] = ts
        prev = (ts, tp)

    # séries et temps actif, dans le flux propre à chaque sujet
    by_tp = {}
    for ts, tp in seq:
        by_tp.setdefault(tp, []).append(ts)
    topics = {tp: _new_topic(tp, t[0], t[-1], len(t)) for tp, t in by_tp.items()}
    series = []
    for tp, ts_l in by_tp.items():
        s = 0
        for i, t in enumerate(ts_l):
            if i + 1 == len(ts_l) or ts_l[i + 1] - t >= GAP:
                topics[tp]["_iv"].append((ts_l[s], t + TAIL))
                topics[tp]["series"] += 1
                series.append({"debut_ms": ts_l[s], "fin_ms": t, "sujet": tp, "messages": i - s + 1})
                s = i + 1
            else:
                topics[tp]["_iv"].append((t, ts_l[i + 1]))

    # présence : blocs de messages (tous sujets) espacés de moins de PRES_GAP
    blocs, s = [], 0
    for i, (ts, _) in enumerate(seq):
        if i + 1 == len(seq) or seq[i + 1][0] - ts >= PRES_GAP:
            blocs.append({"debut_ms": seq[s][0], "fin_ms": ts, "messages": i - s + 1})
            s = i + 1
    presence = _len(_minus(_clip([(b["debut_ms"], b["fin_ms"] + TAIL) for b in blocs], start_ms, end_ms), busy))

    # plus longue série sans changement de contexte, dans le flux fusionné
    best, s = None, 0
    for i, (ts, tp) in enumerate(seq):
        if i + 1 == len(seq) or seq[i + 1][1] != tp or seq[i + 1][0] - ts >= GAP:
            ms = ts - seq[s][0] + TAIL
            if not best or ms > best["ms"]:
                best = {"ms": ms, "sujet": tp, "debut_ms": seq[s][0]}
            s = i + 1

    # attente : part ouvrée de chaque écart assistant -> humain, rattachée au sujet de la session
    biz, wait_iv, snz = _biz(start_ms, end_ms), [], _snoozed()
    for a, h, sid in d["waits"]:
        if h <= start_ms or a >= end_ms:
            continue
        iv = _minus(_minus(_inter(_clip([(a, h)], start_ms, end_ms), biz), busy), snz.get(sid, []))
        if iv:
            wait_iv += iv
            tp = topic(sid, d)
            topics.setdefault(tp, _new_topic(tp))["attente_ms"] += _len(iv)

    # travail des agents : cumulé par sujet, union au total
    work_iv = []
    for a, b, sid in d["work"][:bisect.bisect_left(d["work"], (end_ms,))]:
        if b > start_ms:
            a, b = max(a, start_ms), min(b, end_ms)
            work_iv.append((a, b))
            topics.setdefault(w := work_topic(sid, d), _new_topic(w))["travail_ms"] += b - a
    pauses = 0
    for a, b, sid in d["pauses"]:
        if b > start_ms and a < end_ms:
            n = min(b, end_ms) - max(a, start_ms)
            pauses += n
            topics.setdefault(w := work_topic(sid, d), _new_topic(w))["pauses_ms"] += n

    # jetons et coût équivalent API
    tok, cost, models, unpriced = _zero(), 0.0, {}, {"messages": 0, "modeles": {}, "rapide": 0}
    u0, u1 = bisect.bisect_left(d["utimes"], start_ms), bisect.bisect_left(d["utimes"], end_ms)
    for rec, c in d["usage"][u0:u1]:
        _, sid, model, i, o, r, w5, w1, speed = rec
        m = models.setdefault(model, {"modele": model, "messages": 0, "jetons": _zero(), "cout_usd": 0.0, "non_chiffres": 0})
        m["messages"] += 1
        for tgt in (tok, m["jetons"]):
            tgt["entree"] += i
            tgt["sortie"] += o
            tgt["cache_lecture"] += r
            tgt["cache_ecriture"] += w5 + w1
        if c is None:
            m["non_chiffres"] += 1
            unpriced["messages"] += 1
            if speed == "fast":
                unpriced["rapide"] += 1
            else:
                unpriced["modeles"][model] = unpriced["modeles"].get(model, 0) + 1
        else:
            m["cout_usd"] += c
            cost += c
            topics.setdefault(w := work_topic(sid, d), _new_topic(w))["cout_usd"] += c

    all_iv = []
    for t in topics.values():
        iv = _minus(_clip(t.pop("_iv"), start_ms, end_ms), busy)
        t["actif_ms"] = _len(iv)
        all_iv += iv
    return {
        "debut_ms": start_ms, "fin_ms": end_ms, "messages": len(seq), "sujets": len(by_tp),
        "changements": sw, "rapides": fast, "allers_retours": back,
        "actif_ms": _len(all_iv), "presence_ms": presence, "blocs": blocs,
        "attente_ms": sum(t["attente_ms"] for t in topics.values()),
        "attente_reelle_ms": _len(wait_iv),   # au moins un agent attendait (l'attente cumulée additionne les sessions)
        "travail_ms": sum(t["travail_ms"] for t in topics.values()), "travail_reel_ms": _len(work_iv), "pauses_ms": pauses,
        "cout_usd": cost, "jetons": tok, "non_chiffres": unpriced,
        "par_modele": sorted(models.values(), key=lambda m: -m["cout_usd"]),
        "serie_max": best,
        "par_sujet": sorted(topics.values(), key=lambda t: (-t["actif_ms"], -t["travail_ms"], -t["attente_ms"])),
        "series": sorted(series, key=lambda s: s["debut_ms"]),
    }


def _api_stats(n):
    n = max(1, min(n, MAX_DAYS))
    refresh(n)
    _snoozed()
    key = (n, _data()["sig"], datetime.date.today(), len(BUSY_SOURCES), tuple(getattr(f, "version", lambda: 0)() for f in BUSY_SOURCES), _SNZ["key"])
    if key in _RESP:
        return _RESP[key]
    jours = []
    for i in range(n - 1, -1, -1):
        day = datetime.date.today() - datetime.timedelta(days=i)
        w = window_stats(*day_bounds(day))
        w.pop("series")
        w["nb_blocs"] = len(w.pop("blocs"))
        w["date"] = day.isoformat()
        jours.append(w)
    subj, models, tok, unp = {}, {}, _zero(), {"messages": 0, "modeles": {}, "rapide": 0}
    for j in jours:
        for t in j["par_sujet"]:
            a = subj.setdefault(t["sujet"], {"sujet": t["sujet"], "messages": 0, "jours": 0, **{k: 0 for k in (
                "actif_ms", "attente_ms", "travail_ms", "pauses_ms", "cout_usd")}})
            for k in ("messages", "actif_ms", "attente_ms", "travail_ms", "pauses_ms", "cout_usd"):
                a[k] += t[k]
            a["jours"] += t["messages"] > 0
        for m in j["par_modele"]:
            a = models.setdefault(m["modele"], {"modele": m["modele"], "messages": 0, "jetons": _zero(), "cout_usd": 0.0, "non_chiffres": 0})
            a["messages"] += m["messages"]
            a["cout_usd"] += m["cout_usd"]
            a["non_chiffres"] += m["non_chiffres"]
            for k, v in m["jetons"].items():
                a["jetons"][k] += v
        for k, v in j["jetons"].items():
            tok[k] += v
        unp["messages"] += j["non_chiffres"]["messages"]
        unp["rapide"] += j["non_chiffres"]["rapide"]
        for m, c in j["non_chiffres"]["modeles"].items():
            unp["modeles"][m] = unp["modeles"].get(m, 0) + c
    P = _prices()
    res = {"now_ms": int(time.time() * 1000), "jours": jours,
           "totaux": {k: sum(j[k] for j in jours) for k in (
               "messages", "changements", "rapides", "allers_retours", "actif_ms", "presence_ms", "attente_ms",
               "attente_reelle_ms", "travail_ms", "travail_reel_ms", "pauses_ms", "cout_usd")}
                     | {"sujets": sum(1 for s in subj.values() if s["jours"]), "jetons": tok, "non_chiffres": unp,
                        "serie_max": max((j["serie_max"] for j in jours if j["serie_max"]), key=lambda s: s["ms"], default=None)},
           "par_sujet": sorted(subj.values(), key=lambda s: (-s["actif_ms"], -s["travail_ms"], -s["attente_ms"])),
           "par_modele": sorted(models.values(), key=lambda m: -m["cout_usd"]),
           "prix": {"source": P["source"], "date": P["date"], "fichier": bool(P.get("fichier")), "modeles": P["modeles"]}}
    if len(_RESP) > 4:
        _RESP.clear()
    _RESP[key] = res
    return res


# ---- noms de sujets (space Herdr) ----
def _load_names():
    try:
        with open(NAMES_FILE) as f:
            _NAMES.update(json.load(f))
    except Exception:
        pass


def update_names(srv):
    """sessionId -> nom du space Herdr, via pid -> ~/.claude/sessions/<pid>.json ; persisté pour les spaces fermés."""
    new = {}
    for p in glob.glob(f"{CLAUDE}/sessions/*.json"):
        try:
            with open(p) as f:
                o = json.load(f)
            if o.get("name") and o.get("nameSource") != "derived":   # "derived" = dossier + hasard : le titre du journal vaut mieux
                new[o["sessionId"]] = o["name"]
        except Exception:
            pass
    try:
        for t in srv.snapshot():
            pid = (t.get("foreground") or {}).get("pid")
            where = (t.get("labels") or {}).get("where")
            if not pid or not where:
                continue
            try:
                with open(f"{CLAUDE}/sessions/{pid}.json") as f:
                    new[json.load(f)["sessionId"]] = where.rpartition(" / ")[0] or where
            except Exception:
                pass
    except Exception as e:
        print("stats names: snapshot failed:", e, flush=True)
    if any(_NAMES.get(k) != v for k, v in new.items()):
        _NAMES.update(new)
        os.makedirs(os.path.dirname(NAMES_FILE), exist_ok=True)
        tmp = NAMES_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_NAMES, f, ensure_ascii=False)
        os.replace(tmp, NAMES_FILE)


def _worker(srv):
    while True:
        try:
            update_names(srv)
            refresh()
        except Exception as e:
            print("stats worker failed:", e, flush=True)
        _READY.set()
        time.sleep(30)


# ---- routes ----
def _json(o):
    return 200, "application/json", json.dumps(o, ensure_ascii=False).encode()


def register(srv):
    _load_names()

    def pending():   # premier calcul pas fini : la page réessaie
        return None if _READY.wait(4) else _json({"pending": True})

    def page(h, body):
        with open(os.path.join(srv.HERE, "stats.html"), "rb") as f:
            return 200, "text/html; charset=utf-8", f.read()

    def api(h, body):
        n = int((parse_qs(urlparse(h.path).query).get("days") or [DEFAULT_DAYS])[0])
        return pending() or _json(_api_stats(n))

    def summary(h, body):
        if (p := pending()):
            return p
        refresh()
        today = datetime.date.today()
        w = window_stats(*day_bounds(today))
        keys = ("attente_ms", "attente_reelle_ms", "changements", "sujets", "messages", "actif_ms", "presence_ms",
                "travail_ms", "travail_reel_ms", "cout_usd")
        return _json({"date": today.isoformat(), **{k: w[k] for k in keys}})

    srv.ROUTES["GET"]["/stats"] = page
    srv.ROUTES["GET"]["/api/stats"] = api
    srv.ROUTES["GET"]["/api/stats/summary"] = summary
    srv.LINKS.append(("Statistiques", "/stats"))
    threading.Thread(target=_worker, args=(srv,), daemon=True).start()
    try:   # meetings from Google Calendar (optional): subtracted through BUSY_SOURCES
        import gcal
        gcal.register(srv, sys.modules[__name__])
    except Exception as e:
        print("gcal not loaded:", e, flush=True)
