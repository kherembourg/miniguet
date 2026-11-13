<p align="center"><img src="assets/logo.png" alt="Miniguet" width="120"></p>

# Miniguet

Le « ministère du guet » de tes agents de code. Un tableau de bord web, pensé pour une tablette posée sur le bureau, qui montre **quelles sessions d'agents (Claude Code, Codex) attendent quelque chose de toi** : quelles questions, quelles tâches, depuis quand, avec quelle échéance. Il t'avertit d'un son doux quand une nouveauté arrive, te laisse répondre depuis la tablette, et garde la trace de ta journée (statistiques, résumé du daily).

> **Statut : prototype personnel, un seul utilisateur.** Écrit en quelques jours avec Claude, sans test automatisé, vérifié sur un seul Mac et une tablette Pixel (Chrome). Utilise-le comme point de départ, pas comme un produit.

## Ce que ça fait

**Voir ce qui t'attend**
- Une liste des sessions (un « space » Herdr = une session principale), les plus récentes en haut, avec un détail à droite : questions à trancher, tâches à faire, ce qui a déjà été traité.
- Les questions et tâches sont extraites de l'écran de chaque session par un modèle (`claude -p`), mémorisées d'un tour à l'autre, et retirées dès que tu y as répondu.
- Chaque point porte sa **date de création** (retrouvée dans le journal de la conversation) et un bouton **Plus d'infos** : contexte, ce qui s'est passé depuis, verdict « probablement réglé / périmé », avec la phrase qui le justifie.
- **Reprendre le fil** : résumé en 4 lignes d'une session (objectif, avancement, ce qui bloque, prochaine étape).
- Signale les sessions en erreur, celles qui semblent **bloquées** (écran figé depuis 30 min), et marque d'un « cli » les sessions de l'ancien herdr.

**Ne rien oublier**
- **Échéances** : une date par session, remontée en haut de la liste, rouge si c'est aujourd'hui ou en retard.
- **Snooze** (« Reporter ») d'une session ou d'un point : demain 10 h, dans 3 jours, lundi, une date, ou indéfiniment. Un point reporté ne se perd jamais.
- **Plus pertinent** : retire un point (avec annulation possible, et une section « Retirées » pour le remettre). « Tout retirer » en un geste.

