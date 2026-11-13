# Refonte de l'interface Miniguet — plan de réalisation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nouvelle page tablette (liste groupée par attente + conversation), approbation des demandes d'autorisation, réponses Oui/Non/texte/voix (Whisper local sur le M5).

**Architecture:** Trois nouveaux modules serveur à la manière de `daily.py` (`register(srv)` sur les points d'extension `ROUTES` / `SNAPSHOT_HOOKS`), chacun avec un cœur pur testable sans importer `server.py`. Une nouvelle `index.html` en modules JS sans build sous `assets/app/`, avec les web components `ui-sdk` copiés dans le repo. Un mode démo (`MINIGUET_DEMO`) sert des données d'exemple pour développer et tester l'interface.

**Tech Stack:** Python 3.9+ stdlib (`unittest`), HTML/CSS/JS modules, `@ui-sdk/web@0.1.0-beta.1` (build navigateur copié), `node --test` pour les fonctions JS pures (outil de dev seulement), Playwright (MCP) pour le navigateur, `whisper-cpp` + `ffmpeg` sur le M5.

**Spec:** `docs/superpowers/specs/2026-11-13-refonte-ui-design.md`

## Global Constraints

- Serveur : bibliothèque standard Python uniquement ; aucune dépendance installée côté page, aucun build.
- Aucun script ni feuille de style chargé depuis un autre domaine : tout est servi depuis `assets/`.
- `ui-sdk` figé en `0.1.0-beta.1`, copié dans `assets/ui-sdk/0.1.0-beta.1/` avec sa licence ; `@layer ui-sdk;` en tête de la feuille de style.
- Cibles tactiles ≥ 48 px ; boutons d'action principaux 56 px de haut ; espacement ≥ 8 px ; rien ne dépend du survol.
- Texte ≥ 16 px, boutons d'action 17 px gras ; contraste texte ≥ 4,5:1, bords / focus / fonds d'état ≥ 3:1, en thème sombre (défaut) et clair.
- Couleurs de groupe (sombre) : orange `#ffb020`, bleu `#5aa9ff`, rouge `#ff5d5d`, vert `#2ecc71`.
- Textes de l'interface en français, au ton actuel ; texte des agents affiché en texte brut (jamais interprété comme HTML).
- Rien n'est envoyé à un terminal sans avoir été affiché ; une transcription vocale n'est jamais envoyée automatiquement.
- Toute action qui écrit dans un terminal (`/api/send`, `/api/approve`) et `/api/transcribe` exigent `srv.paired(h)`.
- Toutes les fonctions de l'ancienne page restent disponibles (liste dans la tâche 9).
- Déploiement : commit + push, puis `scripts/deploy.sh kevin@100.75.247.49`.

## Review Focus

1. **Double appui sur Approuver** : une seule touche part. → test `test_approve_twice_sends_once` (tâche 3).
2. **La demande a changé entre l'affichage et l'appui** (Claude enchaîne une autre autorisation) : refus explicite, rien n'est tapé. → test `test_approve_refuses_changed_screen` (tâche 3).
3. **Message d'agent long, avec Markdown, `<balises>` ou blocs de code** : affiché en texte brut, tronqué à 600 caractères avec « Voir tout ». → tests `test_last_exchange_truncates` (tâche 2) et `escapes agent html` (tâche 6).
4. **La liste se rafraîchit pendant qu'on répond** (polling toutes les 2 s, la session change de groupe ou un autre arrive) : la session ouverte reste ouverte, le texte saisi et les Oui/Non cochés sont conservés. → test navigateur `keeps selection and draft across refresh` (tâche 6).
5. **Audio trop long, trop gros, Whisper absent ou planté** : message clair en moins de 60 s, aucun fichier laissé dans `scratch/`. → tests `test_transcribe_rejects_too_big`, `test_transcribe_timeout_cleans_up`, `test_transcribe_missing_binary` (tâche 4).

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `perm.py` (créé) | Lecture du menu d'autorisation de Claude Code sur l'écran ; hash d'écran ; vérification avant approbation. Pur. |
| `approve.py` (créé) | Module : annote les sessions bloquées (`kind`, `perm`) et route `POST /api/approve`. |
| `thread.py` (créé) | Module : `GET /api/thread` (dernier message de toi / de l'agent). Cœur pur. |
| `voice.py` (créé) | Module : `GET /api/voice`, `POST /api/transcribe` (ffmpeg + whisper-cli). Cœur pur. |
| `server.py` (modifié) | Charge les modules ; routes brutes `ROUTES["POST_RAW"]` ; `kind` dans l'état ; `/classic` ; mode démo. |
| `demo/` (créé) | `terminals.json`, `screens/<adresse>.txt`, `transcripts/<adresse>.jsonl` pour le mode démo et les tests. |
| `tests/` (créé) | `test_perm.py`, `test_approve.py`, `test_thread.py`, `test_voice.py`, `js/*.test.mjs`. |
| `index-classic.html` (créé) | Copie de l'ancienne `index.html`, servie à `/classic`. |
| `index.html` (réécrit) | Coquille de la page : en-tête, liste, panneau, dialogues. |
| `assets/app/*.js` (créés) | `api.js`, `groups.js`, `list.js`, `detail.js`, `reply.js`, `voice.js`, `rafale.js`, `desk.js`, `app.js`. |
| `assets/app/style.css` (créé) | Jetons de thème, mise en page, composants. |
| `assets/ui-sdk/0.1.0-beta.1/` (créé) | Build navigateur de `@ui-sdk/web` + `LICENSE`. |
| `README.md` (modifié) | Whisper, mode démo, `/classic`, tests. |

---

### Task 1: Lecture du menu d'autorisation (`perm.py`) et vérification sur une vraie session

**Files:**
- Create: `perm.py`, `tests/test_perm.py`, `demo/screens/` (exemples relevés)

**Interfaces:**
- Produces:
  - `parse_permission(lines: list[str]) -> dict | None` → `{"question": str, "detail": str, "options": [{"key": "1", "label": "Yes", "role": "approve"|"always"|"deny"}]}` ou `None` si aucun menu reconnu.
  - `screen_hash(lines: list[str]) -> str` : SHA-1 hex des 40 dernières lignes non vides, espaces de fin retirés.
  - `check_approval(state: str, kind: str|None, lines: list[str], key: str, expected_hash: str) -> tuple[dict|None, str|None]` → `(option, None)` ou `(None, message d'erreur en français)`.

- [ ] **Step 1: Relever un vrai écran.** Sur le M5, lancer dans un terminal herdr `claude` et lui demander `lance la commande: ls /tmp` sans autorisation préalable. Pendant que le menu est affiché : `hc ls --json` doit montrer pour ce terminal `status.state == "blocked"` et `status.kind == "permission"` ; `hc read <adresse> > demo/screens/perm-bash.txt`. Faire de même pour une écriture de fichier (`perm-write.txt`, menu à 3 options) et garder un écran ordinaire sans menu (`plain.txt`). Si herdr ne signale pas `blocked/permission`, s'arrêter et le signaler (le reste de la tâche 3 en dépend).

- [ ] **Step 2: Écrire les tests** dans `tests/test_perm.py` (`unittest`, fichiers lus depuis `demo/screens/`) :

```python
def test_parses_bash_menu(self):
    p = parse_permission(load("perm-bash.txt"))
    self.assertIn("ls /tmp", p["detail"])
    self.assertEqual([o["role"] for o in p["options"]][0], "approve")
    self.assertEqual(p["options"][-1]["role"], "deny")
    self.assertTrue(all(o["key"].isdigit() for o in p["options"]))

def test_parses_three_options_with_always(self):
    roles = [o["role"] for o in parse_permission(load("perm-write.txt"))["options"]]
    self.assertEqual(roles, ["approve", "always", "deny"])

def test_plain_screen_has_no_menu(self):
    self.assertIsNone(parse_permission(load("plain.txt")))

def test_hash_ignores_trailing_spaces_and_blank_lines(self):
    a = ["x  ", "", "y"]; b = ["x", "y", ""]
    self.assertEqual(screen_hash(a), screen_hash(b))

def test_check_refuses_unknown_key(self):
    lines = load("perm-bash.txt")
    opt, err = check_approval("blocked", "permission", lines, "9", screen_hash(lines))
    self.assertIsNone(opt); self.assertIn("option", err)

def test_check_refuses_changed_hash(self):
    lines = load("perm-bash.txt")
    opt, err = check_approval("blocked", "permission", lines, "1", "deadbeef")
    self.assertIsNone(opt); self.assertIn("a changé", err)

def test_check_refuses_not_blocked(self):
    lines = load("perm-bash.txt")
    self.assertIsNone(check_approval("done", None, lines, "1", screen_hash(lines))[0])

def test_check_accepts(self):
    lines = load("perm-bash.txt")
    opt, err = check_approval("blocked", "permission", lines, "1", screen_hash(lines))
    self.assertIsNone(err); self.assertEqual(opt["role"], "approve")
```

- [ ] **Step 3: Lancer** `python3 -m unittest tests.test_perm -v` → échec (`ModuleNotFoundError: perm`).

- [ ] **Step 4: Écrire `perm.py`.** Menu = bloc de lignes `^\s*(?:❯\s*)?(\d)\.\s+(.+)$` consécutives (2 à 4) précédé, dans les 15 lignes au-dessus, d'une ligne finissant par `?` (la question). `detail` = lignes non vides entre l'en-tête de l'outil (la première ligne du cadre au-dessus de la question) et la question, cadres `│╭╰─` retirés, 400 caractères max. Rôle par libellé : commence par `No` → `deny` ; contient `don't ask again` ou `always` → `always` ; commence par `Yes` → `approve` ; sinon l'option est ignorée. Aucun menu sans au moins une option `approve` et une `deny` → `None`.

- [ ] **Step 5: Lancer** `python3 -m unittest tests.test_perm -v` → tous `ok`.

- [ ] **Step 6: Commit** `git add perm.py tests/test_perm.py demo/screens && git commit -m "perm: lecture du menu d'autorisation de Claude Code"`

---

### Task 2: Derniers messages (`thread.py`) et route `GET /api/thread`

**Files:**
- Create: `thread.py`, `tests/test_thread.py`, `demo/transcripts/t4h.jsonl`
- Modify: `server.py` (`load_modules`: ajouter `"thread"`)

**Interfaces:**
- Consumes: `srv.pid_of(addr)`, `srv.messages(pid) -> [(ts_ms, "user"|"assistant", text)]` (déjà filtrés des `<system-reminder>`, messages méta et sous-agents), `srv.read_screen(addr) -> list[str]`, `srv.ROUTES`.
- Produces:
  - `last_exchange(msgs, limit=600) -> {"me": Msg|None, "agent": Msg|None}` avec `Msg = {"text": str, "ts": int|None, "truncated": bool, "full": str}` ; `me` = dernier `user` ; `agent` = dernier `assistant` **postérieur** à `me` (sinon dernier `assistant`).
  - `screen_excerpt(lines, limit=600) -> str` : lignes de cadre (`^[\s│╭╰─┌└┐┘]+$`), ligne d'invite (`^\s*[>❯]`) et lignes vides de fin retirées ; garde la fin.
  - `GET /api/thread?address=<a>` → `last_exchange(...)` pour une session locale ; pour une adresse contenant `/` ou sans pid : `{"me": null, "agent": {"text": screen_excerpt(...), "ts": null, "truncated": …, "full": …, "screen": true}}`.

- [ ] **Step 1: Tests** (`tests/test_thread.py`) :

```python
def test_last_exchange_pairs_me_then_agent(self):
    m = [(1, "user", "a"), (2, "assistant", "b"), (3, "user", "c"), (4, "assistant", "d")]
    r = last_exchange(m)
    self.assertEqual((r["me"]["text"], r["agent"]["text"]), ("c", "d"))

def test_agent_before_me_still_shown_when_no_reply_yet(self):
    r = last_exchange([(1, "assistant", "b"), (2, "user", "c")])
    self.assertEqual(r["agent"]["text"], "b")

def test_last_exchange_truncates(self):
    r = last_exchange([(1, "assistant", "x" * 900)])
    self.assertEqual(len(r["agent"]["text"]), 600); self.assertTrue(r["agent"]["truncated"])
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
    d = json.loads(body); self.assertIsNone(d["me"]); self.assertTrue(d["agent"]["screen"])
```

`FakeSrv` / `FakeHandler` vivent dans `tests/fakes.py` (créé ici, réutilisé tâches 3 et 4) : `FakeSrv` expose `ROUTES = {"GET": {}, "POST": {}, "POST_RAW": {}}`, `SNAPSHOT_HOOKS = []`, `pid_of`, `messages`, `read_screen`, `snapshot`, `paired`, `hc_keys` (enregistre les appels), `LOCK`, `SENTF` (fichier temporaire) ; `FakeHandler(path, paired=True)` expose `.path`.

- [ ] **Step 2: Lancer** `python3 -m unittest tests.test_thread -v` → échec (module absent).
- [ ] **Step 3: Écrire `thread.py`** (`last_exchange`, `screen_excerpt`, `register(srv)`), et ajouter `"thread"` à la liste de `load_modules()` dans `server.py`.
- [ ] **Step 4: Lancer** `python3 -m unittest tests.test_thread -v` → `ok`.
- [ ] **Step 5: Commit** `git commit -m "thread: dernier message de toi et de l'agent (/api/thread)"`

---

### Task 3: Approbations (`approve.py`) : état et `POST /api/approve`

**Files:**
- Create: `approve.py`, `tests/test_approve.py`
- Modify: `server.py` : dans `build_state()`, chaque agent reçoit `"kind": t["status"].get("kind")` ; `load_modules()` ajoute `"approve"` ; nouvelle fonction `hc_keys(addr: str, key: str) -> str|None` (lance `[HC, "keys", addr, key]`, délai 10 s, renvoie le message d'erreur ou `None`).

**Interfaces:**
- Consumes: `perm.parse_permission`, `perm.screen_hash`, `perm.check_approval` (tâche 1) ; `srv.read_screen`, `srv.snapshot`, `srv.paired`, `srv.hc_keys`, `srv.SNAPSHOT_HOOKS`, `srv.SENTF`, `srv.LOCK`.
- Produces:
  - Hook `annotate(terms, agents)` : pour tout agent `status == "blocked"` et `kind == "permission"`, ajoute `a["perm"] = parse_permission(lines) | {"screen_hash": screen_hash(lines)}` ou `{"options": [], "screen_hash": …}` si non reconnu. Cache par `(address, since_ms)` pour ne relire l'écran qu'une fois par blocage.
  - `POST /api/approve` corps JSON `{"address", "key", "screen_hash"}` → `{"ok": true, "label": …}` ou `{"error": …}` (HTTP 200 comme `/api/send`). Non appairé → `{"error": "appareil non appairé…"}` (même texte que `send_route`). Journal `sent.jsonl` : `{"ts", "address", "approve": key, "label", "role"}`. Anti double appui : `APPROVED[address] = screen_hash` ; même hash une seconde fois → `{"error": "déjà envoyé"}` sans appeler `hc_keys`.

- [ ] **Step 1: Tests** (`tests/test_approve.py`, écrans de `demo/screens/`) :

```python
def test_annotate_adds_perm(self):
    a = [{"address": "t1", "status": "blocked", "kind": "permission", "since_ms": 5}]
    approve.annotate([], a)  # via srv.read_screen -> perm-bash.txt
    self.assertEqual(a[0]["perm"]["options"][0]["role"], "approve")

def test_approve_requires_pairing(self): ...  # paired=False -> "non appairé", srv.keys_sent == []
def test_approve_refuses_changed_screen(self): ...  # hash "x" -> error "a changé", keys_sent == []
def test_approve_twice_sends_once(self):
    h = good_request(); post(h); r = post(h)
    self.assertEqual(len(srv.keys_sent), 1); self.assertIn("déjà", r["error"])
def test_approve_logs(self): ...  # dernière ligne de SENTF a "approve": "1", "role": "approve"
```

- [ ] **Step 2: Lancer** `python3 -m unittest tests.test_approve -v` → échec.
- [ ] **Step 3: Écrire `approve.py`** et les ajouts de `server.py` listés ci-dessus (sous `SEND_LOCK` pour sérialiser avec `/api/send`).
- [ ] **Step 4: Lancer** `python3 -m unittest discover -s tests -v` → tout `ok`.
- [ ] **Step 5: Vérification réelle sur le M5** après déploiement : refaire le scénario de la tâche 1 ; `curl -s localhost:8766/api/state` montre `perm` ; `curl -X POST -d '{"address":"…","key":"1","screen_hash":"…"}' localhost:8766/api/approve` → la commande s'exécute dans le terminal.
- [ ] **Step 6: Commit** `git commit -m "approve: approuver / refuser les demandes d'autorisation"`

---

### Task 4: Voix (`voice.py`) et installation de Whisper sur le M5

**Files:**
- Create: `voice.py`, `tests/test_voice.py`, `tests/fake_whisper.sh`
- Modify: `server.py` : `ROUTES["POST_RAW"] = {}` ; dans `do_POST`, si le chemin est dans `ROUTES["POST_RAW"]`, appeler `fn(self, raw_bytes)` (lecture de `Content-Length` octets, refus 413 au-delà de 5 Mo **avant** lecture) ; `load_modules()` ajoute `"voice"`.

**Interfaces:**
- Produces:
  - `MAX_BYTES = 5 * 1024 * 1024`, `MAX_SECONDS = 60`.
  - `conf(state_dir: str) -> dict` : `whisper.json` fusionné sur `{"bin": "/opt/homebrew/bin/whisper-cli", "ffmpeg": "/opt/homebrew/bin/ffmpeg", "model": "~/.local/share/miniguet/whisper/ggml-large-v3-turbo-q5_0.bin"}` (chemins `~` développés).
  - `available(c: dict) -> bool` : les trois fichiers existent.
  - `class VoiceError(Exception)` (message en français).
  - `transcribe(audio: bytes, c: dict, scratch: str, timeout: int = 60) -> str` : écrit `scratch/<uuid>.in` (0600), `ffmpeg -y -i in -t 60 -ar 16000 -ac 1 out.wav`, `whisper-cli -m model -l fr -nt -np -f out.wav`, renvoie la sortie nettoyée (lignes jointes par un espace) ; supprime les fichiers dans un `finally` ; un verrou module (`threading.Lock`) : un seul transcodage à la fois.
  - `GET /api/voice` → `{"available": bool}` ; `POST_RAW /api/transcribe` → `{"text"}` ou `{"error"}` ; exige `srv.paired(h)`.

- [ ] **Step 1: Tests** avec `tests/fake_whisper.sh` (script qui imprime `bonjour le monde`, ou dort 5 s si `FAKE_SLEEP=1`) et un vrai `ffmpeg` s'il est présent (sinon `skipUnless`) :

```python
def test_transcribe_returns_text(self): ...          # == "bonjour le monde"
def test_transcribe_rejects_too_big(self):
    with self.assertRaises(VoiceError): transcribe(b"x" * (MAX_BYTES + 1), c, d)
def test_transcribe_timeout_cleans_up(self):
    # FAKE_SLEEP=1, timeout=1 -> VoiceError("délai"), os.listdir(scratch) == []
def test_transcribe_missing_binary(self):
    # c["bin"] = "/nope" -> VoiceError, available(c) is False
def test_route_requires_pairing(self): ...
```

- [ ] **Step 2: Lancer** `python3 -m unittest tests.test_voice -v` → échec.
- [ ] **Step 3: Écrire `voice.py`** et les ajouts de `server.py`.
- [ ] **Step 4: Lancer** `python3 -m unittest discover -s tests -v` → tout `ok`.
- [ ] **Step 5: Installer sur le M5** : `ssh kevin@100.75.247.49 'brew install whisper-cpp && mkdir -p ~/.local/share/miniguet/whisper && curl -L -o ~/.local/share/miniguet/whisper/ggml-large-v3-turbo-q5_0.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin'`. Vérifier : `whisper-cli -m … -l fr -f /opt/homebrew/share/whisper-cpp/jfk.wav` (ou un court WAV enregistré) transcrit en moins de 5 s.
- [ ] **Step 6: Commit** `git commit -m "voice: transcription locale par Whisper (/api/transcribe)"`

---

### Task 5: Mode démo, ui-sdk copié, `/classic`, coquille de la nouvelle page et regroupement

**Files:**
- Create: `demo/terminals.json` (8 sessions couvrant : erreur, blocked/permission, blocked/auth, done avec questions, done sans question, working, working bloquée 40 min, distante `m1/t16`, une reportée), `demo/transcripts/*.jsonl`, `index-classic.html` (copie exacte de l'actuelle `index.html`), `assets/ui-sdk/0.1.0-beta.1/` (contenu de `package/browser/` de `@ui-sdk/web@0.1.0-beta.1` + `LICENSE`), `assets/app/style.css`, `assets/app/api.js`, `assets/app/groups.js`, `assets/app/app.js`, `tests/js/groups.test.mjs`
- Modify: `server.py` (mode démo, `/classic`), `index.html` (réécrite : coquille)

**Interfaces:**
- Mode démo : variable d'environnement `MINIGUET_DEMO=<dossier>` ; `snapshot()` renvoie `<dossier>/terminals.json`, `read_screen(addr)` lit `<dossier>/screens/<addr avec / remplacé par _>.txt`, `transcript_path` pointe vers `<dossier>/transcripts/<addr>.jsonl` via un pid factice, `hc send` / `hc keys` sont remplacés par une écriture dans `<dossier>/out.log`, l'état (`STATE_DIR`) va dans `<dossier>/state/`. Lancement : `MINIGUET_DEMO=demo python3 server.py --port 8799`.
- `GET /classic` sert `index-classic.html`.
- `groups.js` exporte :
  - `GROUPS = [{id: "error", label: "En erreur"}, {id: "approve", label: "Attend ton feu vert"}, {id: "question", label: "Te pose une question"}, {id: "review", label: "A fini, à relire"}, {id: "working", label: "Travaille"}, {id: "snoozed", label: "Reportées"}]`
  - `groupOf(agent, nowMs) -> id` selon le tableau du spec (snooze actif d'abord → `snoozed` ; `blocked`+`auth` → `error`).
  - `grouped(agents, nowMs) -> [{id, label, items}]` : groupes non vides dans l'ordre de `GROUPS` ; dans chaque groupe, échéance aujourd'hui / en retard d'abord, puis plus récent d'abord (`since_ms` décroissant).
  - `waitingCount(agents, nowMs) -> number` : éléments des groupes `error|approve|question|review`.
  - `badge(agent) -> {text, tone}` (« AUTORISATION », « 2 QUESTIONS », « TERMINÉ », « ERREUR », « CONNEXION REQUISE », « TRAVAILLE ») et `summary(agent) -> string` (commande demandée, première question ouverte, ou `msg`).
- `api.js` exporte `getState()`, `getThread(address)`, `post(path, body)`, `transcribe(blob)`, `voiceAvailable()` ; chaque appel renvoie l'objet JSON ou lève `Error(message)`.

- [ ] **Step 1: Tests JS** (`tests/js/groups.test.mjs`, `node --test`) :

```js
test("permission goes to approve", () => assert.equal(groupOf({status: "blocked", kind: "permission"}, NOW), "approve"))
test("auth goes to error", () => assert.equal(groupOf({status: "blocked", kind: "auth"}, NOW), "error"))
test("done with open question", () => assert.equal(groupOf({status: "done", q: {open: ["x"]}}, NOW), "question"))
test("blocked question goes to question", () => assert.equal(groupOf({status: "blocked", kind: "question"}, NOW), "question"))
test("done without question", () => assert.equal(groupOf({status: "done", q: {open: [], todo: ["t"]}}, NOW), "review"))
test("snooze wins", () => assert.equal(groupOf({status: "done", q: {open: ["x"]}, snooze: {until: NOW + 1e6}}, NOW), "snoozed"))
test("deadline today first in group", ...)
test("waitingCount excludes working and snoozed", ...)
```

(Champs réels : `q.open` et `q.todo`, listes de textes déjà filtrées par `filt()` dans `server.py`.)

- [ ] **Step 2: Lancer** `node --test tests/js/` → échec.
- [ ] **Step 3: Écrire `groups.js`, `api.js`.**
- [ ] **Step 4: Lancer** `node --test tests/js/` → `ok`.
- [ ] **Step 5: Mode démo, `/classic`, copie ui-sdk, coquille** : `index.html` = en-tête (logo, « À toi N », pastille ⏰, Rafale, Statistiques, Daily, menu `⋯` en `ui-menu`), `<nav id="list">`, `<section id="detail">`, `@layer ui-sdk;`, `assets/ui-sdk/0.1.0-beta.1/web.css` puis `assets/app/style.css` (jetons sombre / clair sur `:root` et `[data-theme=light]`), `<script type="module" src="assets/ui-sdk/0.1.0-beta.1/web.js">`, `<script type="module" src="assets/app/app.js">`. `app.js` : polling `getState()` toutes les 2 s, rendu de la liste groupée (groupes `working` et `snoozed` en `ui-collapsible` fermés), bandeau « Mac injoignable » après 3 échecs.
- [ ] **Step 6: Vérifier** : `MINIGUET_DEMO=demo python3 server.py --port 8799`, ouvrir `http://localhost:8799` avec Playwright à 1180×820 : les 6 groupes de la démo apparaissent dans l'ordre, chaque ligne ≥ 64 px ; `http://localhost:8799/classic` affiche l'ancienne page.
- [ ] **Step 7: Commit** `git commit -m "Nouvelle page: coquille, liste groupee par attente, mode demo, ui-sdk copie"`

---

### Task 6: Panneau de session : fil, carte de réponse, section « Plus »

**Files:**
- Create: `assets/app/detail.js`, `assets/app/reply.js`, `tests/js/reply.test.mjs`
- Modify: `assets/app/app.js`, `assets/app/style.css`

**Interfaces:**
- Consumes: `getThread`, `post` (tâche 5) ; `/api/send` `{address, text, questions, since_ms}` (inchangé) ; `/api/approve` (tâche 3) ; `/api/snooze`, `/api/snooze-item`, `/api/deadline`, `/api/dismiss` (retirer et remettre), `/api/info`, `/api/resume` (inchangées : reprendre les corps exacts envoyés par `index-classic.html`).
- Produces:
  - `reply.js` : `composeMessage(free: string, answers: [{question, choice: "Oui"|"Non"|"", text}]) -> string` — **même format** que la fonction d'assemblage de `index-classic.html` (la retrouver et la porter à l'identique) ; état des brouillons `DRAFTS: Map<address, {free, answers}>` conservé entre les rafraîchissements.
  - `detail.js` : `renderDetail(agent, thread, el)` ; texte des agents inséré avec `textContent` uniquement.

- [ ] **Step 1: Tests JS** (`tests/js/reply.test.mjs`) : `composeMessage` produit exactement le texte de l'ancienne page pour 3 cas (Oui/Non seuls, texte libre en tête, précision après un Non) — textes attendus relevés en exécutant l'ancienne fonction dans Node.
- [ ] **Step 2: Lancer** `node --test tests/js/` → échec ; **Step 3:** écrire `reply.js` ; **Step 4:** `node --test tests/js/` → `ok`.
- [ ] **Step 5: Écrire `detail.js`** : en-tête de session ; deux bulles (toi à droite, agent à gauche, « (écran) » si `screen`), « Voir tout » si `truncated` ; carte d'action selon `groupOf` : *approve* → détail en chasse fixe + boutons par option (`approve` vert, `always` neutre, `deny` rouge), appel `/api/approve` avec `screen_hash`, désactivés pendant l'envoi, `ui-toast` du résultat ; options vides → texte « Réponds dans le terminal : menu non reconnu » ; *question* → par question un groupe `ui-toggle` Oui / Non (un seul actif, ré-appui = aucun), un `textarea` + emplacement du bouton micro (tâche 7), bouton « Aperçu et envoi » ouvrant un `ui-dialog` avec le texte de `composeMessage` modifiable puis « Envoyer » (`/api/send`, `since_ms` = `agent.since_ms`) ; *review/error* → textarea + micro + envoi ; section « Plus » (`ui-collapsible`, fermée) avec À faire, Déjà traité, Retirées, Reprendre le fil, Plus d'infos, Reporter, Échéance portés depuis `index-classic.html`.
- [ ] **Step 6: Vérifier dans le navigateur (démo, Playwright 1180×820 et 820×1180)** :
  - `escapes agent html` : un transcript de démo contient `<b>gras</b>` → affiché littéralement.
  - `keeps selection and draft across refresh` : ouvrir une session, cocher Non, taper « test », attendre 5 s (2 rafraîchissements) → même session ouverte, Non coché, « test » présent.
  - Approuver sur la session démo → `demo/out.log` contient `keys <adresse> 1` ; second appui → toast « déjà envoyé ».
  - Aperçu et envoi → `demo/out.log` contient le message composé.
  - Portrait : la liste occupe l'écran, toucher une session ouvre le panneau avec « ← Sessions ».
- [ ] **Step 7: Commit** `git commit -m "Panneau de session: fil, approbation, Oui/Non, apercu et envoi, section Plus"`

---

### Task 7: Bouton micro (`voice.js`)

**Files:**
- Create: `assets/app/voice.js`
- Modify: `assets/app/detail.js`, `assets/app/style.css`

**Interfaces:**
- Consumes: `voiceAvailable()`, `transcribe(blob)` (tâche 5), `/api/transcribe` (tâche 4).
- Produces: `micButton(textarea: HTMLTextAreaElement) -> HTMLElement | null` (null si `!navigator.mediaDevices || !window.MediaRecorder` ou voix indisponible). États : repos (🎙), enregistrement (rouge, minuterie `0:12`, arrêt auto à 60 s), transcription (indicateur), erreur (`ui-toast`). Le texte est **ajouté** au contenu du textarea (séparé par un espace), curseur à la fin, focus rendu au textarea ; jamais d'envoi.

- [ ] **Step 1: Écrire `voice.js`** (`MediaRecorder` avec le type par défaut du navigateur ; `Blob` envoyé tel quel) et l'intégrer aux cartes *question* et *review/error*.
- [ ] **Step 2: Vérifier en démo** (Playwright avec un faux micro : `--use-fake-device-for-media-stream`) : appui, attente 2 s, appui → le textarea contient le texte du faux whisper ; sans `whisper.json` valide → pas de bouton.
- [ ] **Step 3: Vérifier sur l'iPad** après déploiement : dicter « oui vas-y et relance les tests » → texte correct dans le champ en moins de 5 s.
- [ ] **Step 4: Commit** `git commit -m "Voix: bouton micro, transcription Whisper ajoutee au champ"`

---

### Task 8: Rafale, mode bureau, menu `⋯`, sons, surimpressions Stats / Daily

**Files:**
- Create: `assets/app/rafale.js`, `assets/app/desk.js`
- Modify: `assets/app/app.js`, `index.html`, `assets/app/style.css`

**Interfaces:**
- Consumes: `grouped`, `waitingCount`, `badge` (tâche 5) ; `composeMessage`, `DRAFTS` (tâche 6) ; `micButton` (tâche 7) ; `assets/sound.js` (inchangé, mêmes appels qu'`index-classic.html`).
- Produces: `openRafale()` ; `toggleDesk()`.

- [ ] **Step 1: Rafale** en `ui-dialog` plein écran : file = demandes d'autorisation puis questions ouvertes (ordre des groupes) ; carte autorisation = mêmes boutons que la tâche 6 (envoi immédiat) ; carte question = Oui / Non / Autre (textarea + micro) ; Passer (reporte d'1 h via `/api/snooze-item`, comme aujourd'hui) ; Plus pertinent ; récapitulatif modifiable avant tout envoi, « Tout envoyer ».
- [ ] **Step 2: Mode bureau** (`desk.js`) : porté de `index-classic.html` (gros chiffre `waitingCount`, assombri la nuit, Wake Lock), couleur = groupe le plus urgent non vide.
- [ ] **Step 3: Menu `⋯`** (`ui-menu`) : Mode bureau, Sons, Musique, Thème clair / sombre (mémorisé en `localStorage`, dans un try/catch). Sons : bips différents demande / échéance / erreur comme aujourd'hui (porter la détection de nouveauté de `index-classic.html`), plus un bip « demande » à l'arrivée d'une session dans `approve`.
- [ ] **Step 4: Stats / Daily** en surimpression (iframe `?embed=1`, comme l'ancienne page), routes `/stats`, `/daily`, `/daily/history` inchangées ; la musique continue pendant l'ouverture.
- [ ] **Step 5: Vérifier en démo** : Rafale passe par une autorisation puis deux questions, récapitulatif, envoi → `demo/out.log` ; mode bureau affiche le compte ; thème clair appliqué et mémorisé après rechargement ; ouvrir/fermer Stats ne coupe pas la musique.
- [ ] **Step 6: Commit** `git commit -m "Rafale, mode bureau, menu, sons et surimpressions dans la nouvelle page"`

---

### Task 9: Accessibilité, contraste, parité, déploiement

**Files:**
- Create: `tests/js/agent.test.mjs` (test « agent » exigé par le skill ui-sdk, voir `~/.agents/skills/ui-sdk/references/agent-ready.md`)
- Modify: `README.md`, `assets/app/style.css` si un contraste échoue

- [ ] **Step 1:** Lire `~/.agents/skills/ui-sdk/references/agent-ready.md` et `testing.md` ; écrire le test agent qu'ils décrivent pour la page (contrôles trouvables par leur nom : « Approuver », « Refuser », « Oui », « Non », « Aperçu et envoi », « Dicter »).
- [ ] **Step 2: Contraste** : script Playwright qui calcule le ratio de chaque texte et bord de contrôle visible en sombre et en clair (formule WCAG) → aucun texte < 4,5, aucun bord / focus / fond d'état < 3. Corriger les jetons fautifs.
- [ ] **Step 3: Clavier** : Tab parcourt en-tête, liste, carte d'action dans l'ordre ; focus visible partout ; Échap ferme les dialogues.
- [ ] **Step 4: Parité** — vérifier chaque point en démo puis sur l'iPad : reporter une session (toutes les options) et un point ; échéance (boutons, date, note) ; retirer / remettre un point, « Tout retirer » ; Plus d'infos ; Reprendre le fil ; Rafale ; mode bureau ; sons et musique (déverrouillage au premier appui) ; Stats / Daily en surimpression ; bandeau « Mac injoignable » (couper le serveur démo) ; sessions bloquées 30 min signalées ; sessions de l'ancien herdr (`source`) avec « Répondre : non supporté » ; liens de l'en-tête (`links`) ; pastille « ⏰ Daily prêt ».
- [ ] **Step 5: README** : section Whisper (installation, `whisper.json`), mode démo, `/classic` (retrait prévu le 2026-11-27), commande des tests `python3 -m unittest discover -s tests -v && node --test tests/js/`.
- [ ] **Step 6:** `python3 -m unittest discover -s tests -v && node --test tests/js/` → tout `ok`.
- [ ] **Step 7: Commit, push, déployer** : `git commit -m "Refonte: accessibilite, contraste, README" && git push && scripts/deploy.sh kevin@100.75.247.49` ; vérifier `https://miniguet.herembourg.fr` sur l'iPad.
