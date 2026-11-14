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

Pour mettre à jour Desktop, relance le même installateur ; il récupère la release la plus récente et remplace le paquet natif. Les paquets `.deb` et `.rpm` restent gérés par le gestionnaire système.

Le moteur Python peut être désinstallé avec `zerocode uninstall`. Les configurations, clés API et sessions sont conservées par défaut. `zerocode uninstall --remove-data` les supprime aussi, après confirmation.

Pour retirer Desktop, passe par les paramètres d’applications du système, ou utilise le gestionnaire de paquets Linux. L’AppImage utilisateur se retire en supprimant `~/.local/opt/zerocode`, son lanceur `~/.local/bin/zerocode-desktop` et le raccourci `.desktop`.

### Vérification des téléchargements

Le manifeste `SHA256SUMS` est publié dans chaque release. Il permet de détecter un téléchargement corrompu ou incomplet. Il n’apporte pas à lui seul une preuve d’identité de l’éditeur : les binaires ne sont pas encore signés avec un certificat éditeur Windows ou Apple.
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
