# Refonte de l'interface Miniguet — plan de réalisation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nouvelle page tablette (liste groupée par attente + conversation), approbation des demandes d'autorisation, réponses Oui/Non/texte/voix (Whisper local sur le M5).

**Architecture:** Trois nouveaux modules serveur à la manière de `daily.py` (`register(srv)` sur les points d'extension `ROUTES` / `SNAPSHOT_HOOKS`, `server.py:695-697`, chargés par `load_modules()` `server.py:774`), chacun avec un cœur pur testable sans importer `server.py`. Une nouvelle `index.html` en modules JS sans build sous `assets/app/`, avec les web components `ui-sdk` copiés dans le repo. Un mode démo (`MINIGUET_DEMO`) sert des données d'exemple pour développer et tester l'interface. Le service des fichiers `assets/` doit accepter des sous-dossiers (aujourd'hui `os.path.basename`, `server.py:923`) : ui-sdk charge `web/*.js` et `web/chunks/*.js` relativement à `web.js`.

**Tech Stack:** Python 3.9+ stdlib (`unittest`), HTML/CSS/JS modules, `@ui-sdk/web@0.1.0-beta.1` (build navigateur copié), `node --test` (Node 22 présent, outil de dev seulement) pour les fonctions JS pures, Playwright (MCP) pour le navigateur, `whisper-cpp` + `ffmpeg` sur le M5.

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
- La page référence ses fichiers en chemins **absolus** (`/assets/...`) : le serveur la sert aussi à `/stats`, `/daily`, `/daily/history` (`server.py:901-903`), où un chemin relatif casserait.
- `web.css` de ui-sdk fixe les boutons / champs à `calc(var(--ui-spacing) * 8)` (32 px) et `color-scheme: light dark` : `style.css` les surcharge (48 / 56 px ; `color-scheme: dark` sur `:root`, `light` sur `[data-theme=light]`) et règle les jetons `--ui-*`.
- **Tests (obligatoire)** : pour chaque changement de comportement, d'abord le test qui échoue (RED, échec constaté pour la bonne raison), puis le code qui le fait passer (GREEN). En local, on ne lance **que** les tests écrits pour cette tâche, avec des sélecteurs explicites (`python3 -m unittest tests.test_approve -v`, `python3 -m unittest tests.test_approve.ParseTest -v`, `node --test tests/js/groups.test.mjs`) ; jamais `unittest discover`, jamais `node --test tests/js/` ni aucune suite complète ou non filtrée.

## Lots (deux réalisateurs, un seul auteur par fichier)

| Lot | Tâches | Fichiers possédés (seul ce lot les écrit) |
|---|---|---|
| **A — serveur** | 0, 1, 2, 3, 4 | `server.py`, `approve.py`, `thread.py`, `voice.py`, `tests/fakes.py`, `tests/test_approve.py`, `tests/test_thread.py`, `tests/test_voice.py`, `tests/test_server.py`, `tests/fake_whisper.sh`, `tests/fake_ffmpeg.sh`, `demo/**`, `.gitignore` |
| **B — page** | 5, 6, 7, 8, 9 | `index.html`, `index-classic.html`, `assets/app/**`, `assets/ui-sdk/**`, `tests/js/**`, `README.md` |

