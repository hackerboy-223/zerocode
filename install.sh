#!/usr/bin/env bash
set -Eeuo pipefail

REPO="git+https://github.com/hackerboy-223/zerocode.git"
say() { printf '\n\033[1;36m[ZeroCode]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[Erreur]\033[0m %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || fail "Python 3.10+ est requis. Installe Python depuis https://www.python.org/downloads/ puis relance."
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 ou plus récent est requis.")
print(f"Python {sys.version.split()[0]} détecté.")
PY

if ! command -v pipx >/dev/null 2>&1; then
  say "Installation de pipx (environnement Python isolé)…"
  if command -v brew >/dev/null 2>&1; then
    brew install pipx
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y pipx
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y pipx
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --needed --noconfirm python-pipx
  else
    python3 -m pip install --user pipx || fail "Installe pipx avec le gestionnaire de paquets de ton système, puis relance."
  fi
fi

export PATH="$HOME/.local/bin:$HOME/.local/pipx/venvs/pipx/bin:$PATH"
python3 -m pipx ensurepath >/dev/null 2>&1 || true
command -v pipx >/dev/null 2>&1 || fail "pipx est installé mais absent du PATH. Rouvre le terminal puis relance install.sh."

say "Installation de ZeroCode et de toutes ses dépendances…"
pipx install --force "$REPO"

export PATH="$HOME/.local/bin:$PATH"
if command -v zerocode >/dev/null 2>&1; then
  say "Vérification…"
  zerocode --version
  zerocode doctor || true
else
  say "Installation terminée. Rouvre le terminal pour actualiser le PATH."
fi
say "C'est prêt ! Lance simplement : zerocode"
say "Aucune clé API personnelle n'est requise. Le mode auto utilise les routes gratuites anonymes disponibles."
