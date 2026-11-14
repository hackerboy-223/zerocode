#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/hackerboy-223/zerocode.git"
INSTALL_REF="${ZEROCODE_INSTALL_REF:-feature/zerocode-desktop}"
INSTALL_MODE="${ZEROCODE_INSTALL_MODE:-}"
AUTO_YES="${ZEROCODE_INSTALL_YES:-0}"
BUILD_DIR=""
NODE_BIN=""
INPUT_FD=""

if { exec 3</dev/tty; } 2>/dev/null; then
  INPUT_FD="3"
elif [[ -t 0 ]]; then
  INPUT_FD="0"
fi

info()    { printf '\n\033[1;36m[ZeroCode]\033[0m %s\n' "$*"; }
success() { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn()    { printf '\033[1;33m[Note]\033[0m %s\n' "$*"; }
die()     { printf '\n\033[1;31m[Erreur]\033[0m %s\n' "$*" >&2; exit 1; }

on_error() {
  status=$?
  printf '\n\033[1;31m[Échec]\033[0m Installation interrompue (ligne %s, code %s).\n' "$1" "$status" >&2
  printf 'Corrige le prérequis indiqué ci-dessus, puis relance le même installateur.\n' >&2
  exit "$status"
}
cleanup() {
  if [[ -n "$BUILD_DIR" && -d "$BUILD_DIR" ]]; then rm -rf -- "$BUILD_DIR"; fi
}
trap 'on_error "$LINENO"' ERR
trap cleanup EXIT

usage() {
  cat <<'HELP'
Installateur ZeroCode

Usage:
  bash install.sh                  Menu interactif
  bash install.sh --mode tui       Installer la version terminal
  bash install.sh --mode desktop   Installer l'application graphique
  bash install.sh --mode both      Installer TUI + Desktop
  bash install.sh --yes --mode tui Confirmer automatiquement les étapes

Variables:
  ZEROCODE_INSTALL_REF     Branche ou tag à installer
  ZEROCODE_INSTALL_MODE    tui, desktop ou both
  ZEROCODE_INSTALL_YES     1 pour confirmer les étapes interactives
HELP
}

confirm() {
  question="$1"
  if [[ "$AUTO_YES" == "1" ]]; then return 0; fi
  [[ -n "$INPUT_FD" ]] || die "Confirmation impossible sans terminal. Relance avec --yes si tu acceptes les changements annoncés."
  read -r -u "$INPUT_FD" -p "$question [O/n] " answer
  [[ -z "$answer" || "$answer" =~ ^[OoYy]$ ]]
}

as_root() {
  if [[ "$(id -u)" == "0" ]]; then "$@"; else sudo "$@"; fi
}

detect_platform() {
  case "$(uname -s)" in
    Linux) PLATFORM="linux" ;;
    Darwin) PLATFORM="macos" ;;
    *) die "Ce script prend en charge Linux et macOS. Sur Windows, utilise install.ps1." ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64) ARCH="x64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) die "Architecture non prise en charge : $(uname -m)." ;;
  esac
  success "Système détecté : $PLATFORM ($ARCH)"
}

select_mode() {
  [[ -n "$INSTALL_MODE" ]] && return
  [[ -n "$INPUT_FD" ]] || die "Mode requis en non-interactif : --mode tui, --mode desktop ou --mode both."
  printf '\n'
  printf '  ┌──────────────────────────────────────────┐\n'
  printf '  │             ZEROCODE INSTALLER            │\n'
  printf '  ├──────────────────────────────────────────┤\n'
  printf '  │  1. TUI      Interface dans le terminal  │\n'
  printf '  │  2. Desktop  Application graphique       │\n'
  printf '  │  3. Les deux Installer TUI + Desktop     │\n'
  printf '  └──────────────────────────────────────────┘\n\n'
  read -r -u "$INPUT_FD" -p "Choisis une installation [1-3] : " choice
  case "$choice" in
    1) INSTALL_MODE="tui" ;;
    2) INSTALL_MODE="desktop" ;;
    3) INSTALL_MODE="both" ;;
    *) die "Choix invalide. Relance l'installateur et sélectionne 1, 2 ou 3." ;;
  esac
}

