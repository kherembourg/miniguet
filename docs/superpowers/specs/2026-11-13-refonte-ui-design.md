# Refonte de l'interface de Miniguet : tablette, contraste, réponses rapides

Date : 2026-11-13 · Statut : à valider

## Pourquoi

Miniguet tourne sur une tablette posée sur le bureau (iPad, Safari ou app ajoutée à l'écran d'accueil, via
`https://miniguet.herembourg.fr`). Aujourd'hui, d'après l'utilisateur :

- on ne sait pas **quelle session attend quoi**, ni **qui a besoin de son retour** ;
- on ne voit ni **son dernier message** ni **la dernière réponse de la session** ;
- **ça manque de contraste**.

Il veut une interface plus belle et plus claire, **pensée pour le tactile**, et pouvoir **répondre vite** aux agents :
par boutons (Oui / Non, Approuver / Refuser), par texte, ou **à la voix**.

Réussite : un coup d'œil à la tablette dit qui attend quoi ; on comprend la situation d'une session sans ouvrir de
terminal ; on répond en un ou deux appuis.

## Objectifs

1. Disposition « A » (choisie sur maquette) : **liste à gauche, conversation à droite**, en paysage.
2. Liste **groupée par ce que la session attend**, avec une couleur et une étiquette par type.
3. Pour la session ouverte : **ton dernier message** et **la dernière réponse de l'agent**, sous forme de bulles.
4. **Approuver / Refuser** les demandes d'autorisation de Claude Code depuis la tablette.
5. **Oui / Non** par question, **texte libre**, et **message vocal** transcrit par **Whisper en local sur le M5**.
6. **Fort contraste** et **cibles tactiles** larges.

## Non-objectifs

