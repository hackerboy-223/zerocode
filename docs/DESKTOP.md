# ZeroCode Desktop

ZeroCode Desktop est l’interface graphique native de l’agent Python existant. Elle utilise le moteur installé sur la machine, et non un environnement d’exécution hébergé.

## Fonctionnement

- **Interface** : React, TypeScript, Vite et Tauri 2.
- **Agent** : processus Python local via `zerocode desktop-bridge`.
- **Terminal** : pseudo-terminal natif (PTY), ouvert dans le dossier du projet.
- **Sessions** : réutilise le stockage de sessions de ZeroCode.
- **Autorisations** : les demandes d’écriture, de commande et de privilèges remontent dans l’interface. Une absence de réponse est traitée comme un refus.
- **Démarrage sûr** : Desktop démarre en mode `ask`, même si le CLI est configuré en `allow`. L’accès aux fichiers reste limité au workspace et les fichiers de secrets restent protégés. Le mode Full-stack exige une confirmation explicite.
- **DLP** : les sorties du shell sont limitées et filtrées avant affichage ; les secrets connus sont masqués dans les événements du bridge.
- **Annulation prudente** : les checkpoints récents enregistrent l’empreinte du fichier après modification. `Annuler` refuse d’écraser un fichier modifié depuis et bloque les chemins hors workspace.
- **Mascotte** : LUPUS, dessin vectoriel animé, sans ressource externe.

Les commandes de l’agent et le shell s’exécutent sur l’ordinateur qui héberge l’application. Les prompts, extraits de fichiers et réponses peuvent toutefois être transmis au fournisseur de modèle sélectionné. Pour garder l’inférence locale, configure un fournisseur local compatible, par exemple Ollama. Vérifie toujours les paramètres de confidentialité du fournisseur distant avant d’envoyer du code privé.

Le terminal intégré est un nouveau shell interactif du projet. Il ne prend pas le contrôle d’une fenêtre de terminal externe déjà ouverte.

## Installer ZeroCode Desktop

L’installateur officiel propose trois choix : TUI, Desktop ou les deux. Il sélectionne par défaut la dernière release stable.

Une release stable contient le moteur Python et les paquets Desktop natifs. Avant installation, l’installateur télécharge `SHA256SUMS` et vérifie chaque fichier. Dans ce parcours, les toolchains Node.js, Rust et C/C++ ne sont pas installées.

Si aucune release stable n’est encore publiée, le mode `latest` revient sur la branche source `feature/zerocode-desktop`. Le parcours de compilation source prépare alors les outils nécessaires au système. Une erreur d’intégrité ou un paquet manquant dans une release ne déclenche jamais silencieusement ce repli : l’installation s’arrête.

### Linux et macOS

Depuis le terminal :

```bash
curl -fsSL https://raw.githubusercontent.com/hackerboy-223/zerocode/feature/zerocode-desktop/install.sh | bash
```

Choisis Desktop ou Les deux. Pour sélectionner le mode ou une version précise sans ouvrir le menu :

```bash
bash install.sh --mode tui
bash install.sh --mode desktop
bash install.sh --mode both
bash install.sh --version latest --mode desktop
bash install.sh --version v1.0.0 --mode both
```

Pour forcer le parcours depuis une branche source :

```bash
ZEROCODE_INSTALL_REF=feature/zerocode-desktop bash install.sh --mode desktop
```

Sur Debian/Ubuntu, le paquet `.deb` est installé avec apt et nécessite les droits administrateur. Fedora utilise le RPM. Les distributions Linux sans apt ni dnf utilisent l’AppImage dans le dossier utilisateur. macOS télécharge un DMG, le monte et copie `ZeroCode Desktop.app` dans `~/Applications`.

En mode source, Linux installe les bibliothèques GTK/WebKit, Node.js et Rust stable ; macOS exige Xcode Command Line Tools. Le build est réalisé localement par Tauri.

### Windows

Dans PowerShell :

```powershell
irm https://raw.githubusercontent.com/hackerboy-223/zerocode/feature/zerocode-desktop/install.ps1 | iex
```

Une release stable installe le moteur depuis le wheel Python vérifié puis lance l’installateur NSIS natif. Pour sélectionner une version précise :

```powershell
$env:ZEROCODE_INSTALL_REF = "v1.0.0"
irm https://raw.githubusercontent.com/hackerboy-223/zerocode/feature/zerocode-desktop/install.ps1 | iex
```

En mode source, `winget` prépare Node.js, Rustup, Visual Studio C++ Build Tools, WebView2 et NSIS avant la compilation Tauri. App Installer / winget doit être disponible.

### Mise à jour et désinstallation

Le moteur TUI se met à jour depuis la dernière release stable :

```bash
zerocode update --check
zerocode update
```

Pour réparer le moteur, utilise `zerocode repair`. Pour revenir à une version stable précise, utilise `zerocode rollback v1.0.0`. Les deux commandes vérifient le wheel et son empreinte avant remplacement.

Sous Windows, ces commandes n'écrasent pas le venv Python depuis le processus qui l'utilise. Ferme ZeroCode puis relance l'installateur PowerShell ; pour un rollback, définis `$env:ZEROCODE_INSTALL_REF = "v1.0.0"` avant de le lancer.

Pour mettre à jour Desktop, relance le même installateur ; il récupère la release la plus récente et remplace le paquet natif. Les paquets `.deb` et `.rpm` restent gérés par le gestionnaire système.

Sur Linux et macOS, le moteur Python peut être désinstallé avec `zerocode uninstall`. Les configurations, clés API et sessions sont conservées par défaut. `zerocode uninstall --remove-data` les supprime aussi, après confirmation. Sous Windows, ferme ZeroCode puis exécute `pipx uninstall zerocode` dans une nouvelle fenêtre PowerShell ; cette commande conserve les données utilisateur.