find_python() {
  for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      return 0
    fi
  done
  return 1
}

check_python() {
  if ! find_python; then
    info "Python 3.10+ absent : installation du runtime Python…"
    case "$PLATFORM" in
      macos)
        command -v brew >/dev/null 2>&1 || die "Python 3.10+ est requis. Installe Homebrew (https://brew.sh), puis relance pour installer Python automatiquement."
        brew install python@3.12
        export PATH="$(brew --prefix python@3.12)/bin:$PATH"
        ;;
      linux)
        if command -v apt-get >/dev/null 2>&1; then
          as_root apt-get update
          if apt-cache show python3.12 >/dev/null 2>&1; then
            as_root apt-get install -y python3.12 python3.12-venv
          else
            as_root apt-get install -y python3 python3-venv
          fi
        elif command -v dnf >/dev/null 2>&1; then
          as_root dnf install -y python3 python3-pip
        elif command -v pacman >/dev/null 2>&1; then
          as_root pacman -Sy --needed --noconfirm python python-pip
        else
          die "Python 3.10+ est requis. Installe-le depuis https://www.python.org/downloads/ puis relance."
        fi
        ;;
    esac
  fi
  find_python || die "Python 3.10+ reste introuvable après la tentative d'installation. Installe une version récente puis relance."
  success "Python : $("$PYTHON_BIN" --version)"
}

install_git() {
  command -v git >/dev/null 2>&1 && return
  info "Git est nécessaire pour récupérer le code ZeroCode."
  case "$PLATFORM" in
    macos)
      if command -v brew >/dev/null 2>&1; then
        brew install git
      elif xcode-select -p >/dev/null 2>&1; then
        die "Git n'est pas disponible. Installe Git ou Homebrew (https://brew.sh), puis relance."
      else
        xcode-select --install || true
        die "Installe Xcode Command Line Tools, qui fournissent Git, puis relance l'installateur."
      fi
      ;;
    linux)
      if command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update
        as_root apt-get install -y git
      elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y git
      elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -Sy --needed --noconfirm git
      else
        die "Installe Git avec le gestionnaire de paquets de ta distribution, puis relance."
      fi
      ;;
  esac
}

setup_pipx() {
  if command -v pipx >/dev/null 2>&1; then
    PIPX_KIND="binary"
    PIPX_BIN="$(command -v pipx)"
  elif "$PYTHON_BIN" -m pipx --version >/dev/null 2>&1; then
    PIPX_KIND="module"
  else
    info "Préparation d'un environnement isolé pour pipx…"
    BOOTSTRAP="$HOME/.local/share/zerocode/bootstrap/pipx"
    mkdir -p "$(dirname "$BOOTSTRAP")"
    if ! "$PYTHON_BIN" -m venv "$BOOTSTRAP" 2>/dev/null; then
      if command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update
        as_root apt-get install -y python3-venv
        "$PYTHON_BIN" -m venv "$BOOTSTRAP"
      else
        die "Le module venv de Python est absent. Installe le paquet venv de ta distribution puis relance."
      fi
    fi
    "$BOOTSTRAP/bin/python" -m pip install --upgrade pip pipx
    PIPX_KIND="binary"
    PIPX_BIN="$BOOTSTRAP/bin/pipx"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  pipx_run ensurepath >/dev/null 2>&1 || true
}

pipx_run() {
  if [[ "$PIPX_KIND" == "module" ]]; then
    "$PYTHON_BIN" -m pipx "$@"
  else
    "$PIPX_BIN" "$@"
  fi
}

install_engine() {
  info "Vérification des prérequis du moteur ZeroCode…"
  check_python
  install_git
  setup_pipx
  info "Installation du moteur et de ses dépendances dans un environnement isolé…"
  pipx_run install --force "git+$REPO_URL@$INSTALL_REF"
  export PATH="$HOME/.local/bin:$PATH"
  command -v zerocode >/dev/null 2>&1 || die "ZeroCode a été installé, mais sa commande n'est pas dans PATH. Ajoute ~/.local/bin à PATH puis relance."
  zerocode --version
  success "Moteur ZeroCode installé."
}