- Pas de refonte des pages Statistiques et Daily (elles gardent leur style ; seul leur accès depuis l'en-tête change).
- Pas de changement du serveur au-delà de ce qui est listé plus bas.
- Pas de Node ni d'étape de build.
- Pas de statistiques ni de daily pour les sessions distantes (m1) : limite connue, inchangée.

## Anti-objectifs (ce qui ferait de la refonte un échec même si « ça marche »)

- **Perdre une fonction existante** : reporter (session et point), échéances, retirer / remettre un point, Plus d'infos,
  Reprendre le fil, Rafale, mode bureau, sons et musique, bandeau « Mac injoignable », pages Stats / Daily en
  surimpression (la musique ne doit pas se couper), mise en avant des sessions bloquées / en erreur.
- **Envoyer quelque chose qu'on n'a pas vu** : une transcription vocale ou un message ne part jamais sans être affiché
  et modifiable ; un Approuver ne doit jamais valider une autre demande que celle affichée.
- **Charger du code tiers à chaud** : cette page tape dans des terminaux, aucun script ne vient d'un CDN.
- **Dégrader la sécurité** déjà en place (Access, appairage par Tailscale, garde-fous d'envoi).

## Contraintes

- Serveur Python, **bibliothèque standard uniquement** ; le front est du HTML/JS sans dépendance installée.
- Déploiement : `git push` puis `scripts/deploy.sh kevin@100.75.247.49` (M5 principal, M1 en secours).
- Appareil cible : **iPad en paysage** (Safari / écran d'accueil). Doit rester utilisable sur Mac (Chrome) et en
  portrait (liste et conversation empilées).
- Le son ne démarre qu'après un premier appui (règle des navigateurs), comme aujourd'hui.
- `ui-sdk` est en **0.1.0-beta.1**, publiée le 2026-11-12 : jeune, donc copiée et figée dans le repo.

## Approches envisagées

1. **Réécrire `index.html` sans étape de build, avec les web components `ui-sdk` copiés dans le repo** — *retenue*.
   Garde l'esprit du projet (pas de Node, déploiement par `git pull`), et la disposition A change de toute façon la
   structure de la page.
2. Restyler la page actuelle par petites touches — écartée : la disposition A impose une autre structure, on aurait
   fini par tout réécrire dans du code plus emmêlé.
3. React + `@ui-sdk/react` avec Vite — écartée : ajoute Node et un build au projet et au déploiement pour une seule page.

## Décisions prises avec l'utilisateur

- Disposition **A** (liste + conversation).
- Voix : **Whisper en local sur le M5** (l'audio de travail ne part pas chez un tiers).
- Approche **1**.
- Les sessions passées par Cloudflare Access sont considérées appairées (déjà livré, commit `755293b`).

## Conception

### Vue d'ensemble de l'écran (iPad paysage)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 👁 Miniguet   À toi 5   ⏰ 1 aujourd'hui      [Rafale] [Stats] [Daily] [⋯]   │
├────────────────────────────┬─────────────────────────────────────────────────┤
│ ATTEND TON FEU VERT · 1    │ m5 · Android / Fleet doctor        ⟳ 9 min    │
│ ▌m5 · Android      4 min   │                                                 │
│ ▌[AUTORISATION] gradlew    │          ┌──────────────────────────────┐      │
│                            │          │ TOI · il y a 12 min          │      │
│ TE POSE UNE QUESTION · 2   │          │ Corrige le crash au lancement│      │
│ ▌Purchasely       12 min   │          └──────────────────────────────┘      │
│ ▌[2 QUESTIONS] Garder…     │ ┌────────────────────────────────────┐          │
│ ▌m1 · Development  46 min  │ │ AGENT · il y a 9 min               │          │
│ ▌[1 QUESTION] …            │ │ Deux choix avant de continuer…     │          │
│                            │ └────────────────────────────────────┘          │
│ A FINI, À RELIRE · 3       │ ┌ RÉPONDRE ───────────────────────────────────┐ │
│ ▌…                         │ │ 1. Faut-il … ?        [ Oui ] [ Non ]       │ │
│                            │ │ 2. Lancer … ?         [ Oui ] [ Non ]       │ │
│ TRAVAILLE · 4  (repliée)   │ │ [ Ton message…                    ] [ 🎙 ]  │ │
│ REPORTÉES · 2  (repliée)   │ │                       [ Aperçu et envoi → ] │ │
│                            │ └─────────────────────────────────────────────┘ │
│                            │ Plus : À faire · Déjà traité · Reprendre le fil │
│                            │        Reporter · Échéance                      │
└────────────────────────────┴─────────────────────────────────────────────────┘
```

### Les groupes de la liste (ce que la session attend)

Ordre d'affichage, de haut en bas :

| Groupe | Condition (côté serveur) | Couleur |
|---|---|---|
| **En erreur** | `status.state == "error"` | rouge |
| **Attend ton feu vert** | `state == "blocked"` et `status.kind == "permission"` | orange |
| **Te pose une question** | `state == "done"` avec au moins une question ouverte, ou `state == "blocked"` et `kind == "question"` | bleu |
| **A fini, à relire** | `state == "done"`, sans question ouverte (tâches ou rien) | gris clair |
| **Travaille** | `state == "working"` (repliée par défaut ; signale « bloquée depuis 30 min » comme aujourd'hui) | gris |
| **Reportées** | snooze actif (repliée, comme aujourd'hui) | gris |

`blocked` de type `auth` (connexion requise) va dans **En erreur** avec le texte « connexion requise ».
Les sessions avec échéance aujourd'hui / en retard gardent leur pastille ⏰ rouge et remontent **en tête de leur groupe**.

Chaque ligne : nom (`machine · espace / onglet`), âge, une **étiquette** colorée (« AUTORISATION », « 2 QUESTIONS »,
« TERMINÉ », « ERREUR ») et **une ligne de résumé** (commande demandée, première question, ou début de la dernière
réponse). Hauteur minimale 64 px, la ligne entière est cliquable.

Le chiffre « À toi » compte les groupes erreur + feu vert + question + à relire (hors reportées), comme le compteur actuel.

### Le panneau de droite (session ouverte)

1. **En-tête** : nom, âge, étiquette, pastille échéance / snooze, alerte « bloquée » le cas échéant.
2. **Fil** : deux bulles au plus, **ton dernier message** (à droite, bleu) puis **la dernière réponse de l'agent** (à
   gauche, sombre), avec l'heure relative. Texte tronqué à ~600 caractères avec « Voir tout » (dépliable). Rendu en
   texte brut (pas de Markdown interprété, pas de HTML).
3. **Carte d'action** selon le groupe :
   - *Feu vert* : la demande (outil + commande ou fichier, en police à chasse fixe) et les boutons du menu de Claude Code
     tels qu'affichés à l'écran : **Approuver** (vert), **Toujours** (si l'option « don't ask again » existe), **Refuser**
     (rouge). Un appui envoie la touche immédiatement (voir « Autorisations » plus bas).
   - *Question* : pour chaque question ouverte, **Oui / Non** (bascule, ré-appui pour annuler) ; dessous un **champ texte**
     unique et le **bouton micro** ; puis **Aperçu et envoi** qui ouvre l'aperçu modifiable existant (même texte assemblé
     qu'aujourd'hui), puis **Envoyer**.
   - *À relire / erreur* : champ texte + micro + envoi, pour relancer l'agent.
4. **Section « Plus »** (repliable, fermée par défaut) : À faire, Déjà traité, Reprendre le fil, Reporter, Échéance,
   Retirées, avec les comportements actuels.

En portrait ou sous 900 px de large : la liste occupe l'écran ; toucher une session ouvre le panneau en plein écran avec
un bouton « ← Sessions ».

### Rafale, mode bureau, en-tête

- **Rafale** garde son fonctionnement (une question à la fois, Passer, Plus pertinent, récapitulatif avant envoi), avec le
  nouveau style, le champ texte + micro, et elle **inclut les demandes d'autorisation** (cartes Approuver / Refuser).
- **Mode bureau** inchangé dans son principe (gros chiffre lisible de loin, assombri la nuit, écran gardé allumé), avec
  la couleur du groupe le plus urgent.
- **En-tête** : logo, « À toi N », pastille ⏰, boutons Rafale, Statistiques, Daily, et un menu `⋯` (mode bureau, sons,
  musique). Stats et Daily s'ouvrent toujours en surimpression.
- Bandeau « Mac injoignable » conservé.

### Style

- Thème **sombre par défaut** (choix du constructeur : c'est celui des maquettes validées, et le plus lisible de loin),
  thème clair au choix dans le menu `⋯` (mémorisé dans le navigateur). Variables CSS sur `:root`. Les deux respectent : texte ≥ 4,5:1, bords de contrôles / anneaux de focus / fonds d'état
  ≥ 3:1.
- Couleurs de groupe (sombre) : orange `#ffb020`, bleu `#5aa9ff`, rouge `#ff5d5d`, vert d'approbation `#2ecc71`, à
  ajuster pour tenir les contrastes en clair.
- Police système, 16 px minimum pour le texte courant, 17 px gras pour les boutons d'action.
- **Cibles tactiles ≥ 48 px**, boutons d'action principaux 56 px, espacement ≥ 8 px. Rien ne dépend du survol.
  Retour visuel à l'appui (`:active`) ; pas de double appui requis.

### Composants ui-sdk

- Fichiers : le build navigateur `@ui-sdk/web@0.1.0-beta.1` (`package/browser/` : `web.js`, `web.css`, `web/`, 1,3 Mo,
  aucune requête externe) copié dans `assets/ui-sdk/0.1.0-beta.1/`, chargé par `<script type="module">` et
  `<link rel="stylesheet">` locaux. Licence copiée à côté.
- `@layer ui-sdk;` en tête de la feuille de style de la page.
- Composants utilisés là où la page en a besoin, d'après le tableau de `references/build-interface.md` du skill :
  `toggle` (Oui / Non), `collapsible` / `accordion` (groupes repliables, section Plus), `dialog` (aperçu avant envoi,
  Rafale), `menu` (menu `⋯` de l'en-tête), `toast` (confirmations et erreurs d'envoi), `textarea`, `button`.
  Aucun `role=` écrit à la main pour un comportement que ui-sdk fournit.
- La liste des sessions est une liste de liens / boutons ordinaire (une seule action par ligne : ouvrir).

### Côté serveur

#### 1. Derniers messages : `GET /api/thread?address=…`

Renvoie `{"me": {"text", "ts"}, "agent": {"text", "ts"}}` (chaque champ peut être `null`).

- Session **locale** : lu dans le journal Claude (`transcript_path(pid)`, déjà existant) : dernier message utilisateur
  « réel » (en excluant les messages outils, `<system-reminder>`, `<task-notification>`… comme le fait déjà `stats.py`)
  et dernier texte de l'assistant. Mis en cache par (chemin, mtime, taille) comme `TRANS`.
- Session **distante** (`machine/tN`) : pas de journal ; `me` = `null`, `agent` = fin de l'écran (`hc read`) nettoyée
  des cadres et de l'invite, 600 caractères au plus. L'interface affiche alors « (écran) » à la place de l'heure.
- Pour l'ancien herdr (`source` présent) : même règle que les sessions distantes.

#### 2. Autorisations

- `/api/state` expose pour chaque session `status` (déjà), `kind` (`status.kind`) et, pour `kind == "permission"`, un
  objet `perm` : `{"tool", "detail", "options": [{"key": "1", "label": "Yes"}, …], "screen_hash"}` extrait de l'écran
  (`hc read`). L'extraction lit le menu numéroté de Claude Code (« Do you want to … ? », lignes `❯ 1. Yes`,
  `2. Yes, and don't ask again …`, `3. No, …`) avec une expression régulière ; pas d'appel à un modèle. Si le menu n'est
  pas reconnu, `perm.options` est vide et l'interface propose seulement « Ouvrir dans le terminal » (texte d'aide) : on
  ne devine jamais une touche.
- `POST /api/approve` `{address, key, screen_hash}` : exige l'appairage (comme `/api/send`), vérifie que la session est
  toujours `blocked/permission`, relit l'écran et **refuse si `screen_hash` a changé** (une autre demande est apparue),
  vérifie que `key` est l'une des options lues, puis `hc keys <address> <key>`. Journalisé dans `sent.jsonl`
  (`{"ts", "address", "approve": key, "label"}`). Anti double appui : même mécanisme que `SENT`.
- Le mapping des boutons se fait par libellé : « Yes » → Approuver, « don't ask again » → Toujours, « No » → Refuser.

#### 3. Voix : `POST /api/transcribe`

- Corps : l'audio brut enregistré par `MediaRecorder` (Safari iPad : `audio/mp4`, Chrome : `audio/webm`), 60 s et
  5 Mo au plus. Exige l'appairage.
- Le serveur écrit l'audio dans `scratch/` (0700), le convertit avec `ffmpeg` en WAV 16 kHz mono, lance `whisper-cli`
  (langue `fr`, sortie texte), supprime les fichiers, renvoie `{"text"}`. Un seul transcodage à la fois (verrou) ;
  délai maximal 60 s.
- Installation sur le M5 : `brew install whisper-cpp` ; modèle **`ggml-large-v3-turbo-q5_0.bin`** (~550 Mo) dans
  `~/.local/share/miniguet/whisper/`. Chemins configurables par `whisper.json` dans le dossier d'état
  (`{"bin", "model"}`), valeurs par défaut ci-dessus. Si Whisper est absent, `/api/state` renvoie `"voice": false` et
  l'interface masque le bouton micro.
- Côté page : appui sur 🎙 = démarrer, nouvel appui = arrêter (pas d'appui maintenu, plus fiable au doigt) ; minuterie
  visible ; pendant la transcription, le bouton montre un indicateur. Le texte est **ajouté** au champ (pas remplacé),
  le curseur placé à la fin. Rien n'est envoyé automatiquement. Refus du micro par le navigateur → message clair.
- Note : Safari exige HTTPS pour le micro : c'est le cas via le tunnel ; en accès direct par Tailscale (HTTP), le micro
  est indisponible et le bouton est masqué (`navigator.mediaDevices` absent).

### Ce qui ne change pas

Les garde-fous d'envoi (`send_check`), le format du message assemblé, l'appairage, Access, les modules stats / daily /
gcal / backup / oldherdr, et toutes les API existantes (la nouvelle page les réutilise telles quelles).

## Mise en service

Choix du constructeur : la nouvelle page remplace `index.html` ; l'ancienne reste servie à `/classic` (copie
`index-classic.html`) pendant deux semaines, en secours, puis est supprimée.

Risque à vérifier en premier : que herdr signale bien les demandes d'autorisation de Claude Code en
`blocked` / `kind: "permission"`, et relever un vrai écran de menu pour les tests (le schéma `hc` le décrit, mais aucune
session n'était bloquée pendant la conception).

## Tests

- **Serveur** (tests `unittest`, stdlib) : extraction du menu d'autorisation sur des écrans d'exemple (Bash, Edit,
  Write, menu à 2 et 3 options, écran non reconnu) ; refus d'`/api/approve` quand le hash d'écran change, quand la touche
  n'est pas une option, sans appairage ; `/api/thread` sur un journal d'exemple (filtrage des faux messages
  utilisateur) ; `/api/transcribe` avec un faux binaire whisper (taille max, délai, nettoyage des fichiers).
- **Interface** : test dans un vrai navigateur (Playwright, déjà disponible) en largeur iPad paysage (1180×820) et
  portrait (820×1180), sur des données d'exemple servies par le serveur en mode démo : regroupement, ouverture d'une
  session, Oui / Non, aperçu, approbation, bascule thème clair / sombre ; contrôle des contrastes ; navigation au clavier
  et noms accessibles des contrôles (exigence du skill ui-sdk).
- **Parité** : liste de contrôle des fonctions existantes (anti-objectifs) cochée à la main sur l'iPad avant de
  remplacer la page.

## Ce qui est laissé au constructeur

- Le découpage du JavaScript (un seul fichier ou quelques modules sous `assets/`), tant qu'il n'y a pas de build.
- Le détail visuel (rayons, ombres, animations courtes) dans le cadre des contraintes de contraste et de taille.
- Le texte exact des étiquettes et messages, en français, au ton actuel de l'application.
- Le format de l'écran d'exemple et des données de démo.