Pour retirer Desktop, passe par les paramètres d’applications du système, ou utilise le gestionnaire de paquets Linux. L’AppImage utilisateur se retire en supprimant `~/.local/opt/zerocode`, son lanceur `~/.local/bin/zerocode-desktop` et le raccourci `.desktop`.

### Vérification des téléchargements

Le manifeste `SHA256SUMS` est publié dans chaque release. Il permet de détecter un téléchargement corrompu ou incomplet. Il n’apporte pas à lui seul une preuve d’identité de l’éditeur : les binaires ne sont pas encore signés avec un certificat éditeur Windows ou Apple.
## Développement

Depuis la racine du dépôt :

```bash
cd desktop
npm ci
npm run app:dev
```

L’application Tauri démarre avec le serveur Vite local. Le terminal intégré s’ouvre dans le dossier du projet sélectionné.

## Construire l’application manuellement

```bash
cd desktop
npm ci
npm run app:build
```

Les artefacts natifs sont générés dans `desktop/src-tauri/target/release/bundle/`. La compilation doit être réalisée sur chaque système cible (Linux, Windows ou macOS) avec ses dépendances de développement propres.

## Résolution des problèmes

**« ZeroCode CLI introuvable »**  
Vérifie `zerocode doctor` dans ton terminal habituel, puis ouvre l’application depuis le même compte utilisateur. L’application recherche aussi les emplacements pipx courants sous `~/.local/bin` et `~/.local/share/pipx/venvs/zerocode/bin`. Pour un autre emplacement, configure `ZEROCODE_EXECUTABLE`.

**L’application s’ouvre mais aucun modèle n’est disponible**  
Vérifie le réseau et lance `zerocode doctor --live`. Le shell et les fichiers restent locaux, mais la route de modèle peut nécessiter un accès réseau.

**Le terminal est vide ou ne démarre pas**  
Vérifie que le shell défini par `$SHELL` existe. Sur Linux, vérifie la présence des bibliothèques WebKit indiquées plus haut.

## Périmètre de cette version

Cette version fournit :
- **Fenêtre desktop native** (Tauri 2 + React + TypeScript) avec icônes multi-plateformes configurées.
- **Affichage minimal** : barre latérale (projets et conversations groupées par date), conversation centrée, inspecteur masqué par défaut. Le fil regroupe les appels d'outils en lignes repliables et affiche les sous-agents sous forme de cartes.
- **Sous-agents** : sept spécialistes en lecture seule (`explorer`, `architect`, `reviewer`, `security`, `performance`, `tester`, `researcher`). Lancement depuis le panneau **Agents**, la commande `/agent [rôle] <tâche>` ou le sélecteur de la zone de saisie. Les exécutions (déclenchées par vous ou par l'agent principal) sont suivies en direct avec leurs outils, leur durée et leur synthèse. Des orchestrations prêtes à l'emploi (revue complète, audit sécurité, plan d'architecture, chasse aux lenteurs) demandent à l'agent principal de déléguer en parallèle.
- **Commandes rapides** dans la zone de saisie : `/agent`, `/plan`, `/build`, `/fullstack`, `/model`, `/think`, `/new`, `/compact`, `/undo`, `/copy`, `/terminal`, `/settings`, `/help`. `@` propose les fichiers du projet.
- **Préférences (`Ctrl + ,`)** en six sections :
  - *Apparence* : thème Système/Clair/Sombre, couleur d'accent, densité, taille du texte.
  - *Agent* : mode (Build / Plan / Full-stack), politique d'autorisation (`ask`, `auto`, `allow`), modèle, profondeur de raisonnement, mode/modèle/raisonnement par défaut au démarrage.
  - *Exécution* : étapes maximum, délai des commandes, jetons de sortie, température, seuil et activation de la compaction, routage par tâche, repli automatique, modèles gratuits uniquement, affichage des diffs. Appliqués à chaud puis rappliqués à chaque démarrage.
  - *Sous-agents* : délégation automatique (consigne d'orchestration ajoutée aux demandes) et spécialiste par défaut.
  - *Interface* : touche d'envoi (Entrée ou Ctrl + Entrée), défilement automatique, raisonnement et détails d'outils, confirmation des modes à risque, notification de fin de tâche.
  - *Données & raccourcis* : compaction, copie de la conversation en Markdown, projets récents, réinitialisation.
- **Frontières de sécurité inchangées** : l'accès hors du projet, la protection des secrets et la politique d'autorisation ne sont jamais restaurés ni modifiés par les réglages d'exécution ; le démarrage reste en mode `ask`, et Full-stack n'est jamais réactivé automatiquement.
- **Inspecteur latéral** (`Ctrl + I`) à sept onglets : Aperçu (état, plan de travail, annulation), Agents, Fichiers, Changements (statut Git, diffs de session, annulation), Code (Monaco), Recherche (index lexical local) et MCP.
- **Palette de commandes (`Ctrl + K`)**, **Terminal PTY local** redimensionnable (`Ctrl` + accent grave), barre latérale (`Ctrl + B`).

### Protocole du pont (nouveautés)

| Message UI → agent | Effet |
| --- | --- |
| `run_subagent {role, task}` | Exécute un sous-agent directement ; événements `subagent` (`start`, `tool`, `end`) |
| `set_runtime {values}` | Applique une liste blanche de réglages d'exécution validés ; émet `runtime_changed` |

Les événements `ready` et `session_changed` incluent désormais `runtime` et `subagent_roles`.