**Agir depuis la tablette**
- **Répondre** : Oui / Non / texte libre (avec la dictée du clavier) pour chaque question, regroupé en un seul message envoyé dans le terminal de la session avec `hc send`, après un aperçu et une confirmation explicite.
- **Rafale** : une question à la fois, plein écran, avec le contexte, « Passer » (reporte d'une heure), « Plus pertinent », et un récapitulatif avant tout envoi.
- Garde-fous à l'envoi : refus si la session travaille, si une réponse est déjà tapée dans sa zone de saisie, si l'agent a avancé depuis l'aperçu, ou au-delà de 4 000 caractères. Chaque envoi est journalisé.

**Se repérer**
- **Mode bureau** : très gros chiffre coloré lisible de loin, qui s'assombrit la nuit et garde l'écran allumé.
- Bandeau « Mac injoignable » si le serveur ne répond plus, pastille « ⏰ aujourd'hui », bip différent selon la nouveauté (demande, échéance, erreur).
- **Sons** doux (synthétisés) et **musique d'ambiance** en boucle, mémorisés d'un rechargement à l'autre. Les pages Statistiques et Daily s'ouvrent par-dessus la page principale (adresses `/stats`, `/daily`, `/daily/history`) pour ne jamais couper la musique.

**Mesurer** (page `/stats`)
- Présence, conversation directe, temps de travail des agents (cumulé et réel), temps d'attente de toi, changements de contexte, sujets traités, plus longue série, **jetons et coût équivalent API** (tarifs modifiables). Les réunions du calendrier et les périodes de snooze sont retirées de l'attente.

**Préparer le daily** (page `/daily`)
- Chaque jour ouvré à 11 h 50, un résumé de la veille 12 h à maintenant : un **texte à dire à l'oral** (environ une minute et demie, sans codes ni numéros) et une section de **détails pour toi** (tickets Linear cliquables, décisions, chiffres). Historique consultable et exportable en Markdown sur `/daily/history`.

## Ce qu'il faut installer

| Élément | Pour quoi | Obligatoire |
|---|---|---|
| macOS | `launchd`, lecture de l'interface réseau | oui (non testé ailleurs) |
| [Herdr](https://herdr.dev) (application de bureau) et sa commande `hc` dans `~/.local/bin` | état et écrans des sessions, envoi de texte | oui |
| [Claude Code](https://claude.com/claude-code), commande `claude` connectée | extraction des questions, résumés, daily (appels `claude -p`) | oui |
| Python 3.9 ou plus (testé en 3.14) | le serveur n'utilise que la bibliothèque standard | oui |
| [Tailscale](https://tailscale.com) sur le Mac et sur la tablette | adresse fixe et privée, partout | non, recommandé |
| Connecteur **claude.ai Google Calendar** | retirer tes réunions des mesures de temps, heures de réunion du daily | non |
| Ancien CLI `herdr` (`/opt/homebrew/bin/herdr`) | afficher aussi ses sessions | non |
| Chrome sur la tablette | l'interface (sons, mode plein écran) | non |

## Installation

```bash
git clone https://github.com/romainsalles/miniguet.git
cd miniguet
python3 server.py              # http://127.0.0.1:8765
```

Au démarrage automatique (à l'ouverture de session, avec redémarrage en cas de plantage) :

```bash
scripts/install-launchd.sh     # écoute sur 127.0.0.1 et sur l'adresse Tailscale, jamais sur le réseau local
```

**Tablette ou second écran.**
1. Installe Tailscale sur le Mac et sur la tablette, avec le même compte.
2. Ouvre `http://<nom-du-mac>:8765` (le nom MagicDNS court de Tailscale) dans Chrome. Il ne change pas quand tu passes du bureau à la maison.
3. Chrome, menu ⋮, « Ajouter à l'écran d'accueil » : une icône Miniguet qui ouvre la page en plein écran.
4. **Appairage (une seule fois par appareil).** Pour répondre aux agents depuis la tablette, elle doit être appairée : sur le Mac, lance `scripts/pair-url.sh`, ouvre l'adresse affichée sur la tablette. Elle mémorise l'appareil (cookie). Le Mac lui-même n'a pas besoin d'être appairé.
5. Appuie une fois sur la cloche et sur la note : les navigateurs bloquent le son avant un premier appui, et après un rechargement le bouton clignote tant qu'il n'est pas rappuyé.

**Calendrier (facultatif).** Dans Claude Code, tape `/mcp`, choisis « claude.ai Google Calendar » et autorise. Miniguet lit uniquement les horaires, le type et le nombre de participants des événements (jamais les titres). Une réunion compte si elle a au moins 2 participants.

**Musique d'ambiance.** Dépose un fichier `assets/ambient.mp3` : il est lu en boucle à 30 % de volume. Aucun fichier n'est fourni (il est ignoré par git) : apporte le tien, libre de droits.

**Cloudflare Tunnel + Access (alternative à Tailscale, gratuite).** Pour joindre le tableau depuis n'importe où sans installer Tailscale sur les appareils : un tunnel Cloudflare publie `https://miniguet.<ton-domaine>` et **Cloudflare Access** (plan Zero Trust Free, jusqu'à 50 utilisateurs) exige une connexion (Google, code par e-mail…) avant d'atteindre le Mac.
1. Dans le tunnel (`~/.cloudflared/config.yml`), ajoute `- hostname: miniguet.<ton-domaine>` / `service: http://127.0.0.1:8765`, puis `cloudflared tunnel route dns <tunnel> miniguet.<ton-domaine>`.
2. Crée une application Access « self-hosted » sur ce nom, avec une règle *Allow* limitée à ton adresse.
3. Crée `~/.local/state/herdr-board/cloudflare.json` : `{"host": "miniguet.<ton-domaine>", "team": "<équipe>", "aud": "<AUD de l'application>", "emails": ["toi@exemple.com"]}` et redémarre le serveur.

Le serveur vérifie lui-même le jeton Access (signature, audience, expiration, e-mail) de toute requête arrivée par le tunnel et refuse le reste : sans `cloudflare.json`, tout ce qui passe par Cloudflare est refusé. Ces requêtes ne sont jamais traitées comme venant du Mac (bien que `cloudflared` se connecte depuis `127.0.0.1`) : envoyer du texte aux agents exige toujours l'appairage (`scripts/pair-url.sh` affiche alors l'adresse publique).

## Configuration

Tout l'état est dans `~/.local/state/herdr-board/` (ce dossier n'est pas dans le dépôt : il contient ton travail réel).

| Fichier | Contenu |
|---|---|
| `memory.json` | dernière analyse de chaque session |
| `deadlines.json`, `snooze.json`, `snooze_items.json`, `dismissed.json` | échéances, reports, points retirés |
| `snooze_log.jsonl`, `sent.jsonl` | historique des reports, journal de tout ce qui est envoyé aux agents |
| `daily/` | un fichier par jour, avec `versions/` pour les anciennes générations |
| `daily_config.json` | `time` (11:50), `skip_weekends`, `ignore_topics` (sujets exclus du daily), `linear` (bases d'URL des tickets, par exemple `{"ENG": "https://linear.app/mon-espace/issue/"}`) |
| `prices.json` (facultatif) | tarifs des modèles, remplace ceux du code (relevés le 2026-11-05 sur la page officielle) |
| `gcal.json`, `stats_names.json` | cache du calendrier, noms des sujets |
| `pair_token` (0600) | secret d'appairage des appareils distants : ne jamais le partager ni le sauvegarder |
| `backup_config.json`, `backups/mirror.sqlite` | configuration de la sauvegarde, copie locale chiffrée |
| `access.log`, `scratch/` | journal d'accès (0600), dossier de travail privé (0700) des appels `claude -p` |

## Sécurité

Le serveur **n'a ni mot de passe ni chiffrement** et peut envoyer du texte à tes agents, qui ont accès à ton code et à ta machine. Il est donc conçu pour n'être joignable que de toi :
- il n'écoute que sur `127.0.0.1` et sur l'adresse Tailscale (`--host tailscale`), jamais sur `0.0.0.0` ;
- il refuse toute requête dont le nom d'hôte n'est pas `localhost`, une adresse de loopback ou Tailscale, ou un nom Tailscale (contre le détournement de nom DNS), et toute requête venant d'une autre origine (contre une page web qui tenterait d'écrire vers `localhost`) ;
- **envoyer du texte à un agent exige l'appairage** : un appareil distant doit présenter le secret `pair_token` (cookie posé par l'adresse d'appairage) ; le Mac lui-même est exempté ;
- un message commençant par `!` (commande shell) ou `/` (commande slash) est refusé à l'envoi ;
- `--host 0.0.0.0` est refusé sauf `--allow-lan` ;
- les appels `claude -p` tournent dans un dossier privé, sans réglages de projet ni outils intégrés (`--setting-sources user --tools ""`) ;
- côté Tailscale, restreins l'accès à tes propres appareils.

**Ce qui sort de la machine.** Le texte des écrans de terminal et des extraits de conversation est envoyé à `claude -p` (donc à Anthropic) pour en extraire des questions et des résumés. Les journaux de conversation peuvent contenir des secrets collés : ne partage pas les fichiers d'état. Rien d'autre n'est envoyé ailleurs.

## Sauvegarde chiffrée

`backup.py` copie l'état (`~/.local/state/herdr-board`) vers une **copie locale chiffrée** (`backups/mirror.sqlite`) et, une fois configurée, vers une base **Cloudflare D1** (gratuite). Sur un compte Cloudflare partagé, tout administrateur peut lire une base D1 : tout est donc **chiffré sur le Mac avant l'envoi** (AES-256 + HMAC, clé dans le Trousseau macOS). D1 ne contient que du texte chiffré, des noms de fichiers hachés, des tailles et des dates. Chaque version modifiée d'un fichier est conservée ; un fichier inchangé n'est pas renvoyé. La sauvegarde tourne 2 minutes après le démarrage, puis toutes les 6 heures. `pair_token`, le journal d'accès, le cache du calendrier et le dossier de travail ne sont pas sauvegardés.

```bash
python3 backup.py status                 # clé, D1 configurée, dernière sauvegarde
python3 backup.py run                    # sauvegarde maintenant
python3 backup.py verify                 # télécharge, déchiffre, compare avec les fichiers
python3 backup.py restore --to /tmp/restauration [--at 2026-11-06] [--from d1]
python3 backup.py export-key             # clé de secours : à garder dans un gestionnaire de mots de passe
python3 backup.py setup --account <ID>   # crée la base D1 « miniguet » ; demande le jeton API (D1 Edit) sans l'afficher
```

**Perdre la clé = perdre les données** : elle seule déchiffre. La recherche texte se fait en local sur les fichiers en clair (la copie D1 n'est qu'une sauvegarde).

## Fonctionnement

- `server.py` : serveur HTTP, état, analyse des écrans, envoi, snooze, échéances. Points d'extension (`ROUTES`, `AGENT_SOURCES`, `SNAPSHOT_HOOKS`, `LINKS`) auxquels s'accrochent les modules ci-dessous.
- `oldherdr.py` : sessions de l'ancien CLI `herdr` (lecture seule).
- `stats.py` + `stats.html` : mesures, tirées des journaux de conversation (`~/.claude/projects`) ; `gcal.py` : réunions du calendrier.
- `daily.py` + `daily.html` + `daily-history.html` : résumé du daily.
- `index.html` : la page principale (JavaScript sans dépendance). `assets/` : logo, icônes, `sound.js`, musique.
- `cfaccess.py` : vérification des jetons Cloudflare Access (tunnel).
- `backup.py` : sauvegarde chiffrée. `launchd/`, `scripts/` : démarrage automatique, adresse d'appairage.

Les sessions principales et leurs écrans viennent de `hc events` et `hc read`. Le lien terminal, conversation passe par `~/.claude/sessions/<pid>.json`.

## Limites connues

- Prototype : pas de test automatisé, pas d'authentification, un seul utilisateur, un seul Mac.
- Codex n'est pas couvert par les statistiques ni les coûts, et la détection des brouillons ne reconnaît que l'invite de Claude Code.
- Les extractions et verdicts sont produits par un modèle : une aide, pas une vérité.
- Le son ne démarre qu'après un premier appui sur la page (règle des navigateurs).
- La musique ne traverse pas un rechargement de la page.

## Idées en attente

Recherche texte globale (index SQLite FTS5 local, reconstruit depuis les fichiers), liens cliquables dans les notes, ordre de traitement conseillé, réponses depuis l'ancien herdr.

## Licence

Aucune pour le moment : tous droits réservés.
