# zerocode

Agent de codage autonome pour le terminal, gratuit par défaut et compatible avec plusieurs fournisseurs de modèles. Le mode `auto` sélectionne une route adaptée à la demande.

Créé par **H@CKERBOY** · [GitHub](https://github.com/hackerboy-223) · [Portfolio](https://hackerboy-223.vercel.app)

zerocode inspecte un dépôt, lit et modifie des fichiers, lance des tests et exécute des commandes. Il ne se contente pas de générer du texte : chaque action est vérifiable, les modifications sûres et les commandes de contrôle courantes sont automatiques, et les opérations sensibles restent soumises à autorisation.

## Points clés

- Chaîne de repli automatique si un modèle est indisponible, limité ou saturé.
- Modèle automatique gratuit sans clé personnelle via Kilo Gateway ; fournisseurs supplémentaires disponibles en configuration explicite.
- Outils intégrés (18 outils) : lecture (`read`), écriture (`write`), édition (`edit`), édition multi-blocs atomique (`multi_edit`), liste (`list`), recherche regex (`grep` / `ripgrep`), cartographie AST de symboles (`symbols`), inspection Git sécurisée (`git_status`, `git_diff`), audit statique de cybersécurité SAST (`security_audit`), diagnostic système/technicien (`sys_diag`), cartographie de projet (`project_map`), vérification multi-stack (`project_verify`), shell (`bash`), web (`fetch`, `web_search`), sous-agents spécialisés isolés (`subagent`: explorer, architect, reviewer, security, performance, tester, researcher), plan de tâches (`todo_write`) et checkpoints atomiques (`/undo`). Les outils des serveurs MCP configurés sont ajoutés dynamiquement.
- Système de **Skills d'expertise** intégrés et extensibles (`/skills`, `/skill <nom>`, `--skill`) : `ultra-dev` (Ingénierie Senior), `cyber-sec` (Expert Cybersécurité, Audit OWASP/CWE & DevSecOps), `sys-tech` (Technicien Système, Réseau & Infra), `review` (Revue de code), `perf` (Haute Performance) et `sec-hardening` (Durcissement actif), plus découverte automatique de `.zerocode/skills/*.md` et `~/.config/zerocode/skills/*.md`.
- Hooks de cycle de vie `PreToolUse` / `PostToolUse` configurables pour bloquer ou auditer les actions. Les hooks sont lus uniquement dans la configuration globale utilisateur et exécutés sans shell. Guide : [`docs/HOOKS.md`](docs/HOOKS.md).
- Intégration Fabric native : `zerocode skills --sync-fabric` télécharge les Patterns (développement, sécurité, recherche, rédaction, apprentissage, etc.) dans le catalogue local et les stratégies de raisonnement dans un répertoire séparé. `--force` actualise les ressources déjà installées. Guide : [`docs/FABRIC_INTEGRATION.md`](docs/FABRIC_INTEGRATION.md). Connecteurs navigateur/fichiers (Playwright, filesystem) : [`docs/MCP_SERVERS.md`](docs/MCP_SERVERS.md).
- Exécution parallèle automatique des appels d'outils en lecture seule (`ThreadPoolExecutor`), pré-injection directe des fichiers mentionnés avec `@chemin` (0 tour réseau) et cache TTL Git.
- Diagnostics syntaxiques instantanés (Python AST, JSON, TOML, Shell `bash -n` et JavaScript `node --check`) après chaque écriture ou édition pour auto-correction immédiate.
- Sessions reprenables, mémoire projet persistante (`/remember`), copie rapide (`/copy`, `Ctrl+Y`), compaction du contexte, support multimodal (`/image`, `--image`), mode headless JSON Lines (`--json`) et autocomplétion shell (`zerocode completion`).
- Interface TUI Textual sobre et moderne : sidebar projet/sessions, chat Markdown, streaming temps réel, diffs intégrés et approbations.
- Mascotte animée **LUPUS**, un loup veilleur qui rappelle d'observer avant d'agir.
- Routage adaptatif : modèle spécialisé pour le code, raisonnement renforcé pour les audits et modèle rapide pour les demandes simples.
- Mode `/full-stack` autonome : cartographie préalable du dépôt, sélection contextuelle des Skills, sous-agents spécialistes, plan de tâches, vérification multi-stack et auto-continuation renforcée jusqu'à la livraison.
- Palette de commandes, recherche de fichiers `@`, boutons d'action rapides et panneaux de tâches/outils.
- Cybersécurité Zero-Trust : masquage DLP automatique des clés et jetons API (`redact_secrets`), pare-feu contre les commandes shell destructrices, isolation des variables d'environnement sensibles dans les sous-processus et protection anti-SSRF.

## Installation automatique

Pour les étapes détaillées, les commandes par système, les mises à jour et le dépannage, consulte le [guide d'installation complet](INSTALL_GUIDE.md).

L'installateur interactif propose trois choix : **TUI**, **Desktop** ou **les deux**. Par défaut, il cherche la dernière release stable. Quand elle existe, il télécharge les paquets précompilés et vérifie leur empreinte SHA-256 avant installation. Node.js, Rust et les outils C/C++ ne sont donc pas nécessaires pour installer une release.

Si aucune release stable n'est publiée, l'installateur utilise le code source de la branche `main`. Dans ce mode de secours, Desktop doit être compilé localement et les outils de développement correspondants sont installés.

### Linux et macOS

```bash
curl -fsSL https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.sh | bash
```

Choisis TUI, Desktop ou les deux dans le menu. Les paquets Desktop sont installés selon le système : `.deb`, `.rpm`, AppImage ou `.dmg`/`.app`.

Pour choisir le mode ou une version sans passer par le menu :

```bash
bash install.sh --mode tui
bash install.sh --mode desktop
bash install.sh --mode both
bash install.sh --version latest --mode both
bash install.sh --version v1.0.0 --mode desktop
```

Pour forcer le parcours depuis une branche source :

```bash
ZEROCODE_INSTALL_REF=main bash install.sh --mode desktop
```

### Windows · PowerShell

```powershell
irm https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.ps1 | iex
```

Le menu propose les mêmes trois choix. Une release stable installe le moteur depuis le wheel Python vérifié puis lance l'installateur Desktop Windows. `winget`, Node.js, Rust et Visual Studio Build Tools ne sont nécessaires que pour le parcours de compilation source.

Pour choisir une version précise :

```powershell
$env:ZEROCODE_INSTALL_REF = "v1.0.0"
irm https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.ps1 | iex
```

### Installation manuelle du moteur

```bash
python -m pip install --user pipx
python -m pipx ensurepath
pipx install git+https://github.com/hackerboy-223/zerocode.git
```

Pour contribuer au code source :

```bash
git clone https://github.com/hackerboy-223/zerocode.git
cd zerocode
python -m venv .venv
# Linux/macOS : source .venv/bin/activate
# Windows : .venv\\Scripts\\Activate.ps1
python -m pip install -e ".[dev]"
pytest
ruff check src tests
```
## État de publication

La release stable **[ZeroCode v1.0.0](https://github.com/hackerboy-223/zerocode/releases/tag/v1.0.0)** a été publiée le 22 novembre 2026. Elle comprend le moteur Python, les paquets Desktop pour Linux x86_64, Windows x64 et macOS Intel/Apple Silicon, ainsi que le manifeste `SHA256SUMS`.

Le workflow de publication a terminé ses **7 jobs sur 7 avec succès**. Les workflows CI et Quality sur `main` sont également au vert. Les scripts d'installation téléchargent les paquets de la release stable et vérifient leur empreinte avant installation. Les binaires ne sont toutefois pas encore signés avec un certificat éditeur Windows ou Apple ; consulte le [guide d'installation](INSTALL_GUIDE.md) pour les avertissements et vérifications.

## Versions, mises à jour et désinstallation

Les releases sont déclenchées par un tag Git `vX.Y.Z`. Le workflow vérifie que les versions du package Python, de npm, de Cargo et de Tauri correspondent au tag, puis construit les paquets natifs Windows, macOS et Linux et les distributions Python. Les fichiers publiés reçoivent un manifeste `SHA256SUMS`.

Pour publier une nouvelle version, aligne les versions dans `pyproject.toml`, `desktop/package.json`, `desktop/src-tauri/Cargo.toml` et `desktop/src-tauri/tauri.conf.json`, puis pousse le tag correspondant. Le workflow refusera les versions incohérentes.

Mettre à jour le moteur Python/TUI depuis la dernière release stable :

```bash
zerocode update --check
zerocode update
```

Pour réparer le moteur avec une réinstallation vérifiée de la release actuelle :

```bash
zerocode repair
```

Pour revenir à une version stable connue :

```bash
zerocode rollback v1.0.0
```

Sous Windows, les commandes de maintenance du moteur évitent de remplacer les fichiers Python d'un processus encore actif. Ferme ZeroCode puis relance l'installateur PowerShell pour mettre à jour, réparer ou revenir à une version précise ; configure `$env:ZEROCODE_INSTALL_REF = "v1.0.0"` avant de lancer l'installateur pour un rollback.

Pour mettre à jour Desktop, relance l'installateur officiel. Il récupère la dernière release et installe le paquet natif adapté au système.

Désinstaller le moteur tout en conservant la configuration, les clés API et les sessions :

```bash
zerocode uninstall
```

Sous Windows, ferme toutes les fenêtres ZeroCode puis désinstalle le moteur depuis une nouvelle fenêtre PowerShell avec `pipx uninstall zerocode`. Les données utilisateur ne sont pas supprimées par cette commande.

Supprimer aussi ces données utilisateur (opération irréversible, commande prise en charge sur Linux et macOS) :

```bash
zerocode uninstall --remove-data
```

Desktop reste géré par le système d'exploitation : utilise les paramètres d'applications de Windows/macOS, `sudo apt remove zerocode-desktop` sur Debian/Ubuntu ou `sudo dnf remove zerocode-desktop` sur Fedora. Sur une installation AppImage utilisateur, retire `~/.local/opt/zerocode`, `~/.local/bin/zerocode-desktop` et `~/.local/share/applications/zerocode-desktop.desktop`.

Les releases possèdent des sommes SHA-256 pour vérifier l'intégrité des téléchargements. Elles ne sont pas encore signées par un certificat éditeur Windows ou Apple ; une somme hébergée avec le paquet ne remplace pas une signature du fournisseur.
## Démarrage rapide

Sans aucune clé :

```bash
zerocode "explique la structure de ce projet"
zerocode
zerocode tui
```

Sans prompt, `zerocode` ouvre l'interface TUI Textual. Elle affiche la sidebar du projet, les sessions, le chat Markdown, l'état du routeur et les confirmations d'outils. Tapez `/help` ou `Ctrl+K` pour les commandes.

Pour revenir à l'ancienne boucle REPL :

```bash
zerocode --classic
zerocode chat --classic
```

Exemples :

```bash
zerocode "corrige le test qui échoue" --yolo
zerocode -m auto
zerocode -c
```

`--yolo` autorise les actions ordinaires sans confirmation. Il ne contourne pas les confirmations dédiées à `sudo` ni aux serveurs MCP non fiables. À utiliser uniquement dans un dépôt de confiance.

## Interface TUI

L'interface par défaut s'appuie sur [Textual](https://textual.textualize.io/). Elle est pensée pour garder le contexte visible sans bloquer le terminal.

- **Sidebar** : branche Git, arborescence du projet et sessions récentes avec leur premier message.
- **Chat** : réponses Markdown, blocs de code colorés, raisonnement et cartes d'outils repliables.
- **Modes agent** : `BUILD` pour modifier, `PLAN` pour inspecter sans toucher aux fichiers (`Shift+Tab`), `FULL-STACK` pour construire un projet complet en autonomie.
- **Panneaux** : barre `CHAT / TÂCHES / OUTILS` toujours visible, synchronisée avec `Tab`.
- **Statut** : modèle, fournisseur, route prévue, permissions, session et jetons, avec animation de réflexion et indicateur d'activité.
- **Approbations** : les modifications risquées et commandes non classées comme sûres ouvrent un panneau `Autoriser / Refuser` avec aperçu défilable.
- **Confort** : historique des demandes avec `↑`/`↓`, recherche floue et défilement qui ne vous arrache pas la lecture si vous êtes remonté.

| Raccourci | Action |
| --- | --- |
| `Ctrl+K` | Palette de commandes avec recherche floue |
| `@` | Recherche floue de fichiers du dépôt |
| `↑` / `↓` | Naviguer dans l'historique des demandes |
| `Shift+Tab` | Basculer entre les modes build et plan |
| `Tab` | Chat → tâches → outils |
| `F2` | Replier ou ouvrir le dernier résultat d'outil |
| `F3` | Basculer le mode think (`off` / `low` / `high` / `max`) |
| `F6` | Focus prompt → fichiers → sessions → chat |
| `Échap` | Interrompre le tour ou le processus shell en cours |
| `Ctrl+B` | Afficher ou masquer la sidebar |
| `F1` | Aide et commandes |
| `Ctrl+Q` | Quitter |

Le mode plan masque `write`, `edit` et `bash`, ajoute une consigne de lecture seule au prompt système et refuse toute tentative de mutation.

`/full-stack` active un preset autonome : raisonnement `max`, 500 étapes, 128k jetons de sortie (plafonnés par le modèle), timeout de commande d'une heure, compaction à 95 %, raisonnement affiché et permissions `allow`. L'agent est invité à planifier, scaffolder, implémenter, installer les dépendances locales, tester, corriger et livrer un projet complet sans demander confirmation à chaque étape. Un retour en `BUILD`, `PLAN` ou `/safe` restaure automatiquement les réglages et permissions précédents. Les outils de fichiers vérifient les chemins et bloquent les fichiers de secrets par défaut. Attention : le shell exécute des commandes avec les droits de votre compte et n'est pas une sandbox ; une commande peut accéder à des fichiers hors du projet, y compris des secrets. N'activez `--yolo` ou `/full-stack` que dans un environnement de confiance.

Les réponses et le raisonnement sont diffusés en streaming via un worker, avec une animation de réflexion visible pendant l'attente, sans figer l'interface. Les confirmations de sécurité restent actives en mode `ask`.

## Modèles et routage gratuit

Le mode `auto` est le choix recommandé pour commencer : il utilise exclusivement les routes anonymes gratuites de Kilo Gateway, sans clé API personnelle, sans compte OpenRouter et sans carte bancaire. Le routeur adapte l'ordre des modèles gratuits à la demande (code, raisonnement ou requête simple).

**À retenir :** Kilo Gateway est un service distant. Ses quotas, sa disponibilité et ses conditions peuvent évoluer. Si le quota est atteint ou si le service est indisponible, ZeroCode ne bascule pas silencieusement vers un modèle payant ni vers un fournisseur qui réclame une clé : il signale l'échec. La gratuité ne garantit donc pas une disponibilité illimitée.

Les modèles gratuits d'OpenRouter et les autres fournisseurs restent accessibles si tu les configures volontairement avec leurs propres identifiants. Ils ne font pas partie du routage automatique sans clé.

### Utilisation 100 % locale

Pour ne dépendre d'aucun fournisseur distant, installe [Ollama](https://ollama.com), télécharge un modèle compatible (par exemple `ollama pull qwen2.5-coder:7b`) et sélectionne le fournisseur local dans la configuration. Aucun compte ni clé API n'est requis ; les performances dépendent de la mémoire et du processeur de ta machine.

Détails, identifiants et limites : [docs/PROVIDERS.md](docs/PROVIDERS.md).

## GLM 5.3 et offre gratuite

Il n'existe pas d'API gratuite permanente pour GLM 5.3 complet. Les routes gratuites ou d'essai dépendent des fournisseurs et peuvent changer.

| Modèle | Accès gratuit réel | Remarque |
| --- | --- | --- |
| GLM 5.3 complet | Essai ou crédit selon le fournisseur | Pas de gratuité permanente connue |
| GLM 5.3 Flash | NVIDIA Build, OpenCode Zen | `glm-5.3-flash-free` chez OpenCode Zen |
| GLM 4.7 Flash | Z.AI | Gratuit en permanence sur l'API publique |
| GLM 4.5 Flash | Z.AI | Gratuit en permanence sur l'API publique |
| Modèles `:free` | OpenRouter | Quota gratuit, conditions variables |
| Kilo Auto Free | Kilo Gateway | Route anonyme gratuite, quotas susceptibles d'évoluer |

Ces offres concernent des accès fournisseurs optionnels : elles ne sont pas utilisées par le routage automatique sans clé de ZeroCode. Vérifie les conditions actuelles auprès de chaque fournisseur avant de les sélectionner.

Détails et identifiants exacts : [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Configuration

```bash
zerocode setup
zerocode setup --show
zerocode setup --test
zerocode doctor --live
```

Les clés peuvent aussi être fournies par l'environnement (voir `.env.example`) :

```bash
export NVIDIA_API_KEY="..."
export ZAI_API_KEY="..."
export OPENROUTER_API_KEY="..."
```

Ou stockées dans `~/.config/zerocode/keys.json` avec les droits `600`. Ne commitez jamais ce fichier.

### Fichiers

| Élément | Chemin |
| --- | --- |
| Configuration globale | `~/.config/zerocode/config.json` |
| Clés | `~/.config/zerocode/keys.json` |
| Sessions | `~/.local/share/zerocode/sessions/` |
| Configuration projet | `zerocode.json` ou `.zerocode.json` |
| Instructions projet | `ZEROCODE.md`, `AGENTS.md` |

Les variables `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `ZEROCODE_CONFIG` et `ZEROCODE_KEYS_FILE` permettent de déplacer ces fichiers.

### Exemple de configuration projet

```json
{
  "model": "auto",
  "free_only": true,
  "fallback": true,
  "permissions": "ask",
  "max_steps": 40,
  "max_tokens": 8192,
  "providers": {
    "zai": { "base_url": "https://api.z.ai/api/coding/paas/v4" }
  }
}
```

Les overrides disponibles : `--model`, `--provider`, `--free-only/--no-free-only`, `--fallback/--no-fallback`, `--reasoning`, `--temperature`, `--max-tokens`, `--max-steps`, `--permissions`, `--allow-outside-cwd`.

## Commandes

| Commande | Rôle |
| --- | --- |
| `zerocode [prompt]` | Exécuter une demande ou ouvrir le TUI |
| `zerocode tui` | Ouvrir explicitement l'interface TUI |
| `zerocode --classic` | Ouvrir l'ancienne interface REPL |
| `zerocode doctor [--live]` | Diagnostic local et test réel du routeur |
| `zerocode audit [chemin]` | Audit statique de sécurité (SAST, secrets, OWASP/CWE, permissions) |
| `zerocode skills [--json] [--sync-fabric] [--force]` | Lister les skills ou importer/actualiser les Patterns Fabric |
| `zerocode strategies [--json] [--show NOM]` | Lister ou afficher les stratégies Fabric installées séparément |
| `zerocode models [--free] [--live]` | Catalogue des modèles |
| `zerocode providers` | État des fournisseurs et des clés |
| `zerocode sessions` | Lister, reprendre ou supprimer des sessions |
| `zerocode config` | Afficher ou initialiser la configuration |
| `zerocode completion [bash\|zsh\|fish]` | Générer le script d'autocomplétion shell |

Dans le chat : `/help`, `/build`, `/plan`, `/full-stack`, `/skills`, `/skill`, `/audit`, `/doctor`, `/model`, `/provider`, `/permissions`, `/yolo`, `/safe`, `/reasoning`, `/think`, `/temp`, `/max-steps`, `/compact`, `/cost`, `/todos`, `/tools`, `/models`, `/free`, `/providers`, `/session`, `/new`, `/resume`, `/sessions`, `/cd`, `/init`, `/remember`, `/copy`, `/undo`, `/image`, `/clear`, `/quit`.

## Outils et sécurité

- `read`, `list`, `grep`, `fetch`, `web_search` et `todo_write` sont sans effet de bord sur le dépôt et automatiques.
- En mode `ask`, la création de nouveaux fichiers, les éditions dans le projet et les commandes sûres de diagnostic/tests/lint (`pytest`, `unittest`, `ruff`, `mypy`, `flake8`, `npm test`, `cargo test`, `cargo clippy`, `go test`, `go vet`, etc.) sont automatiques.
- Le remplacement d'un fichier existant via `write`, les commandes shell non classées comme sûres et les actions sensibles demandent confirmation.
- Toute commande `sudo` exige une confirmation dédiée à chaque exécution, même avec `/full-stack`, `--yolo` ou un ticket sudo déjà actif. Le mot de passe n'est jamais enregistré dans la configuration ou les sessions ; l'authentification est refusée en mode non interactif.
- Un pare-feu shell bloque systématiquement les commandes catastrophiques pour l'hôte (`rm -rf /`, `rm -rf ~`, fork bombs, `mkfs`, `dd of=/dev/*`), même en mode `allow` ou `--yolo`.
- Toutes les sorties d'outils passent par un filtre DLP (`redact_secrets`) qui masque automatiquement les clés privées PEM, les jetons API (`sk-*`, `nvapi-*`, `ghp_*`, `AKIA*`, `AIza*`, `gsk_*`, `hf_*`, `Bearer`) et les mots de passe dans les URL de connexion.
- Les sous-processus `bash` et les serveurs MCP s'exécutent dans un environnement expurgé des clés API des fournisseurs (`PROVIDER_KEY_ENVS`).
- Les outils `fetch` et `web_search` bloquent les adresses IP privées, loopback, link-local, non spécifiées (`0.0.0.0`/`::`), IPv6 mappées IPv4 et les endpoints de métadonnées cloud (anti-SSRF).
- Les outils de fichiers et de recherche refusent les chemins et liens symboliques hors du répertoire de travail sauf avec `--allow-outside-cwd`, et bloquent les fichiers de secrets par défaut.\n- Les outils MCP distants exigent une confirmation explicite dédiée, y compris en mode `/full-stack` et `--yolo`, car ils peuvent agir sur des comptes, dépôts et services externes.
- Les écritures et la restauration `/undo` dans `.git` et les fichiers de secrets sont bloquées.
- Les commandes ont un délai maximal ; leur sortie est diffusée en temps réel, limitée en mémoire et tronquée avant d'être renvoyée à l'agent.
- zerocode ne commit, ne pousse et n'installe rien sans demande explicite.

Aucun agent ne remplace une revue humaine. Vérifiez les diffs et les commandes avant de les accepter, surtout en mode `--yolo`.

## Architecture

Le fonctionnement interne, le routage et les points d'extension sont décrits dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```text
CLI / TUI Textual
   |
   v
Agent <--> Router <--> Fournisseurs OpenAI-compatibles
   |
   +--> Outils (fichiers, recherche, shell, tâches)
   |
   +--> Sessions et compaction du contexte
```

## Développement

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

Les tests n'effectuent aucun appel réseau. Les fournisseurs sont simulés avec `httpx.MockTransport`.

## Limites

- Les offres gratuites, quotas et identifiants de modèles changent fréquemment.
- Les données envoyées à un fournisseur anonyme ou gratuit peuvent être journalisées ou utilisées pour améliorer ses services; les notes de confidentialité varient par modèle.
- La qualité et le respect des appels d'outils varient selon le modèle.
- Le mode gratuit peut être plus lent ou temporairement saturé.
- La compaction du contexte est une estimation, pas un comptage exact de jetons.

## Auteur

**H@CKERBOY**

- GitHub : [github.com/hackerboy-223](https://github.com/hackerboy-223)
- Portfolio : [hackerboy-223.vercel.app](https://hackerboy-223.vercel.app)
- Dépôt : [github.com/hackerboy-223/zerocode](https://github.com/hackerboy-223/zerocode)

## Licence

MIT. Voir [LICENSE](LICENSE).


## ZeroCode Desktop

ZeroCode existe aussi sous forme d’application graphique native, construite avec **Tauri 2, React et TypeScript**. Elle réutilise le moteur Python installé localement : pas de deuxième agent ni de service d'exécution hébergé.

Fonctionnalités principales :

- Conversations avec réponses en streaming et blocs de code formatés.
- Modes **Build**, **Plan** et **Full-stack**, avec sélection du modèle et des permissions.
- Gestion des projets et des sessions, reprise d'une conversation et création d'une nouvelle session.
- Inspecteur latéral : branche Git, tâches, historique des outils, explorateur de fichiers et diffs de session. Pour éviter d'exécuter à l'ouverture des filtres ou helpers Git configurés par un dépôt, l'état automatique n'exécute pas `git status` : la liste des fichiers modifiés n'est pas préremplie.
- Terminal local intégré basé sur un pseudo-terminal (PTY).
- Demandes d'autorisation explicites pour les opérations sensibles et restauration prudente des checkpoints.
- Mascotte animée LUPUS, sans dépendance à une ressource distante.

L'application et son terminal exécutent les commandes sur l'ordinateur de l'utilisateur. Les prompts, extraits de fichiers et réponses peuvent être transmis au fournisseur de modèle sélectionné. Pour garder l'inférence sur la machine, configure un fournisseur local compatible comme Ollama.

Guide complet : [docs/DESKTOP.md](docs/DESKTOP.md).

