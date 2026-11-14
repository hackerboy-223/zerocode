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

## Prérequis

- Node.js 20.19+ ou 22.12+ et npm.
- Rust stable et Cargo.
- Python 3.10+.
- Le moteur ZeroCode déjà installé et fonctionnel.

### Linux (Ubuntu / Debian)

Installe les dépendances système Tauri/WebKit :

```bash
sudo apt update
sudo apt install -y build-essential curl wget file libssl-dev libgtk-3-dev libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev patchelf
```

Installe Rust si nécessaire :

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
```

Installe le moteur Python avec pipx :

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install git+https://github.com/hackerboy-223/zerocode.git
zerocode doctor
```

Si le moteur est dans un environnement non standard, définis `ZEROCODE_EXECUTABLE` vers le chemin absolu de la commande `zerocode`.

## Lancer en mode développement

Depuis la racine du dépôt :

```bash
cd desktop
npm ci
npm run app:dev
```

L’application Tauri démarre avec le serveur Vite local. Le terminal intégré s’ouvre dans le dossier sélectionné.

## Construire l’application

```bash
cd desktop
npm ci
npm run app:build
```

Les artefacts natifs sont générés dans `desktop/src-tauri/target/release/bundle/`. La compilation doit être faite sur chaque système cible (Linux, Windows ou macOS) avec ses dépendances de développement propres.

## Résolution des problèmes

**« ZeroCode CLI introuvable »**  
Vérifie `zerocode doctor` dans ton terminal habituel, puis ouvre l’application depuis le même compte utilisateur. L’application recherche aussi les emplacements pipx courants sous `~/.local/bin` et `~/.local/share/pipx/venvs/zerocode/bin`. Pour un autre emplacement, configure `ZEROCODE_EXECUTABLE`.

**L’application s’ouvre mais aucun modèle n’est disponible**  
Vérifie le réseau et lance `zerocode doctor --live`. Le shell et les fichiers restent locaux, mais la route de modèle peut nécessiter un accès réseau.

**Le terminal est vide ou ne démarre pas**  
Vérifie que le shell défini par `$SHELL` existe. Sur Linux, installe les dépendances WebKit listées plus haut.

## Périmètre de cette version

Cette version fournit :
- **Fenêtre desktop native** (Tauri 2 + React + TypeScript) avec icônes multi-plateformes configurées.
- **Fil de conversation enrichi** : blocs de code formatés avec copie rapide, affichage repliable du raisonnement (`think`), et gestion complète des sessions (reprise, création, suppression).
- **Modes d'agent & Préférences (`Ctrl + ,`)** : bascule Build / Plan / Full-stack, sélection du modèle (`auto` ou modèle spécifique), politique d'autorisation (`ask`, `auto`, `allow`), profondeur de raisonnement (`off`, `low`, `high`, `max`) et compactage de contexte.
- **Inspecteur latéral à 3 onglets** :
  - **Aperçu** : statut Git (branche et fichiers modifiés), plan de travail (`todos` en temps réel), restauration de checkpoints (`Annuler`), et historique détaillé des outils.
  - **Fichiers** : explorateur de fichiers du projet avec filtrage, aperçu sécurisé en lecture seule et mention rapide `@fichier` dans le prompt.
  - **Diffs** : visualisation colorée des diffs générés par l'agent et statut Git du dépôt.
- **Palette de commandes (`Ctrl + K`)** et **Terminal PTY local (`Ctrl + \``)** redimensionnable.
