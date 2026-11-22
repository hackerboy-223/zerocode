# Guide d'installation de ZeroCode

ZeroCode est un agent de développement disponible dans le terminal (**TUI**) et dans une application graphique native (**Desktop**).

> **Version stable :** [v1.0.0](https://github.com/hackerboy-223/zerocode/releases/tag/v1.0.0)  
> **Dépôt :** https://github.com/hackerboy-223/zerocode  
> **Dernière release :** https://github.com/hackerboy-223/zerocode/releases/latest

Ce guide couvre l'installation sur Linux, macOS et Windows, le premier démarrage, les mises à jour et la désinstallation.

## 1. Choisir son installation

L'installateur propose trois modes :

| Mode | Ce qui est installé |
| --- | --- |
| `tui` | Le moteur ZeroCode et son interface dans le terminal |
| `desktop` | Le moteur ZeroCode et l'application graphique |
| `both` | Le moteur ZeroCode, la TUI et Desktop |

**Recommandation :** choisis `both` pour profiter des deux interfaces. Tu peux aussi commencer uniquement par la TUI, plus légère.

### Plateformes Desktop précompilées en v1.0.0

| Système | Architecture | Format publié |
| --- | --- | --- |
| Linux | x86_64 / amd64 | `.deb`, `.rpm`, AppImage |
| Windows | x64 | Installateur `.exe`, package `.msi` |
| macOS | Intel x86_64 | `.dmg` |
| macOS | Apple Silicon arm64 | `.dmg` |

Le moteur TUI est distribué sous forme de wheel Python universel. Les binaires Desktop de cette release ne couvrent pas Linux ARM ni Windows ARM ; sur ces architectures, utilise la TUI ou suis le parcours de compilation depuis les sources décrit dans [docs/DESKTOP.md](docs/DESKTOP.md).

## 2. Avant de commencer

- Une connexion Internet pour télécharger ZeroCode et accéder au fournisseur de modèles.
- Un compte utilisateur normal sur la machine.
- Python **3.10 ou supérieur** pour le moteur. L'installateur tente de préparer Python lorsqu'il manque.
- Sous Linux, `sudo` peut être demandé pour installer le paquet Desktop ou les dépendances système.

Avec une release stable, les installateurs récupèrent les paquets déjà compilés. Tu n'as donc pas besoin d'installer Node.js, Rust ou Visual Studio Build Tools pour le parcours normal de v1.0.0.

**Ne lance pas l'installateur Linux/macOS avec sudo.** Il utilise les privilèges administrateur uniquement pour les opérations système qui le nécessitent.

## 3. Installation sur Linux

Ouvre un terminal puis exécute :

```bash
curl -fsSL https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.sh | bash
```

Le menu te demande de choisir :

1. `TUI` : terminal uniquement ;
2. `Desktop` : application graphique ;
3. `Les deux` : TUI + Desktop.

Confirme ensuite l'installation. L'installateur télécharge la release stable, vérifie les empreintes SHA-256 des fichiers utilisés et installe les composants sélectionnés.

### Choisir directement un mode

Pour afficher le menu, la commande précédente suffit. Pour choisir un mode sans menu, télécharge d'abord le script officiel :

```bash
curl -fsSLo /tmp/zerocode-install.sh https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.sh
```

Puis lance l'une des commandes :

```bash
bash /tmp/zerocode-install.sh --mode tui
bash /tmp/zerocode-install.sh --mode desktop
bash /tmp/zerocode-install.sh --mode both
```

Pour installer explicitement la version `v1.0.0` :

```bash
bash /tmp/zerocode-install.sh --version v1.0.0 --mode both
```

### Quel paquet Linux est utilisé ?

- Debian, Ubuntu et distributions compatibles : paquet `.deb` installé avec `apt`.
- Fedora et distributions compatibles : paquet `.rpm`.
- Autres distributions Linux prises en charge par l'installateur : AppImage dans le dossier utilisateur.

L'installateur utilise `sudo` lorsque le gestionnaire de paquets doit installer le paquet système.

## 4. Installation sur macOS

Ouvre Terminal et lance :

```bash
curl -fsSL https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.sh | bash
```

Choisis `TUI`, `Desktop` ou `Les deux`. Le script détecte l'architecture du Mac et télécharge le DMG correspondant :

- Apple Silicon : arm64 (puces Apple) ;
- Mac Intel : x86_64.

L'application est copiée dans `~/Applications/ZeroCode Desktop.app`.

**À propos de Gatekeeper :** les binaires v1.0.0 ne sont pas encore signés et notarisés par Apple. macOS peut donc afficher un avertissement de développeur non identifié. Vérifie que tu as téléchargé le fichier depuis la release officielle avant de décider de l'ouvrir. N'ignore jamais un avertissement si l'origine du fichier n'est pas certaine.

## 5. Installation sur Windows

Ouvre **PowerShell** avec ton compte utilisateur normal, puis exécute :

```powershell
irm https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.ps1 | iex
```

Choisis `TUI`, `Desktop` ou `Les deux`, puis confirme.

Pour sélectionner directement le mode et la version, télécharge le script et exécute-le avec ses paramètres :

```powershell
$installer = Join-Path $env:TEMP "zerocode-install.ps1"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.ps1" -OutFile $installer

# TUI + Desktop, version stable v1.0.0
& $installer -Mode both -Version v1.0.0
```

Tu peux remplacer `both` par `tui` ou `desktop`. Pour examiner le script avant son exécution :

```powershell
Get-Content $installer
```

L'installateur récupère le wheel Python vérifié puis lance l'installateur natif Windows (`.exe`) pour Desktop. `winget`, Node.js, Rust et Visual Studio Build Tools ne sont pas nécessaires pour le parcours de release stable.

Le binaire Windows n'est pas encore signé avec un certificat éditeur. Windows peut afficher un avertissement SmartScreen ou éditeur inconnu. Vérifie toujours l'origine du fichier sur la [page officielle des releases](https://github.com/hackerboy-223/zerocode/releases/tag/v1.0.0).

## 6. Installer une version précise ou utiliser une branche source

Par défaut, l'installateur récupère la dernière release stable. Pour choisir une version précise, utilise `--version` sous Linux/macOS :

```bash
bash /tmp/zerocode-install.sh --version v1.0.0 --mode both
```

Sous Windows :

```powershell
& $installer -Mode both -Version v1.0.0
```

Pour les tests ou le développement, tu peux forcer l'installation depuis la branche `main`. **Ce mode peut compiler Desktop sur ta machine et installer les outils de développement nécessaires.**

Linux/macOS :

```bash
ZEROCODE_INSTALL_REF=main bash /tmp/zerocode-install.sh --mode both
```

Windows :

```powershell
$env:ZEROCODE_INSTALL_REF = "main"
& $installer -Mode both
Remove-Item Env:ZEROCODE_INSTALL_REF
```

N'utilise pas ce parcours source si tu souhaites simplement installer la version stable.

## 7. Vérifier l'installation

Ferme puis rouvre ton terminal si la commande n'est pas immédiatement reconnue.

Vérifie la version :

```bash
zerocode --version
```

Lance le diagnostic :

```bash
zerocode doctor
```

Puis démarre l'interface terminal :

```bash
zerocode
```

Pour demander directement une tâche à l'agent :

```bash
zerocode "explique la structure de ce projet"
```

Sous Windows, les commandes sont identiques dans une nouvelle fenêtre PowerShell.

### Démarrer Desktop

- **Linux :** cherche ZeroCode Desktop dans le menu des applications. Pour une installation AppImage utilisateur, lance `zerocode-desktop`.
- **Windows :** ouvre ZeroCode Desktop depuis le menu Démarrer.
- **macOS :** ouvre `ZeroCode Desktop.app` dans le dossier Applications de ton compte.

## 8. Premier démarrage et modèles

Le mode automatique (`auto`) permet de commencer sans saisir ta propre clé API grâce à la route gratuite configurée par défaut. Une connexion Internet reste nécessaire pour joindre le fournisseur de modèles. La disponibilité et les limites du fournisseur peuvent évoluer.

Pour vérifier les fournisseurs et la connexion :

```bash
zerocode doctor --live
```

Tu peux configurer d'autres fournisseurs et tes propres clés API. Consulte [docs/PROVIDERS.md](docs/PROVIDERS.md) pour les paramètres disponibles. Ne partage jamais une clé API dans une conversation, une capture d'écran ou un dépôt public.

### Confidentialité

Les commandes et opérations sur les fichiers s'exécutent localement. Cependant, les prompts, extraits de code utiles à la tâche et réponses peuvent être transmis au fournisseur de modèle sélectionné. Consulte sa politique de confidentialité avant d'utiliser ZeroCode avec un dépôt confidentiel.

## 9. Mettre à jour ou réparer

### Linux et macOS — moteur TUI

Vérifie d'abord si une mise à jour est disponible :

```bash
zerocode update --check
```

Puis mets à jour :

```bash
zerocode update
```

Pour réparer le moteur avec une réinstallation vérifiée :

```bash
zerocode repair
```

### Windows — moteur TUI

Ferme les fenêtres et processus ZeroCode, ouvre une nouvelle fenêtre PowerShell puis relance l'installateur officiel. Pour choisir explicitement la version :

```powershell
$env:ZEROCODE_INSTALL_REF = "v1.0.0"
irm https://raw.githubusercontent.com/hackerboy-223/zerocode/main/install.ps1 | iex
Remove-Item Env:ZEROCODE_INSTALL_REF
```

### Desktop — toutes plateformes

Relance le même installateur officiel et choisis `Desktop` ou `Les deux`. Il récupère la dernière release stable et installe le paquet natif correspondant au système.

## 10. Vérifier manuellement les sommes SHA-256

Les scripts d'installation officiels téléchargent `SHA256SUMS` et vérifient automatiquement les paquets avant installation.

Le manifeste contient une ligne pour **chaque fichier** de la release. Si tu n'as téléchargé qu'un seul paquet, vérifie uniquement sa ligne : lancer `sha256sum -c SHA256SUMS` sur le manifeste complet signalerait aussi les autres fichiers comme absents.

Télécharge le paquet choisi et `SHA256SUMS` dans le même dossier, puis adapte le nom du fichier dans les exemples.

Linux (exemple Debian/Ubuntu) :

§§§bash
ASSET="zerocode-desktop-1.0.0-linux-amd64.deb"
grep -F "  $ASSET" SHA256SUMS > selected-checksum.txt &&
sha256sum -c selected-checksum.txt
§§§

macOS (exemple Apple Silicon) :

§§§bash
ASSET="zerocode-desktop-1.0.0-darwin-aarch64.dmg"
grep -F "  $ASSET" SHA256SUMS > selected-checksum.txt &&
shasum -a 256 -c selected-checksum.txt
§§§

Windows PowerShell :

§§§powershell
$asset = "zerocode-desktop-1.0.0-windows-x64-setup.exe"
$entry = Get-Content .\SHA256SUMS | Where-Object {
    $_ -match "  $([regex]::Escape($asset))$"
} | Select-Object -First 1

if (-not $entry) { throw "Aucune empreinte trouvée pour $asset dans SHA256SUMS." }

$expected = ($entry -split '\s+')[0]
$actual = (Get-FileHash ".\$asset" -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw "Échec de vérification SHA-256 pour $asset." }

Write-Host "SHA-256 vérifié : $asset" -ForegroundColor Green
§§§

Pour contrôler **tous** les fichiers de la release, télécharge l'ensemble des assets dans le même dossier que le manifeste, puis exécute `sha256sum -c SHA256SUMS` sous Linux ou `shasum -a 256 -c SHA256SUMS` sous macOS.

Les empreintes détectent une corruption ou une modification des fichiers, mais ne prouvent pas à elles seules l'identité de l'éditeur.

**En cas d'échec de vérification, n'installe pas le fichier.** Télécharge à nouveau l'asset et le manifeste depuis la [release officielle](https://github.com/hackerboy-223/zerocode/releases/tag/v1.0.0).

## 11. Désinstaller ZeroCode

### Moteur Python / TUI

Linux et macOS :

```bash
zerocode uninstall
```

Cette commande conserve les paramètres, les clés API et les sessions par défaut.

Pour supprimer aussi les données utilisateur — opération irréversible — :

```bash
zerocode uninstall --remove-data
```

Windows, dans une nouvelle fenêtre PowerShell après avoir fermé ZeroCode :

```powershell
pipx uninstall zerocode
```

Cette commande retire le moteur Python, mais conserve les données utilisateur.

### Application Desktop

- **Windows :** désinstalle ZeroCode Desktop depuis Paramètres → Applications → Applications installées.
- **macOS :** supprime `ZeroCode Desktop.app` du dossier Applications de ton compte.
- **Debian/Ubuntu :** `sudo apt remove zerocode-desktop`.
- **Fedora :** `sudo dnf remove zerocode-desktop`.
- **Installation AppImage :** supprime `~/.local/opt/zerocode`, `~/.local/bin/zerocode-desktop` et `~/.local/share/applications/zerocode-desktop.desktop`.

## 12. Dépannage

### La commande zerocode est introuvable

1. Ferme et rouvre le terminal.
2. Vérifie que le répertoire utilisateur de pipx est dans ton `PATH`.
3. Sous Linux/macOS, exécute `python3 -m pipx ensurepath`, puis rouvre le terminal.
4. Sous Windows, exécute `py -m pipx ensurepath`, puis rouvre PowerShell.

### Le diagnostic ne détecte aucun modèle

- Vérifie la connexion Internet.
- Lance `zerocode doctor --live`.
- Vérifie la configuration du fournisseur sélectionné.
- Consulte [docs/PROVIDERS.md](docs/PROVIDERS.md).

### Desktop ne démarre pas

- Vérifie que le moteur est disponible avec `zerocode doctor`.
- Sous Linux, vérifie que le paquet a été installé correctement et que le système dispose des bibliothèques graphiques requises.
- Sur macOS et Windows, vérifie les avertissements de sécurité et assure-toi que le fichier vient de la release officielle.

### L'empreinte SHA-256 ne correspond pas

Arrête l'installation. Ne contourne pas le contrôle. Supprime le téléchargement incomplet, récupère de nouveau le paquet et `SHA256SUMS` depuis GitHub, puis recommence.

### Consulter les versions et signaler un problème

- [Toutes les releases](https://github.com/hackerboy-223/zerocode/releases)
- [Code source et documentation](https://github.com/hackerboy-223/zerocode)
- [Signaler un bug](https://github.com/hackerboy-223/zerocode/issues)

---

Créé par **H@CKERBOY** · [GitHub](https://github.com/hackerboy-223) · [ZeroCode](https://github.com/hackerboy-223/zerocode)