install_linux_build_dependencies() {
  info "Installation des bibliothèques natives nécessaires à Tauri…"
  if command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update
    as_root apt-get install -y build-essential curl wget file libssl-dev libgtk-3-dev libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev patchelf
  elif command -v dnf >/dev/null 2>&1; then
    as_root dnf install -y gcc gcc-c++ make curl wget file openssl-devel gtk3-devel webkit2gtk4.1-devel libappindicator-gtk3-devel librsvg2-devel libxdo-devel patchelf
  elif command -v pacman >/dev/null 2>&1; then
    as_root pacman -Sy --needed --noconfirm base-devel curl wget file openssl appmenu-gtk-module webkit2gtk-4.1 libappindicator-gtk3 librsvg xdotool patchelf fuse2
  else
    die "Distribution Linux non reconnue. Installe les dépendances Tauri indiquées dans docs/DESKTOP.md, puis relance."
  fi
}

ensure_macos_build_tools() {
  if ! xcode-select -p >/dev/null 2>&1; then
    warn "Les outils de compilation Apple (Xcode Command Line Tools) sont nécessaires."
    xcode-select --install || true
    die "Termine l'installation de Xcode Command Line Tools, puis relance l'installateur."
  fi
}

install_node() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    NODE_OK="$(node -e 'const p=process.versions.node.split(".").map(Number); process.exit((p[0] >= 24 || (p[0] === 22 && p[1] >= 12) || (p[0] === 20 && p[1] >= 19)) ? 0 : 1)' >/dev/null 2>&1; echo $?)"
    if [[ "$NODE_OK" == "0" ]]; then
      success "Node.js $(node --version) et npm $(npm --version) détectés."
      return
    fi
    warn "Node.js $(node --version) est trop ancien. Une version compatible sera installée localement."
  fi

  info "Installation de Node.js 24 (version locale à ZeroCode)…"
  command -v curl >/dev/null 2>&1 || die "curl est requis pour télécharger Node.js."
  command -v tar >/dev/null 2>&1 || die "tar est requis pour extraire Node.js."
  NODE_VERSION="$(curl -fsSL https://nodejs.org/dist/index.json | "$PYTHON_BIN" -c 'import json,sys; print(next(x["version"] for x in json.load(sys.stdin) if x["version"].startswith("v24.")))')"
  if [[ "$PLATFORM" == "macos" ]]; then NODE_OS="darwin"; NODE_EXT="tar.gz"; else NODE_OS="linux"; NODE_EXT="tar.xz"; fi
  NODE_ARCHIVE="node-$NODE_VERSION-$NODE_OS-$ARCH.$NODE_EXT"
  NODE_BASE="https://nodejs.org/dist/$NODE_VERSION"
  TEMP_NODE="$(mktemp -d)"
  curl -fsSL "$NODE_BASE/SHASUMS256.txt" -o "$TEMP_NODE/SHASUMS256.txt"
  curl -fL "$NODE_BASE/$NODE_ARCHIVE" -o "$TEMP_NODE/$NODE_ARCHIVE"
  EXPECTED_HASH="$(awk -v file="$NODE_ARCHIVE" '$2 == file || $2 == "*" file {print $1; exit}' "$TEMP_NODE/SHASUMS256.txt")"
  [[ -n "$EXPECTED_HASH" ]] || die "Le checksum officiel de Node.js est introuvable. Téléchargement annulé."
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s  %s\n' "$EXPECTED_HASH" "$TEMP_NODE/$NODE_ARCHIVE" | sha256sum -c -
  else
    printf '%s  %s\n' "$EXPECTED_HASH" "$TEMP_NODE/$NODE_ARCHIVE" | shasum -a 256 -c -
  fi
  TOOLCHAINS="$HOME/.local/share/zerocode/toolchains"
  mkdir -p "$TOOLCHAINS"
  tar -xf "$TEMP_NODE/$NODE_ARCHIVE" -C "$TOOLCHAINS"
  NODE_BIN="$TOOLCHAINS/node-$NODE_VERSION-$NODE_OS-$ARCH/bin"
  rm -rf -- "$TEMP_NODE"
  export PATH="$NODE_BIN:$PATH"
  node --version
  npm --version
}