- Les contrats que B consomme sont figés dans ce plan : champs `kind` / `perm` de `/api/state` (tâche 3), `/api/thread` (tâche 2), `/api/approve` (tâche 3), `/api/voice` et `/api/transcribe` (tâche 4), mode démo et données de démo (tâche 0). B peut commencer tout de suite (tâche 5 étapes 1-4 : fonctions pures et tests JS).
- **Dépendance dure** : la première vérification navigateur de B (tâche 5 étape 6) exige la tâche 0 livrée (sous-dossiers d'`assets/`, type `text/css`, mode démo, `/classic`). A fait donc la tâche 0 **en premier**, puis 1 → 4. Les vérifications navigateur d'approbation (tâche 6) et de voix (tâche 7) exigent les tâches 3 et 4.
- `index-classic.html` : B le crée (copie exacte de l'`index.html` actuelle) **avant** de réécrire `index.html` ; A ne fait que la route `/classic`.
- A transmet à B, pour le README, les faits serveur (installation Whisper, `whisper.json`, mode démo, commandes de test).

## Review Focus

1. **Double appui sur Approuver** : une seule touche part. → test `test_approve_twice_sends_once` (tâche 3).
2. **La demande a changé entre l'affichage et l'appui** (Claude enchaîne une autre autorisation) : refus explicite, rien n'est tapé ; le hash porte sur le menu lu (outil, commande, options), pas sur l'écran entier dont le pied bouge. → tests `test_approve_refuses_changed_screen` (tâche 3), `test_hash_ignores_footer_change` et `test_hash_changes_with_command` (tâche 1).
3. **Message d'agent long, avec Markdown, `<balises>` ou blocs de code** : affiché en texte brut, tronqué à 600 caractères avec « Voir tout ». → tests `test_last_exchange_truncates` (tâche 2) et `escapes agent html` (tâche 6).
4. **La liste se rafraîchit pendant qu'on répond** (polling toutes les 2 s, la session change de groupe ou un autre arrive) : la session ouverte reste ouverte, le texte saisi et les Oui/Non cochés sont conservés. → test navigateur `keeps selection and draft across refresh` (tâche 6).
5. **Audio trop long, trop gros, Whisper absent ou planté** : message clair en moins de 60 s, aucun fichier laissé dans `scratch/`. → tests `test_transcribe_rejects_too_big`, `test_transcribe_timeout_cleans_up`, `test_transcribe_missing_binary` (tâche 4).

---

## Fichiers

| Fichier | Rôle | Existe pour satisfaire |
|---|---|---|
| `approve.py` (créé, lot A) | Cœur pur : lecture du menu d'autorisation, hash du menu, vérification avant approbation ; module : annote les sessions `blocked/permission` (`perm`) et route `POST /api/approve`. (L'ancien `perm.py` séparé est fusionné ici : un seul module, comme `daily.py`.) | Spec §Côté serveur 2 (Approuver / Refuser depuis la tablette, jamais une autre demande que celle affichée). |
| `thread.py` (créé, A) | `GET /api/thread` (dernier message de toi / de l'agent). Cœur pur. | Spec §Côté serveur 1 (voir ton dernier message et la dernière réponse). |
| `voice.py` (créé, A) | `GET /api/voice`, `POST /api/transcribe` (ffmpeg + whisper-cli). Cœur pur. | Spec §Côté serveur 3 (voix, Whisper local). |
| `server.py` (modifié, A) | Charge les modules ; `kind` dans l'état ; `hc_keys()` ; sous-dossiers et CSS sous `/assets/` ; `/classic` ; mode démo. | Approbation (touche), ui-sdk et modules JS servis localement (anti-objectif « pas de CDN »), mise en service, tests sur démo. |
| `demo/` (créé, A) | `terminals.json`, `screens/<adresse>.txt`, `transcripts/<adresse>.jsonl`, `state/memory.json` (analyses pré-remplies), `whisper.json` (faux binaires) ; `demo/state/` et `demo/out.log` ignorés par git. | Spec §Tests (« données d'exemple servies par le serveur en mode démo ») et écrans d'exemple des tests serveur. |
| `tests/*.py`, `tests/fakes.py`, `tests/fake_*.sh` (créés, A) | Tests `unittest` ; faux `srv` / handler ; faux whisper / ffmpeg. | Spec §Tests serveur. |
| `tests/js/*.test.mjs` (créés, B) | `node --test` sur les fonctions pures (regroupement, assemblage du message). | Review Focus 3-4 ; même format de message qu'aujourd'hui. |
| `index-classic.html` (créé, B) | Copie de l'ancienne `index.html`, servie à `/classic` jusqu'au 2026-11-27. | Spec §Mise en service (secours). |
| `index.html` (réécrit, B) | Coquille de la page : en-tête, liste, panneau, dialogues. | Disposition A. |
| `assets/app/*.js` (créés, B) | `api.js` (appels serveur), `groups.js` (regroupement, pur), `reply.js` (assemblage du message, pur, brouillons), `detail.js` (panneau), `voice.js` (micro), `rafale.js`, `desk.js`, `app.js` (polling, liste, en-tête). Pas de `list.js` : la liste est rendue par `app.js` (aucune tâche ne le justifiait). | Découpage laissé au constructeur par le spec ; les fichiers purs existent pour être testés sous Node sans navigateur. |
| `assets/app/style.css` (créé, B) | Jetons de thème, mise en page, surcharges de `web.css`. | Contraste, cibles tactiles, thèmes. |
| `assets/ui-sdk/0.1.0-beta.1/` (créé, B) | Copie intégrale de `package/browser/` (`web.js`, `web.css`, `web/` avec ses 58 entrées et `web/chunks/`) + `LICENSE`. | Spec §Composants ui-sdk (copié et figé). |
| `README.md` (modifié, B) | Whisper, mode démo, `/classic`, commandes de test. | Exploitation. |

---

### Task 0 (lot A, à faire en premier) : serveur prêt pour la nouvelle page — `/assets/` en sous-dossiers, `/classic`, mode démo

**Files:**
- Create: `tests/test_server.py`, `tests/fakes.py`, `demo/terminals.json`, `demo/screens/*.txt`, `demo/transcripts/*.jsonl`, `demo/seed/` (`memory.json`, `snooze.json`, `deadlines.json`, `whisper.json`)
- Modify: `server.py`, `.gitignore` (`demo/state/`, `demo/out.log`)

**Faits relevés dans le code :**
- `/assets/` ne sert qu'un nom de base (`name = os.path.basename(p)`, `server.py:923`) et seulement `png ico svg js mp3` (`server.py:925-926`) : `/assets/ui-sdk/0.1.0-beta.1/web/chunks/X.js` et tout `.css` font 404.
- Le chemin d'état est figé à l'import : `STATE_DIR` (`server.py:45`) **et** `MEM` (`server.py:52`, d'où dérivent `DLF`, `DIF`, `SNZF`, `SNZIF`, `SENTF`, `SNZLOG`) ; `PAIRF` dérive de `STATE_DIR`.
- `send_route` appelle `subprocess.run([HC, "send", ...])` en direct (`server.py:673`) ; `questions_for` lance `analyze` → `ask_sonnet` (`claude -p`, `server.py:533-540`) pour toute session `done` sans analyse en mémoire ; `backup` (chargé par `load_modules`, `server.py:775`) chiffre et envoie l'état vers Cloudflare D1.

**Interfaces (contrat pour le lot B) :**
- `GET /assets/<chemin>` : sous-dossiers acceptés ; chemin résolu par `os.path.realpath` et refusé (404) s'il sort de `HERE/assets/` ; types ajoutés : `css` → `text/css; charset=utf-8`, `js` → `text/javascript` (inchangé). Le reste du comportement (plages, cache) est inchangé.
- `GET /classic` sert `index-classic.html` (404 tant que le lot B ne l'a pas créé).
- Mode démo : `MINIGUET_DEMO=<dossier> python3 server.py --port 8799`. Lu tout en haut de `server.py`, avant `STATE_DIR`/`MEM` : l'état va dans `<dossier>/state/`, créé au lancement par copie de `<dossier>/seed/` s'il n'existe pas (les fichiers suivis par git ne sont jamais réécrits). `snapshot()` lit `<dossier>/terminals.json` (même forme que `hc events` → `{"terminals": [...]}`, passée par `_remote`) ; `read_screen(addr)` lit `<dossier>/screens/<addr, « / » remplacé par « _ »>.txt` (liste vide si absent) ; `transcript_path(pid)` renvoie `<dossier>/transcripts/<pid>.jsonl` (les terminaux de démo portent `foreground.pid` = un entier, nom du fichier) ; `hc send` (extrait de `send_route` dans une fonction `hc_send(addr, text) -> str|None`) et `hc_keys` (tâche 3) ajoutent une ligne `send <adresse> <texte>` / `keys <adresse> <touche>` à `<dossier>/out.log` ; `ask_sonnet` lève `RuntimeError("démo : pas d'appel à Claude")` ; `load_modules` ne charge pas `backup` ni `oldherdr`. Les analyses des sessions `done` viennent de `memory.json` (entrées `LAST[addr]` avec `"tkey": [turn, status_ms]`, réutilisées par `questions_for`, `server.py:345-346`).
- Contenu de démo (8 à 10 sessions) : erreur ; `blocked/permission` (écran `perm-bash`) ; `blocked/permission` à 3 options (`perm-write`) ; `blocked/auth` ; `blocked/question` ; `done` avec 2 questions ouvertes ; `done` avec seulement des tâches ; `working` ; `working` figée (`stalled_min`) ; distante `m1/t16` ; une reportée (`state/snooze.json`) ; une avec échéance aujourd'hui (`state/deadlines.json`). Un transcript contient `<b>gras</b>` et un message de plus de 600 caractères.

**Exists to satisfy :** sous-dossiers d'assets → ui-sdk servi localement (anti-objectif « pas de CDN ») ; `/classic` → spec §Mise en service ; mode démo → spec §Tests interface.

- [ ] **Step 1: Tests (RED)** `tests/test_server.py` : lance `server.py` dans un sous-processus avec `MINIGUET_DEMO=<copie temporaire de demo/>` sur un port libre, puis : `/assets/ui-sdk/x/../../logo.png` hors dossier → 404 ; `/assets/%2e%2e/server.py` → 404 ; un fichier imbriqué créé dans un dossier temporaire sous `assets/` → 200 ; `.css` → `text/css` ; `/api/state` renvoie les sessions de `demo/terminals.json` ; `POST /api/send` sur la session `done` → `out.log` contient `send`. `python3 -m unittest tests.test_server -v` → échecs attendus.
- [ ] **Step 2: Écrire** le service d'assets, `/classic`, le mode démo, `hc_send`, les données de démo.
- [ ] **Step 3: Lancer** `python3 -m unittest tests.test_server -v` → `ok`.
- [ ] **Step 4: Commit** `git commit -m "Serveur: assets en sous-dossiers, /classic, mode demo"` — puis prévenir le lot B.

---

### Task 1: Lecture du menu d'autorisation (`approve.py`, partie pure) et vérification sur une vraie session

**Files:**
- Create: `approve.py` (fonctions pures), `tests/test_approve.py` (classe `ParseTest`), `demo/screens/perm-bash.txt`, `perm-write.txt`, `plain.txt` (relevés réels)

**Interfaces:**
- Produces:
  - `parse_permission(lines: list[str]) -> dict | None` → `{"tool": str (en-tête du cadre, ex. « Bash command », champ `tool` du spec), "question": str, "detail": str, "options": [{"key": "1", "label": "Yes", "role": "approve"|"always"|"deny"}]}` ou `None` si aucun menu reconnu.
  - `menu_hash(p: dict) -> str` : SHA-1 hex de `tool`, `question`, `detail` et des couples `(key, label)`. Exposé au client sous le nom `screen_hash` (nom du spec). Le hash porte sur le **menu lu**, pas sur l'écran entier : le pied de l'écran de Claude Code (compteurs, minuteries) change sans que la demande change, et un hash d'écran ferait refuser toute approbation.
  - `check_approval(state: str, kind: str|None, lines: list[str], key: str, expected_hash: str) -> tuple[dict|None, str|None]` → `(option, None)` ou `(None, message d'erreur en français)`.

- [ ] **Step 1: Relever un vrai écran et valider la touche.** Sur le M5, lancer dans un terminal herdr `claude` et lui demander `lance la commande: ls /tmp` sans autorisation préalable. Pendant que le menu est affiché : `hc ls --json` doit montrer pour ce terminal `status.state == "blocked"` et `status.kind == "permission"` (le schéma `hc` documente `kind` : « permission, question or auth (blocked only, when the program said) ») ; `hc read <adresse> > demo/screens/perm-bash.txt`. Puis valider la syntaxe d'envoi : `hc keys <adresse> <chiffre de l'option « No »>` (syntaxe `hc keys [--json] <TERMINAL> <KEYS>...`, noms de touches « enter, esc, tab, up, ctrl+c, alt+x, f5, a, … » : un caractère seul est un nom de touche) doit refuser la demande **sans** `enter`. Si le chiffre seul ne valide pas, noter la séquence qui marche (`<chiffre> enter`, ou `down`… `enter`) et l'utiliser dans `hc_keys` (tâche 3). `hc keys` attend ~3 s sans frappe avant d'envoyer (« same quiet rule as send ») : délai de 10 s suffisant. Faire de même pour une écriture de fichier (`perm-write.txt`, menu à 3 options) et garder un écran ordinaire sans menu (`plain.txt`). Si herdr ne signale pas `blocked/permission`, s'arrêter et le signaler (le reste de la tâche 3 en dépend).

- [ ] **Step 2: Écrire les tests** dans `tests/test_approve.py`, classe `ParseTest` (`unittest`, fichiers lus depuis `demo/screens/`) :

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

def test_hash_ignores_footer_change(self):
    a = load("perm-bash.txt"); b = a + ["  ✻ 12s · esc to interrupt"]
    self.assertEqual(menu_hash(parse_permission(a)), menu_hash(parse_permission(b)))

def test_hash_changes_with_command(self):
    a = load("perm-bash.txt"); b = [l.replace("ls /tmp", "rm -rf /tmp/x") for l in a]
    self.assertNotEqual(menu_hash(parse_permission(a)), menu_hash(parse_permission(b)))

def test_check_refuses_unknown_key(self):
    lines = load("perm-bash.txt")
    opt, err = check_approval("blocked", "permission", lines, "9", menu_hash(parse_permission(lines)))
    self.assertIsNone(opt); self.assertIn("option", err)

def test_check_refuses_changed_hash(self):
    lines = load("perm-bash.txt")
    opt, err = check_approval("blocked", "permission", lines, "1", "deadbeef")
    self.assertIsNone(opt); self.assertIn("a changé", err)

def test_check_refuses_not_blocked(self):
    lines = load("perm-bash.txt")
    self.assertIsNone(check_approval("done", None, lines, "1", menu_hash(parse_permission(lines)))[0])

def test_check_accepts(self):
    lines = load("perm-bash.txt")
    opt, err = check_approval("blocked", "permission", lines, "1", menu_hash(parse_permission(lines)))
    self.assertIsNone(err); self.assertEqual(opt["role"], "approve")
```

- [ ] **Step 3: Lancer** `python3 -m unittest tests.test_approve.ParseTest -v` → échec (`ModuleNotFoundError: approve`).

- [ ] **Step 4: Écrire la partie pure d'`approve.py`.** Menu = bloc de lignes `^\s*(?:❯\s*)?(\d)\.\s+(.+)$` consécutives (2 à 4) précédé, dans les 15 lignes au-dessus, d'une ligne finissant par `?` (la question). `detail` = lignes non vides entre l'en-tête de l'outil (la première ligne du cadre au-dessus de la question) et la question, cadres `│╭╰─` retirés, 400 caractères max. Rôle par libellé : commence par `No` → `deny` ; contient `don't ask again` ou `always` → `always` ; commence par `Yes` → `approve` ; sinon l'option est ignorée. Aucun menu sans au moins une option `approve` et une `deny` → `None`.

- [ ] **Step 5: Lancer** `python3 -m unittest tests.test_approve.ParseTest -v` → tous `ok`.

- [ ] **Step 6: Commit** `git add approve.py tests/test_approve.py demo/screens && git commit -m "approve: lecture du menu d'autorisation de Claude Code"`

---

### Task 2: Derniers messages (`thread.py`) et route `GET /api/thread`

**Files:**
- Create: `thread.py`, `tests/test_thread.py`
- Modify: `server.py` (`load_modules`, `server.py:775` : ajouter `"thread"`)

**Interfaces:**
- Consumes (vérifiés) : `srv.pid_of(addr) -> int|None` (`server.py:543`, relit `snapshot()` ; `None` pour une session distante, `_remote` retire le pid, `server.py:30-42`, et pour l'ancien herdr, absent du snapshot) ; `srv.messages(pid) -> [(ts_ms, "user"|"assistant", text)]` (`server.py:215-242` : ignore `isSidechain`, `isMeta`, textes commençant par `<` ou contenant `<system-reminder>` dans les 40 premiers caractères ; ne garde que les blocs `text`, donc les résultats d'outils disparaissent ; déjà mis en cache par chemin + mtime + taille dans `TRANS` : pas de second cache) ; `srv.read_screen(addr) -> list[str]` (`server.py:159`, `hc read` avec délai 3 s, peut lever) ; `srv.ROUTES`. Un handler `GET` est appelé `fn(handler, "")` et renvoie `(code, content_type, bytes)` (`server.py:905-908`) ; l'adresse se lit dans `parse_qs(urlparse(h.path).query)` comme `daily.py:332`.
- Produces:
  - `last_exchange(msgs, limit=600) -> {"me": Msg|None, "agent": Msg|None}` avec `Msg = {"text": str, "ts": int|None, "truncated": bool, "full": str}` ; `me` = dernier `user` ; `agent` = dernier `assistant` **postérieur** à `me` (sinon dernier `assistant`).
  - `screen_excerpt(lines, limit=600) -> str` : lignes de cadre (`^[\s│╭╰─┌└┐┘]+$`), ligne d'invite (`^\s*[>❯]`) et lignes vides de fin retirées ; garde la fin.
  - `GET /api/thread?address=<a>` → `last_exchange(...)` pour une session locale ; pour une adresse sans pid (distante `machine/tN`, ancien herdr) : `{"me": null, "agent": {"text": screen_excerpt(...), "ts": null, "truncated": …, "full": …, "screen": true}}` ; si `read_screen` échoue ou ne laisse rien (cas de l'ancien herdr, que `hc read` ne connaît pas) : `{"me": null, "agent": null}`.

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

def test_route_unreadable_screen_gives_nulls(self):
    srv = FakeSrv(screen_error=RuntimeError("not_found"))
    thread.register(srv)
    d = json.loads(srv.ROUTES["GET"]["/api/thread"](FakeHandler("/api/thread?address=old-1"), "")[2])
    self.assertEqual(d, {"me": None, "agent": None})
```

`FakeSrv` / `FakeHandler` vivent dans `tests/fakes.py` (créé à la tâche 0, réutilisé tâches 2 à 4) : `FakeSrv` expose `ROUTES = {"GET": {}, "POST": {}}`, `SNAPSHOT_HOOKS = []`, `pid_of`, `messages`, `read_screen`, `snapshot`, `main_agent`, `paired(h) -> h.paired`, `hc_keys` (enregistre les appels dans `keys_sent`), `LOCK`, `SEND_LOCK`, `SENTF` (fichier temporaire), `SCRATCH` (dossier temporaire), `STATE_DIR` ; `FakeHandler(path, paired=True)` expose `.path` et `.paired`.

Et, pour le filtrage exigé par le spec (« journal d'exemple, filtrage des faux messages utilisateur »), `tests/test_server.py::ThreadDemoTest.test_thread_skips_fake_user_messages` : serveur en démo, transcript dont le dernier message utilisateur réel est suivi d'une ligne `<system-reminder>…`, d'un `tool_result`, d'une ligne `isMeta` et d'un `<task-notification>` → `/api/thread` renvoie le vrai message dans `me`.

- [ ] **Step 2: Lancer** `python3 -m unittest tests.test_thread tests.test_server.ThreadDemoTest -v` → échec (module absent).
- [ ] **Step 3: Écrire `thread.py`** (`last_exchange`, `screen_excerpt`, `register(srv)`), et ajouter `"thread"` à la liste de `load_modules()` dans `server.py`.
- [ ] **Step 4: Lancer** `python3 -m unittest tests.test_thread tests.test_server.ThreadDemoTest -v` → `ok`.
- [ ] **Step 5: Commit** `git commit -m "thread: dernier message de toi et de l'agent (/api/thread)"`

---

### Task 3: Approbations (`approve.py`) : état et `POST /api/approve`

**Files:**
- Modify: `approve.py` (ajout de `annotate` et `register`), `tests/test_approve.py` (classe `RouteTest`), `server.py` : dans `build_state()` (`server.py:452-468`), chaque agent reçoit `"kind": t["status"].get("kind")` ; `load_modules()` ajoute `"approve"` ; nouvelle fonction `hc_keys(addr: str, key: str) -> str|None` (lance `[HC, "keys", addr, key]` — ou la séquence validée à la tâche 1 —, délai 10 s, renvoie le message d'erreur lu comme dans `send_route` (`json.loads(r.stdout)["error"]["message"]`, `server.py:675-678`) ou `None` ; en démo, écrit dans `out.log`).

**Faits relevés :** `hc_keys` n'existe pas encore ; `SEND_LOCK`, `SENT`, `SENTF`, `LOCK` existent (`server.py:596-599`, `134`). Pour une session `blocked`, `q` vaut `{"carry": …}` ou `None` (`server.py:467`) : **jamais de `q.open`**. `send_check` refuse tout état autre que `done` (`server.py:615-617`) : une session `blocked/question` ne peut pas recevoir de texte par `/api/send` (voir tâche 6).

**Interfaces:**
- Consumes: `parse_permission`, `menu_hash`, `check_approval` (tâche 1, même module) ; `srv.read_screen`, `srv.snapshot`, `srv.main_agent`, `srv.paired`, `srv.hc_keys`, `srv.SNAPSHOT_HOOKS` (appelés `fn(terms, agents)`, exceptions journalisées, `server.py:473-477`), `srv.SENTF`, `srv.LOCK`, `srv.SEND_LOCK`. Un handler `POST` est appelé `fn(handler, body: str)` (corps déjà décodé UTF-8, `server.py:842-845`, `888-889`).
- Produces:
  - Hook `annotate(terms, agents)` : pour tout agent `status == "blocked"` et `kind == "permission"`, ajoute `a["perm"] = {**p, "screen_hash": menu_hash(p)}` (`p = parse_permission(read_screen(addr))`), ou `{"options": [], "screen_hash": None}` si non reconnu ou illisible. Écran relu à chaque construction de l'état, comme `questions_for` le fait déjà pour chaque session `done` (`server.py:333`) : pas de cache, donc pas de demande périmée affichée.
  - `POST /api/approve` corps JSON `{"address", "key", "screen_hash"}` → `{"ok": true, "label": …}` ou `{"error": …}` (HTTP 200 comme `/api/send`). Non appairé → `{"error": "appareil non appairé…"}` (même texte que `send_route`, `server.py:666`). Sous `SEND_LOCK` : terminal relu dans `srv.snapshot()` et refusé s'il n'est pas `srv.main_agent(t)` (même liste blanche que `send_check`), puis `check_approval(t.status.state, t.status.kind, read_screen(addr), key, screen_hash)`. Journal `sent.jsonl` : `{"ts", "address", "space", "approve": key, "label", "role"}` (+ `"error"` si `hc keys` échoue, comme `send_route`). Anti double appui : `APPROVED[address] = (status_ms, screen_hash)` posé après un envoi réussi ; même couple une seconde fois → `{"error": "déjà envoyé"}` sans appeler `hc_keys` (le `status_ms` évite de bloquer une demande identique posée plus tard).

- [ ] **Step 1: Tests (RED)** (`tests/test_approve.py`, classe `RouteTest`, écrans de `demo/screens/`) :

```python
def test_annotate_adds_perm(self):
    a = [{"address": "t1", "status": "blocked", "kind": "permission", "since_ms": 5}]
    approve.annotate([], a)  # via srv.read_screen -> perm-bash.txt
    self.assertEqual(a[0]["perm"]["options"][0]["role"], "approve")
    self.assertTrue(a[0]["perm"]["screen_hash"])

def test_annotate_unrecognised_menu(self): ...       # plain.txt -> options == [], screen_hash None
def test_approve_requires_pairing(self): ...         # paired=False -> "non appairé", srv.keys_sent == []
def test_approve_refuses_changed_screen(self): ...   # hash "x" -> error "a changé", keys_sent == []
def test_approve_refuses_unknown_session(self): ...  # adresse absente du snapshot -> erreur, keys_sent == []
def test_approve_twice_sends_once(self):
    h = good_request(); post(h); r = post(h)
    self.assertEqual(len(srv.keys_sent), 1); self.assertIn("déjà", r["error"])
def test_approve_logs(self): ...                     # dernière ligne de SENTF a "approve": "1", "role": "approve"
```

- [ ] **Step 2: Lancer** `python3 -m unittest tests.test_approve.RouteTest -v` → échec.
- [ ] **Step 3: Écrire** `annotate` / `register` dans `approve.py` et les ajouts de `server.py` listés ci-dessus.
- [ ] **Step 4: Lancer** `python3 -m unittest tests.test_approve -v` → tout `ok`.
- [ ] **Step 5: Vérification réelle sur le M5** après déploiement : refaire le scénario de la tâche 1 ; `curl -s localhost:8766/api/state` (port du déploiement M5, `scripts/install-failover.sh:3`) montre `perm` ; `curl -X POST -d '{"address":"…","key":"<No>","screen_hash":"…"}' localhost:8766/api/approve` → la demande est refusée dans le terminal.
- [ ] **Step 6: Commit** `git commit -m "approve: approuver / refuser les demandes d'autorisation"`

---

### Task 4: Voix (`voice.py`) et installation de Whisper sur le M5

**Files:**
- Create: `voice.py`, `tests/test_voice.py`, `tests/fake_whisper.sh`, `tests/fake_ffmpeg.sh`
- Modify: `server.py` : `load_modules()` ajoute `"voice"`. Rien d'autre : l'audio passe par la table `ROUTES["POST"]` existante (voir ci-dessous).

**Fait relevé :** `do_POST` décode tout corps en texte (`self.rfile.read(n).decode()`, `server.py:888-889`) : un corps binaire brut y lèverait `UnicodeDecodeError`. Plutôt qu'un nouveau point d'extension `ROUTES["POST_RAW"]`, la page envoie l'audio **encodé en base64 dans du JSON** sur la route `POST` ordinaire : aucun changement de `do_POST`, +33 % de volume (≤ 6,7 Mo pour 5 Mo d'audio, sur loopback / tunnel). Écart assumé avec la formulation du spec (« corps : l'audio brut ») ; le reste du contrat (60 s, 5 Mo, appairage, verrou, nettoyage) est inchangé. Écart assumé aussi : la disponibilité de la voix est donnée par `GET /api/voice` et non par un champ `voice` de `/api/state`, pour ne pas toucher `build_state()` (qui ne renvoie que `now_ms`, `agents`, `links`, `server.py:478`).

**Interfaces:**
- Produces:
  - `MAX_BYTES = 5 * 1024 * 1024`, `MAX_SECONDS = 60`.
  - `conf(state_dir: str) -> dict` : `whisper.json` fusionné sur `{"bin": "/opt/homebrew/bin/whisper-cli", "ffmpeg": "/opt/homebrew/bin/ffmpeg", "model": "~/.local/share/miniguet/whisper/ggml-large-v3-turbo-q5_0.bin"}` (chemins `~` développés).
  - `available(c: dict) -> bool` : les trois fichiers existent.
  - `class VoiceError(Exception)` (message en français).
  - `transcribe(audio: bytes, c: dict, scratch: str, timeout: int = 60) -> str` : refuse au-delà de `MAX_BYTES` ; écrit `scratch/<uuid>.in` (0600, `scratch` = `srv.SCRATCH`, déjà 0700, `server.py:47-48`), `ffmpeg -y -i in -t 60 -ar 16000 -ac 1 out.wav`, `whisper-cli -m model -l fr -nt -np -f out.wav`, renvoie la sortie nettoyée (lignes jointes par un espace) ; supprime les fichiers dans un `finally` ; un verrou module (`threading.Lock`) : un seul transcodage à la fois.
  - `GET /api/voice` → `{"available": bool}` ; `POST /api/transcribe` corps `{"audio": "<base64>", "type": "audio/mp4"}` → `{"text"}` ou `{"error"}` ; exige `srv.paired(h)` ; refuse un corps base64 de plus de `ceil(MAX_BYTES / 3) * 4` caractères avant décodage.

- [ ] **Step 1: Tests (RED)** avec `tests/fake_ffmpeg.sh` (copie son entrée vers son dernier argument) et `tests/fake_whisper.sh` (imprime `bonjour le monde`, ou dort 5 s si `FAKE_SLEEP=1`), passés par `c["ffmpeg"]` / `c["bin"]` : aucun test ne dépend d'un vrai `ffmpeg` :

```python
def test_transcribe_returns_text(self): ...          # == "bonjour le monde"
def test_transcribe_rejects_too_big(self):
    with self.assertRaises(VoiceError): transcribe(b"x" * (MAX_BYTES + 1), c, d)
def test_transcribe_timeout_cleans_up(self):
    # FAKE_SLEEP=1, timeout=1 -> VoiceError("délai"), os.listdir(scratch) == []
def test_transcribe_missing_binary(self):
    # c["bin"] = "/nope" -> VoiceError, available(c) is False
def test_route_requires_pairing(self): ...
def test_route_rejects_oversized_body(self): ...   # base64 trop long -> {"error"}, rien écrit dans SCRATCH
```

- [ ] **Step 2: Lancer** `python3 -m unittest tests.test_voice -v` → échec.
- [ ] **Step 3: Écrire `voice.py`** et l'ajout de `server.py`. `demo/seed/whisper.json` pointe vers `tests/fake_ffmpeg.sh` / `tests/fake_whisper.sh` et un fichier modèle factice, pour que la tâche 7 se vérifie en démo.
- [ ] **Step 4: Lancer** `python3 -m unittest tests.test_voice -v` → tout `ok`.
- [ ] **Step 5: Installer sur le M5** (installer ffmpeg explicitement : whisper-cpp ne le garantit pas) : `ssh kevin@100.75.247.49 'brew install whisper-cpp ffmpeg && mkdir -p ~/.local/share/miniguet/whisper && curl -L -o ~/.local/share/miniguet/whisper/ggml-large-v3-turbo-q5_0.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin'`. Vérifier : `whisper-cli -m … -l fr -f /opt/homebrew/share/whisper-cpp/jfk.wav` (ou un court WAV enregistré) transcrit en moins de 5 s.
- [ ] **Step 6: Commit** `git commit -m "voice: transcription locale par Whisper (/api/transcribe)"`

---

### Task 5 (lot B): ui-sdk copié, coquille de la nouvelle page et regroupement

**Files:**
- Create: `index-classic.html` (copie exacte de l'actuelle `index.html`, **avant** toute réécriture), `assets/ui-sdk/0.1.0-beta.1/` (copie intégrale de `package/browser/` de `@ui-sdk/web@0.1.0-beta.1` : `web.js`, `web.css`, `web/*.js`, `web/chunks/*.js`, + `LICENSE` Apache-2.0 du paquet), `assets/app/style.css`, `assets/app/api.js`, `assets/app/groups.js`, `assets/app/app.js`, `tests/js/groups.test.mjs`
- Modify: `index.html` (réécrite : coquille)

**Faits relevés (ui-sdk 0.1.0-beta.1, build navigateur) :** autonome — aucune URL réseau dans `web.js`, `web/`, `web.css` hors l'espace de noms SVG et des icônes en `data:` ; `web.js` définit chaque élément à la première apparition de son tag en important `web/<entrée>.js` **relativement à sa propre URL**, et les entrées importent `./chunks/*.js` : copier le dossier tel quel, côte à côte (`docs/installation.md` § « Without a Build Step »). Pas d'entrée `agent` ni `toast()` / `createToaster` publics dans ce build (voir tâches 6 et 9).

**Interfaces:**
- Consumes: tâche 0 (assets en sous-dossiers, mode démo). `/api/state` → `{now_ms, agents, links}` (`server.py:478`) ; champs d'un agent (`server.py:452-470`) : `address, space, tab, title, agent, status, msg, since_ms, unseen, cwd, deadline ({date, note}|null), dismissed, subagents, stalled_min, q, snooze ({until}|null), snoozed` + `kind` et `perm` (tâche 3) ; agents de l'ancien herdr : `source` présent. `status` ∈ `idle, working, done, blocked, error` (schéma `hc`).
- `groups.js` exporte :
  - `GROUPS = [{id: "error", label: "En erreur"}, {id: "approve", label: "Attend ton feu vert"}, {id: "question", label: "Te pose une question"}, {id: "review", label: "A fini, à relire"}, {id: "working", label: "Travaille"}, {id: "snoozed", label: "Reportées"}]`
  - `groupOf(agent, nowMs) -> id` selon le tableau du spec, complété pour les états qu'il ne cite pas : snooze actif (`snooze.until > now`, comme `snz`, `index.html:191`) → `snoozed` ; `error`, ou `blocked`+`auth` → `error` ; `blocked`+`permission` → `approve` ; `blocked` avec `kind` `question` **ou absent** → `question` ; `done` avec au moins une question ouverte visible → `question` ; autre `done` → `review` ; `working` et `idle` → `working`. « Visible » = `q.open` / `q.todo` moins les points retirés ou reportés en attente de confirmation, comme `vis()` (`index.html:198`).
  - `grouped(agents, nowMs) -> [{id, label, items}]` : groupes non vides dans l'ordre de `GROUPS` ; dans chaque groupe, échéance aujourd'hui / en retard d'abord, puis plus récent d'abord (`since_ms` décroissant).
  - `waitingCount(agents, nowMs) -> number` : même règle que le compteur actuel `needs()` (`index.html:200` : `error`, ou `done` avec analyse absente / en cours / en erreur, questions ou tâches visibles), plus les `blocked` (feu vert, question, connexion). Une session `done` analysée sans rien d'ouvert est rangée dans `review` mais n'est pas comptée (spec : « comme le compteur actuel »).
  - `badge(agent) -> {text, tone}` (« AUTORISATION », « 2 QUESTIONS », « QUESTION » pour `blocked/question`, « TERMINÉ », « ERREUR », « CONNEXION REQUISE », « TRAVAILLE ») et `summary(agent) -> string` (`perm.detail`, première question ouverte, ou `msg`).
- `api.js` exporte `getState()`, `getThread(address)`, `post(path, body)`, `transcribe(blob)` (lit le blob en base64, `POST /api/transcribe {audio, type}`), `voiceAvailable()` ; chaque appel renvoie l'objet JSON ou lève `Error(message)`.

**Exists to satisfy :** `groups.js` → spec §Les groupes ; `api.js` → un seul endroit pour la forme `{error}` des réponses ; `app.js` → polling, liste, en-tête ; `style.css` → contraste, tactile, thèmes.

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
test("idle goes to working", ...)
test("blocked without kind goes to question", ...)
test("done analysed with nothing open is review but not counted", ...)
```

(Champs réels : `q.open` et `q.todo`, listes de textes déjà filtrées par `filt()` côté serveur, `server.py:114-124` ; `q.pending` / `q.error` pendant ou après une analyse ratée.)

- [ ] **Step 2: Lancer** `node --test tests/js/groups.test.mjs` → échec.
- [ ] **Step 3: Écrire `groups.js`, `api.js`.**
- [ ] **Step 4: Lancer** `node --test tests/js/groups.test.mjs` → `ok`.
- [ ] **Step 5: Copie ui-sdk, coquille** : `index-classic.html` d'abord ; puis `index.html` = en-tête (logo, « À toi N », pastille ⏰, Rafale, Statistiques, Daily, menu `⋯`), `<nav id="list">`, `<section id="detail">`, `<link rel="stylesheet" href="/assets/ui-sdk/0.1.0-beta.1/web.css">` puis `/assets/app/style.css` (qui commence par `@layer ui-sdk;` ; jetons `--ui-*` et de groupe sombre / clair sur `:root` et `[data-theme=light]`), `<script type="module" src="/assets/ui-sdk/0.1.0-beta.1/web.js">`, `<script src="/assets/sound.js">`, `<script type="module" src="/assets/app/app.js">` — chemins absolus (voir Global Constraints). Menu `⋯` = `ui-menu > ui-menu-trigger > button[aria-label="Plus d'options"]` + `ui-menu-content > ui-menu-item[value]`, commande lue dans l'événement `action` du `ui-menu`. Groupes repliables `working` et `snoozed` = `ui-collapsible > ui-collapsible-trigger > button` + `ui-collapsible-panel`, fermés par défaut. `app.js` : polling `getState()` toutes les 2 s (comme `setInterval(tick,2000)`, `index.html:509`), rendu de la liste groupée, bandeau « Mac injoignable » avec la règle actuelle (`down()` : dernier appel en échec ou pas de réponse depuis 15 s, `index.html:485`), liens de l'en-tête `links`.
- [ ] **Step 6: Vérifier (exige la tâche 0)** : `MINIGUET_DEMO=demo python3 server.py --port 8799`, ouvrir `http://localhost:8799` avec Playwright à 1180×820 : aucune requête en échec dans l'onglet réseau (chunks ui-sdk compris), les 6 groupes de la démo apparaissent dans l'ordre, chaque ligne ≥ 64 px ; `http://localhost:8799/classic` affiche l'ancienne page ; `http://localhost:8799/stats` charge la nouvelle page sans erreur de chemin.
- [ ] **Step 7: Commit** `git commit -m "Nouvelle page: coquille, liste groupee par attente, ui-sdk copie"`

---

### Task 6: Panneau de session : fil, carte de réponse, section « Plus »

**Files:**
- Create: `assets/app/detail.js`, `assets/app/reply.js`, `tests/js/reply.test.mjs`
- Modify: `assets/app/app.js`, `assets/app/style.css`

**Interfaces:**
- Consumes: `getThread`, `post` (tâche 5) ; `/api/send` `{address, text, questions, since_ms}` (inchangé) ; `/api/approve` (tâche 3) ; `/api/snooze`, `/api/snooze-item`, `/api/deadline`, `/api/dismiss` (retirer et remettre), `/api/info`, `/api/resume` (inchangées : reprendre les corps exacts envoyés par `index-classic.html`).
- Produces:
  - `reply.js` : `composeMessage(free: string, answers: [{question, choice: "Oui"|"Non"|"", text}]) -> string` — portage à l'identique de `compose()` + `ansOf()` (`index.html:394-397`) : réponse = `choice + ", " + text` si les deux, sinon celui qui existe ; lignes `"<i>. <question> → <réponse>"` numérotées sur les **seules questions répondues** (l'appelant passe `answered(x)`, `index.html:395`, `427`) ; résultat = texte libre puis `"Réponses :\n" + lignes`, séparés par une ligne vide, parties vides omises. État des brouillons `DRAFTS: Map<address, {free, answers}>` conservé entre les rafraîchissements.
  - `detail.js` : `renderDetail(agent, thread, el)` ; texte des agents inséré avec `textContent` uniquement.
  - Retour d'action (succès / erreur / « Annuler » d'un retrait) : **pas de `ui-toast`** — le build navigateur n'exporte ni `toast()` ni `createToaster` (`web/toast.js` n'exporte rien ; l'`api` de `ui-toast-region` n'offre que `focus/pause/resume`) et la référence `references/web-components.md` du skill précise que `core.js` n'a pas `toast()`. On garde l'élément de l'ancienne page (`#toast` avec `#tmsg`, « Annuler », « × », `index.html:156`), restylé, avec `role="status"` (rôle hors de la liste que ui-sdk interdit d'écrire à la main).

**Exists to satisfy :** `reply.js` → « même texte assemblé qu'aujourd'hui » (spec) et Review Focus 4 ; `detail.js` → spec §Le panneau de droite.

- [ ] **Step 1: Tests JS (RED)** (`tests/js/reply.test.mjs`) : `composeMessage` produit exactement le texte de l'ancienne page pour 3 cas (Oui/Non seuls, texte libre en tête, précision après un Non) — textes attendus relevés en exécutant l'ancienne fonction dans Node.
- [ ] **Step 2: Lancer** `node --test tests/js/reply.test.mjs` → échec ; **Step 3:** écrire `reply.js` ; **Step 4:** `node --test tests/js/reply.test.mjs` → `ok`.
- [ ] **Step 5: Écrire `detail.js`** : en-tête de session ; deux bulles (toi à droite, agent à gauche, « (écran) » si `screen`, rien si `agent` est `null`), « Voir tout » si `truncated` ; carte d'action selon `groupOf` : *approve* → détail en chasse fixe + boutons par option (`ui-button > button`, texte = « Approuver » / « Toujours » / « Refuser » selon `role`, vert / neutre / rouge), appel `/api/approve` avec `perm.screen_hash`, désactivés pendant l'envoi (`disabled` sur `ui-button`), résultat dans `#toast` ; options vides → texte « Réponds dans le terminal : menu non reconnu » ; *question* d'une session `done` → par question ouverte un `ui-toggle-group aria-label="<question>"` contenant `ui-toggle value="Oui" > button` et `ui-toggle value="Non" > button` (sans `multiple` : un seul actif ; ré-appui = aucun, comportement par défaut, `deselectable` laissé vrai ; valeur lue dans `valuechange`), un `ui-field` + `ui-textarea > textarea` + emplacement du bouton micro (tâche 7), bouton « Aperçu et envoi » ouvrant un `ui-dialog` (`ui-dialog-content hidden` > `ui-dialog-title`, `ui-textarea` avec le texte de `composeMessage` modifiable, `ui-dialog-close > button` « Annuler ») puis « Envoyer » (`/api/send`, `since_ms` = `agent.since_ms`, avertissements de `sendWarn`, `index.html:399-400`) ; *question* d'une session **`blocked`** (pas de `q.open`, et `/api/send` refuse tout état autre que `done`) → dernière fin d'écran (`/api/thread`) et texte « Réponds dans le terminal : l'agent attend un choix dans son menu » ; *review/error* → textarea + micro + envoi ; ancien herdr (`source`) → « Répondre : ancien herdr, non supporté » (`index.html:406`) ; section « Plus » (`ui-collapsible`, fermée) avec À faire, Déjà traité, Retirées (`/api/dismiss` avec `undo`, `server.py:854-866`), Reprendre le fil (`/api/resume`), Plus d'infos (`/api/info`), Reporter (`/api/snooze`, `/api/snooze-item`), Échéance (`/api/deadline` `{address, date, note}`, `server.py:869-882`) portés depuis `index-classic.html`.
- [ ] **Step 6: Vérifier dans le navigateur (démo, Playwright 1180×820 et 820×1180 ; exige les tâches 0, 2 et 3)** :
  - `escapes agent html` : un transcript de démo contient `<b>gras</b>` → affiché littéralement.
  - `keeps selection and draft across refresh` : ouvrir une session, cocher Non, taper « test », attendre 5 s (2 rafraîchissements) → même session ouverte, Non coché, « test » présent.
  - Approuver sur la session démo → `demo/out.log` contient `keys <adresse> 1` ; second appui → message « déjà envoyé ».
  - Session `blocked/question` : pas de champ d'envoi, texte « Réponds dans le terminal ».
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
- Produces: `micButton(textarea: HTMLTextAreaElement) -> HTMLElement | null` (null si `!navigator.mediaDevices || !window.MediaRecorder` ou voix indisponible). Bouton `ui-button > button[aria-label="Dicter"]`. États : repos (🎙), enregistrement (rouge, minuterie `0:12`, arrêt auto à 60 s), transcription (indicateur), erreur (`#toast`, voir tâche 6).

**Exists to satisfy :** spec §Côté serveur 3, côté page. Le texte est **ajouté** au contenu du textarea (séparé par un espace), curseur à la fin, focus rendu au textarea ; jamais d'envoi.

- [ ] **Step 1: Écrire `voice.js`** (`MediaRecorder` avec le type par défaut du navigateur ; `Blob` envoyé tel quel) et l'intégrer aux cartes *question* et *review/error*.
- [ ] **Step 2: Vérifier en démo (exige la tâche 4)** (Playwright avec un faux micro : `--use-fake-device-for-media-stream`) : appui, attente 2 s, appui → le textarea contient le texte du faux whisper (`demo/seed/whisper.json`) ; sans `whisper.json` valide → pas de bouton.
- [ ] **Step 3: Vérifier sur l'iPad** après déploiement : dicter « oui vas-y et relance les tests » → texte correct dans le champ en moins de 5 s.
- [ ] **Step 4: Commit** `git commit -m "Voix: bouton micro, transcription Whisper ajoutee au champ"`

---

### Task 8: Rafale, mode bureau, menu `⋯`, sons, surimpressions Stats / Daily

**Files:**
- Create: `assets/app/rafale.js`, `assets/app/desk.js`
- Modify: `assets/app/app.js`, `index.html`, `assets/app/style.css`

**Interfaces:**
- Consumes: `grouped`, `waitingCount`, `badge` (tâche 5) ; `composeMessage`, `DRAFTS` (tâche 6) ; `micButton` (tâche 7) ; `assets/sound.js` inchangé, chargé en script classique, API `window.MG.sound` (`assets/sound.js:90-115`) : `chime(kind)` avec `kind` ∈ `new | deadline | error | wake`, `toggleSound()`, `toggleMusic()`, `soundState()` / `musicState()` (`"off" | "on" | "locked"`), `onChange(fn)`, `restore()` (une fois au chargement).
- Produces: `openRafale()` ; `toggleDesk()`.

**Exists to satisfy :** anti-objectif « perdre une fonction existante » (Rafale, mode bureau, sons, surimpressions) ; spec : la Rafale inclut les autorisations.

- [ ] **Step 1: Rafale** en `ui-dialog` plein écran : file = demandes d'autorisation puis questions ouvertes (ordre des groupes) ; carte autorisation = mêmes boutons que la tâche 6 (envoi immédiat) ; carte question = Oui / Non / Autre (textarea + micro) ; Passer (reporte d'1 h via `/api/snooze-item`, comme aujourd'hui) ; Plus pertinent ; récapitulatif modifiable avant tout envoi, « Tout envoyer ».
- [ ] **Step 2: Mode bureau** (`desk.js`) : porté de `index-classic.html` (gros chiffre `waitingCount`, assombri la nuit, Wake Lock), couleur = groupe le plus urgent non vide.
- [ ] **Step 3: Menu `⋯`** (`ui-menu`, items `value="desk" | "sound" | "music" | "theme"`) : Mode bureau, Sons, Musique, Thème clair / sombre (mémorisé en `localStorage`, dans un try/catch). Sons : porter la détection de nouveauté de `render()` (`index.html:330-338` : clé `adresse:since_ms`, `chime("error" | "deadline" | "new")`, rien quand `down()`) ; une session qui arrive dans `approve` compte comme nouvelle et sonne `new` (pas de nouveau son : `sound.js` reste inchangé).
- [ ] **Step 4: Stats / Daily** en surimpression (iframe `?embed=1`), porté de `showFrame` / `openFrame` / `closeFrame` et de l'ouverture au chargement quand `location.pathname` est `/stats`, `/daily` ou `/daily/history` (`index.html:164-175`) ; routes inchangées ; la musique continue pendant l'ouverture.
- [ ] **Step 5: Vérifier en démo** : Rafale passe par une autorisation puis deux questions, récapitulatif, envoi → `demo/out.log` ; mode bureau affiche le compte ; thème clair appliqué et mémorisé après rechargement ; ouvrir/fermer Stats ne coupe pas la musique.
- [ ] **Step 6: Commit** `git commit -m "Rafale, mode bureau, menu, sons et surimpressions dans la nouvelle page"`

---

### Task 9: Accessibilité, contraste, parité, déploiement

**Files:**
- Modify: `README.md`, `assets/app/style.css` si un contraste échoue

**Fait relevé :** le test « agent » du skill (`references/agent-ready.md`, « Prove it with a test ») utilise `createAgent` de `@ui-sdk/web/agent` sous Vitest + jsdom. Le build navigateur n'a pas d'entrée `agent` (`browser/web/` n'a pas d'`agent.js`), et `dist/agent.js` importe le nom nu `@ui-sdk/core/agent` : il faudrait npm + un bundler, exclus par le spec (« pas de Node ni d'étape de build »). On garde l'intention du test (chaque contrôle trouvable par son nom, unique là où il est) en le faisant dans le vrai navigateur.

- [ ] **Step 1: Noms accessibles** (Playwright sur la démo) : `getByRole("button", {name})` trouve exactement un contrôle pour « Approuver », « Refuser », « Oui », « Non », « Aperçu et envoi », « Dicter », « Plus d'options », « Rafale » dans la session ouverte ; aucun `button` / `textarea` sans nom accessible (`page.accessibility.snapshot()` parcouru) ; les boutons d'envoi portent `data-agent-confirm` (« Envoie le message à l'agent », « Approuve la demande dans le terminal »).
- [ ] **Step 2: Contraste** : script Playwright qui calcule le ratio de chaque texte et bord de contrôle visible en sombre et en clair (formule WCAG) → aucun texte < 4,5, aucun bord / focus / fond d'état < 3. Corriger les jetons fautifs.
- [ ] **Step 3: Clavier** : Tab parcourt en-tête, liste, carte d'action dans l'ordre ; focus visible partout ; Échap ferme les dialogues.
- [ ] **Step 4: Parité** — vérifier chaque point en démo puis sur l'iPad : reporter une session (toutes les options) et un point ; échéance (boutons, date, note) ; retirer / remettre un point, « Tout retirer » ; Plus d'infos ; Reprendre le fil ; Rafale ; mode bureau ; sons et musique (déverrouillage au premier appui) ; Stats / Daily en surimpression ; bandeau « Mac injoignable » (couper le serveur démo) ; sessions bloquées 30 min signalées ; sessions de l'ancien herdr (`source`) avec « Répondre : non supporté » ; liens de l'en-tête (`links`) ; pastille « ⏰ Daily prêt ».
- [ ] **Step 5: README** : section Whisper (installation de `whisper-cpp` **et** `ffmpeg`, `whisper.json`), mode démo, `/classic` (retrait prévu le 2026-11-27), commandes de test par module : `python3 -m unittest tests.test_server tests.test_approve tests.test_thread tests.test_voice -v` et `node --test tests/js/groups.test.mjs tests/js/reply.test.mjs`.
- [ ] **Step 6:** relancer, avec ces sélecteurs explicites, les seuls tests écrits pour cette refonte : `python3 -m unittest tests.test_server tests.test_approve tests.test_thread tests.test_voice -v && node --test tests/js/groups.test.mjs tests/js/reply.test.mjs` → tout `ok`.
- [ ] **Step 7: Commit, push, déployer** : `git commit -m "Refonte: accessibilite, contraste, README" && git push && scripts/deploy.sh kevin@100.75.247.49` ; vérifier `https://miniguet.herembourg.fr` sur l'iPad.

---

## Consequential decisions

1. **Nouvelles routes publiques et champs de `/api/state`** (`/api/thread`, `/api/approve`, `/api/voice`, `/api/transcribe` ; `kind` et `perm` par agent). *Ajoute* un contrat que la page (et tout autre client de `/api/state`) suit. *Satisfait* spec §Côté serveur 1-3. *Coût* : quatre routes à garder compatibles ; `annotate` relit l'écran (`hc read`, ≤ 3 s) de chaque session `blocked/permission` à chaque construction de l'état. *Moins cher* : la voix par un champ `voice` de `/api/state` (spec) — écarté pour ne pas toucher `build_state()` ; un cache par blocage — écarté car il affichait une demande périmée quand Claude en enchaîne une autre.
2. **`screen_hash` aller-retour entre `/api/state` et `/api/approve`, calculé sur le menu lu**. *Ajoute* un invariant : le hash d'`annotate` et celui de la vérification doivent sortir de la même fonction (`menu_hash`) sur la même lecture (`parse_permission`). *Satisfait* l'anti-objectif « un Approuver ne valide jamais une autre demande que celle affichée ». *Coût* : une demande identique au caractère près serait confondue (sans risque : même commande, même choix). *Moins cher* : comparer seulement les libellés d'options — ne détecte pas une autre commande avec le même menu.
3. **Anti double appui `APPROVED[address] = (status_ms, hash)`**, en mémoire. *Ajoute* un second registre à côté de `SENT` (`server.py:599`), même principe. *Satisfait* Review Focus 1. *Coût* : quelques lignes. *Moins cher* : réutiliser `SENT` — impossible tel quel, `SENT` bloquerait ensuite `/api/send` pour le même `status_ms`.
4. **Service d'`/assets/` en sous-dossiers** (remplace `os.path.basename`, `server.py:923`). *Change* une défense existante contre la traversée de chemin. *Satisfait* « aucun script d'un CDN » + ui-sdk qui charge `web/` et `web/chunks/` relativement. *Coût* : contrôle `realpath` sous `assets/` et tests de traversée (tâche 0). *Moins cher* : aucun — les imports `./chunks/*.js` du build interdisent d'aplatir.
5. **Mode démo dans `server.py`** (`MINIGUET_DEMO`). *Ajoute* des branches dans `snapshot`, `read_screen`, `transcript_path`, `hc_send`, `hc_keys`, `ask_sonnet`, `load_modules` et le chemin d'état. *Satisfait* spec §Tests (« données d'exemple servies par le serveur en mode démo »). *Coût* : code de démo dans le chemin de production ; doit couper `backup` (envoi vers D1) et `claude -p`. *Moins cher* : tester la page contre de fausses réponses servies par Playwright (`page.route`) — ne vérifie ni le serveur, ni `out.log`, ni la parité de bout en bout.
6. **Deuxième copie de la page (`index-classic.html`, `/classic`) pendant deux semaines.** *Ajoute* une copie de code. *Satisfait* spec §Mise en service. *Coût* : à supprimer le 2026-11-27 (route + fichier). *Moins cher* : revenir en arrière par `git revert` — plus lent en cas de souci sur l'iPad.
7. **Règle de regroupement en double** : `groups.js` (page) et `sections_route` (`server.py:751-765`, pour la barre latérale Herdr) décident chacun « qui attend ». *Ajoute* une seconde copie d'une règle partagée (l'ancienne `needs()` disparaît avec `/classic`). *Satisfait* spec §Les groupes, côté page comme aujourd'hui. *Coût* : les deux peuvent diverger (`sections_route` ne connaît pas `blocked`). *Moins cher* : calculer le groupe dans `build_state()` et le lire des deux côtés — change le contrat de `/api/state` et `sections_route` ; laissé hors périmètre.
