# ZeroCode Desktop

ZeroCode Desktop est l’interface graphique native de l’agent Python existant. Elle utilise le moteur installé sur la machine, et non un environnement d’exécution hébergé.

## Fonctionnement

- **Interface** : React, TypeScript, Vite et Tauri 2.
- **Agent** : processus Python local via \`zerocode desktop-bridge\`.
- **Terminal** : pseudo-terminal natif (PTY), ouvert dans le dossier du projet.
- **Sessions** : réutilise le stockage de sessions de ZeroCode.
- **Autorisations** : les demandes d’écriture, de commande et de privilèges remontent dans l’interface. Une absence de réponse est traitée comme un refus.
- **Démarrage sûr** : Desktop démarre en mode \`ask\`, même si le CLI est configuré en \`allow\`. L’accès aux fichiers reste limité au workspace et les fichiers de secrets restent protégés. Le mode Full-stack exige une confirmation explicite.
- **DLP** : les sorties du shell sont limitées et filtrées avant affichage ; les secrets connus sont masqués dans les événements du bridge.
- **Annulation prudente** : les checkpoints récents enregistrent l’empreinte du fichier après modification. \`Annuler\` refuse d’écraser un fichier modifié depuis et bloque les chemins hors workspace.
- **Mascotte** : LUPUS, dessin vectoriel animé, sans ressource externe.

Les commandes de l’agent et le shell s’exécutent sur l’ordinateur qui héberge l’application. Les prompts, extraits de fichiers et réponses peuvent toutefois être transmis au fournisseur de modèle sélectionné. Pour garder l’inférence locale, configure un fournisseur local compatible, par exemple Ollama. Vérifie toujours les paramètres de confidentialité du fournisseur distant avant d’envoyer du code privé.

Le terminal intégré est un nouveau shell interactif du projet. Il ne prend pas le contrôle d’une fenêtre de terminal externe déjà ouverte.

## Installer ZeroCode Desktop

L’installateur officiel présente un menu avec trois choix :

1. **TUI** : installe uniquement le moteur Python et l’interface terminale.
2. **Desktop** : installe le moteur requis par l’application, prépare l’environnement de compilation, construit l’application native puis lance ou installe le paquet.
3. **Les deux** : installe les deux interfaces.

Le moteur Python est installé avec \`pipx\`, dans un environnement isolé. Le choix Desktop inclut donc aussi la commande \`zerocode\` et le pont local \`zerocode desktop-bridge\`.

### Linux et macOS

Depuis le terminal :

\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/hackerboy-223/zerocode/feature/zerocode-desktop/install.sh | bash
\`\`\`

Choisis Desktop dans le menu. L’installateur vérifie Python, Git, Node.js et Rust, installe les bibliothèques natives nécessaires et compile Tauri. Node.js 24 est téléchargé dans le dossier utilisateur si la version du système n’est pas compatible ; son checksum officiel SHA-256 est vérifié avant extraction.

Pour lancer un mode directement depuis une copie locale du dépôt :

\`\`\`bash
bash install.sh --mode tui
bash install.sh --mode desktop
bash install.sh --mode both
\`\`\`

Sur Debian/Ubuntu, le paquet \`.deb\` est installé avec apt et nécessite une confirmation administrateur. Fedora utilise le paquet RPM. Les distributions Arch utilisent l’AppImage dans le dossier utilisateur. macOS installe l’application dans \`~/Applications/ZeroCode Desktop.app\`.

Sur macOS, Xcode Command Line Tools doit être installé. L’installateur déclenche son installation si nécessaire ; termine-la puis relance le script.

### Windows

Dans PowerShell :

\`\`\`powershell
irm https://raw.githubusercontent.com/hackerboy-223/zerocode/feature/zerocode-desktop/install.ps1 | iex
\`\`\`

Le parcours Desktop utilise \`winget\` pour préparer Node.js, Rustup, Visual Studio C++ Build Tools, WebView2 et NSIS. Il compile ensuite l’application et ouvre l’installateur NSIS natif. App Installer / winget doit être disponible sur la machine.

### Prérequis de compilation

Pour un développement manuel, les versions prises en charge sont :

- Python 3.10+.
- Node.js 20.19+ ou 22.12+ et npm.
- Rust stable et Cargo.
- Git.
- Les outils C++ natifs et bibliothèques WebKit propres au système.

#### Linux (Ubuntu / Debian)

\`\`\`bash
sudo apt update
sudo apt install -y build-essential curl wget file libssl-dev libgtk-3-dev libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev patchelf
\`\`\`

#### macOS

Installe Xcode Command Line Tools :

\`\`\`bash
xcode-select --install
\`\`\`

Git et les outils Apple doivent être accessibles dans le terminal.

#### Windows

Installe Visual Studio 2022 Build Tools avec le workload **Desktop development with C++**, WebView2 Runtime, Node.js LTS, Rustup et NSIS. Le parcours automatique utilise winget pour ces composants.

## Développement

Depuis la racine du dépôt :

\`\`\`bash
cd desktop
npm ci
npm run app:dev
\`\`\`

L’application Tauri démarre avec le serveur Vite local. Le terminal intégré s’ouvre dans le dossier du projet sélectionné.

## Construire l’application manuellement

\`\`\`bash
cd desktop
npm ci
npm run app:build
\`\`\`

Les artefacts natifs sont générés dans \`desktop/src-tauri/target/release/bundle/\`. La compilation doit être réalisée sur chaque système cible (Linux, Windows ou macOS) avec ses dépendances de développement propres.

## Résolution des problèmes

**« ZeroCode CLI introuvable »**  
Vérifie \`zerocode doctor\` dans ton terminal habituel, puis ouvre l’application depuis le même compte utilisateur. L’application recherche aussi les emplacements pipx courants sous \`~/.local/bin\` et \`~/.local/share/pipx/venvs/zerocode/bin\`. Pour un autre emplacement, configure \`ZEROCODE_EXECUTABLE\`.

**L’application s’ouvre mais aucun modèle n’est disponible**  
Vérifie le réseau et lance \`zerocode doctor --live\`. Le shell et les fichiers restent locaux, mais la route de modèle peut nécessiter un accès réseau.

**Le terminal est vide ou ne démarre pas**  
Vérifie que le shell défini par \`$SHELL\` existe. Sur Linux, vérifie la présence des bibliothèques WebKit indiquées plus haut.

## Périmètre de cette version

Cette version fournit :
- **Fenêtre desktop native** (Tauri 2 + React + TypeScript) avec icônes multi-plateformes configurées.
- **Fil de conversation enrichi** : blocs de code formatés avec copie rapide, affichage repliable du raisonnement (\`think\`), et gestion complète des sessions (reprise, création, suppression).
- **Modes d'agent & Préférences (\`Ctrl + ,\`)** : bascule Build / Plan / Full-stack, sélection du modèle (\`auto\` ou modèle spécifique), politique d'autorisation (\`ask\`, \`auto\`, \`allow\`), profondeur de raisonnement (\`off\`, \`low\`, \`high\`, \`max\`) et compactage de contexte.
- **Inspecteur latéral à 3 onglets** :
  - **Aperçu** : statut Git (branche et fichiers modifiés), plan de travail (\`todos\` en temps réel), restauration de checkpoints (\`Annuler\`), et historique détaillé des outils.
  - **Fichiers** : explorateur de fichiers du projet avec filtrage, aperçu sécurisé en lecture seule et mention rapide \`@fichier\` dans le prompt.
  - **Diffs** : visualisation colorée des diffs générés par l'agent et statut Git du dépôt.
- **Palette de commandes (\`Ctrl + K\`)** et **Terminal PTY local** redimensionnable.