install_rust() {
  if ! command -v rustup >/dev/null 2>&1; then
    info "Installation de Rust stable pour compiler l'application native…"
    TEMP_RUST="$(mktemp)"
    curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o "$TEMP_RUST"
    sh "$TEMP_RUST" -y --profile minimal --default-toolchain stable
    rm -f -- "$TEMP_RUST"
  fi
  [[ -f "$HOME/.cargo/env" ]] && source "$HOME/.cargo/env"
  command -v rustup >/dev/null 2>&1 || die "Rustup n'est pas disponible dans ce terminal. Rouvre le terminal puis relance."
  rustup toolchain install stable --profile minimal
  rustup default stable
  success "Rust : $(rustc --version)"
}

install_macos_app() {
  APP_SOURCE="$(find "$BUILD_DIR/source/desktop/src-tauri/target/release/bundle/macos" -maxdepth 1 -name '*.app' -print -quit 2>/dev/null || true)"
  [[ -n "$APP_SOURCE" ]] || die "L'application macOS n'a pas été générée. Consulte les erreurs de compilation."
  mkdir -p "$HOME/Applications"
  APP_DEST="$HOME/Applications/ZeroCode Desktop.app"
  if [[ -e "$APP_DEST" ]]; then
    BACKUP="$HOME/Applications/ZeroCode Desktop.backup-$(date +%Y%m%d-%H%M%S).app"
    mv "$APP_DEST" "$BACKUP"
    warn "Ancienne version conservée dans : $BACKUP"
  fi
  ditto "$APP_SOURCE" "$APP_DEST"
  success "Application installée : $APP_DEST"
}

install_linux_app() {
  BUNDLE_DIR="$BUILD_DIR/source/desktop/src-tauri/target/release/bundle"
  if command -v apt-get >/dev/null 2>&1; then
    PACKAGE="$(find "$BUNDLE_DIR/deb" -maxdepth 1 -type f -name '*.deb' -print -quit 2>/dev/null || true)"
    [[ -n "$PACKAGE" ]] || die "Le paquet .deb n'a pas été généré."
    info "Installation du paquet système : $PACKAGE"
    as_root apt-get install -y "$PACKAGE"
  elif command -v dnf >/dev/null 2>&1; then
    PACKAGE="$(find "$BUNDLE_DIR/rpm" -maxdepth 1 -type f -name '*.rpm' -print -quit 2>/dev/null || true)"
    [[ -n "$PACKAGE" ]] || die "Le paquet .rpm n'a pas été généré."
    info "Installation du paquet système : $PACKAGE"
    as_root dnf install -y "$PACKAGE"
  else
    APP_SOURCE="$(find "$BUNDLE_DIR/appimage" -maxdepth 1 -type f -name '*.AppImage' -print -quit 2>/dev/null || true)"
    [[ -n "$APP_SOURCE" ]] || die "Aucun paquet AppImage n'a été généré pour cette distribution."
    APP_DIR="$HOME/.local/opt/zerocode"
    mkdir -p "$APP_DIR" "$HOME/.local/bin" "$HOME/.local/share/applications"
    if [[ -e "$APP_DIR/ZeroCode.AppImage" ]]; then
      cp -p "$APP_DIR/ZeroCode.AppImage" "$APP_DIR/ZeroCode.AppImage.backup-$(date +%Y%m%d-%H%M%S)"
      warn "Ancienne AppImage conservée avant remplacement."
    fi
    if [[ -e "$HOME/.local/bin/zerocode-desktop" && ! -L "$HOME/.local/bin/zerocode-desktop" ]]; then
      mv "$HOME/.local/bin/zerocode-desktop" "$HOME/.local/bin/zerocode-desktop.backup-$(date +%Y%m%d-%H%M%S)"
    fi
    cp "$APP_SOURCE" "$APP_DIR/ZeroCode.AppImage"
    chmod 755 "$APP_DIR/ZeroCode.AppImage"
    ln -sfn "$APP_DIR/ZeroCode.AppImage" "$HOME/.local/bin/zerocode-desktop"
    printf '[Desktop Entry]\nType=Application\nName=ZeroCode Desktop\nComment=Agent de développement ZeroCode\nExec="%s"\nTerminal=false\nCategories=Development;Utility;\n' "$APP_DIR/ZeroCode.AppImage" > "$HOME/.local/share/applications/zerocode-desktop.desktop"
    success "Application installée dans $APP_DIR. Lance-la avec zerocode-desktop."
  fi
}

install_desktop() {
  [[ "$PLATFORM" == "linux" ]] && install_linux_build_dependencies
  [[ "$PLATFORM" == "macos" ]] && ensure_macos_build_tools
  install_node
  install_rust

  info "Récupération du code source de ZeroCode…"
  BUILD_DIR="$(mktemp -d)"
  git clone --depth 1 --branch "$INSTALL_REF" "$REPO_URL" "$BUILD_DIR/source"
  [[ -f "$BUILD_DIR/source/desktop/package-lock.json" ]] || die "Le projet Desktop ou son package-lock.json est absent de la branche $INSTALL_REF."

  info "Installation des dépendances frontend…"
  (cd "$BUILD_DIR/source/desktop" && npm ci)

  if [[ "$PLATFORM" == "macos" ]]; then
    BUNDLE_TARGET="dmg"
  elif command -v apt-get >/dev/null 2>&1; then
    BUNDLE_TARGET="deb"
  elif command -v dnf >/dev/null 2>&1; then
    BUNDLE_TARGET="rpm"
  else
    BUNDLE_TARGET="appimage"
  fi

  info "Compilation de ZeroCode Desktop (première compilation parfois longue)…"
  (cd "$BUILD_DIR/source/desktop" && npm run app:build -- --bundles "$BUNDLE_TARGET")

  if [[ "$PLATFORM" == "macos" ]]; then install_macos_app; else install_linux_app; fi
  success "ZeroCode Desktop est installé."
}

main() {
  [[ "$(id -u)" != "0" ]] || die "Ne lance pas l'installateur avec sudo. Il gère sudo uniquement pour les dépendances système."
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; return 0 ;;
      --yes) AUTO_YES="1"; shift ;;
      --mode)
        [[ "$#" -ge 2 ]] || die "L'option --mode attend tui, desktop ou both."
        INSTALL_MODE="$2"
        shift 2
        ;;
      *) die "Option inconnue : $1. Utilise --help pour voir les options." ;;
    esac
  done
  detect_platform
  select_mode
  case "$INSTALL_MODE" in
    tui|desktop|both) ;;
    *) die "Mode inconnu : $INSTALL_MODE (attendu : tui, desktop ou both)." ;;
  esac

  info "Installation sélectionnée : $INSTALL_MODE"
  info "Branche source : $INSTALL_REF"
  confirm "Continuer ? Les dépendances manquantes et les applications sélectionnées seront installées." || die "Installation annulée."

  install_engine
  if [[ "$INSTALL_MODE" == "desktop" || "$INSTALL_MODE" == "both" ]]; then install_desktop; fi

  printf '\n'
  success "Installation terminée."
  if [[ "$INSTALL_MODE" == "tui" || "$INSTALL_MODE" == "both" ]]; then printf '  TUI : zerocode\n'; fi
  if [[ "$INSTALL_MODE" == "desktop" || "$INSTALL_MODE" == "both" ]]; then
    if [[ "$PLATFORM" == "macos" ]]; then
      printf '  Desktop : ~/Applications/ZeroCode Desktop.app\n'
    elif [[ -x "$HOME/.local/bin/zerocode-desktop" ]]; then
      printf '  Desktop : zerocode-desktop\n'
    else
      printf '  Desktop : disponible dans le menu des applications\n'
    fi
  fi
  printf '\nPour vérifier le moteur : zerocode doctor\n'
  printf 'Aucune clé API personnelle n'est requise pour commencer avec le mode auto.\n'
  if [[ -n "$NODE_BIN" ]]; then
    printf '\nNode.js local : %s\nAjoute ce dossier à PATH si tu souhaites utiliser Node.js hors de ZeroCode.\n' "$NODE_BIN"
  fi
}
main "$@"
