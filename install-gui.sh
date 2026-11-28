#!/usr/bin/env bash
set -Eeuo pipefail

REPO_RAW="https://raw.githubusercontent.com/hackerboy-223/zerocode/main"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/zerocode-installer.XXXXXX")"
INSTALLER="$TMP_DIR/install.sh"

cleanup() { [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]] && rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT

if ! command -v curl >/dev/null 2>&1; then
  printf 'Erreur : curl est requis pour télécharger ZeroCode.\n' >&2
  exit 1
fi

if ! command -v zenity >/dev/null 2>&1; then
  printf 'Zenity est absent : ouverture de l’installateur interactif en mode terminal.\n'
  curl -fsSL "$REPO_RAW/install.sh" -o "$INSTALLER"
  chmod 700 "$INSTALLER"
  bash "$INSTALLER"
fi

MODE="$(zenity --list --radiolist \
  --title="Installer ZeroCode" \
  --width=560 --height=360 \
  --text="Choisissez les composants à installer." \
  --column="" --column="Composant" --column="Description" \
  TRUE both "ZeroCode Desktop + interface terminal" \
  FALSE desktop "Application graphique uniquement" \
  FALSE tui "Interface terminal uniquement")" || exit 0

if [[ -z "$MODE" ]]; then exit 0; fi

zenity --question \
  --title="Confirmer l’installation" \
  --width=440 \
  --text="ZeroCode va installer : <b>$MODE</b>\n\nLes dépendances système manquantes pourront nécessiter votre mot de passe administrateur." \
  --ok-label="Installer" --cancel-label="Annuler" || exit 0

if ! curl -fsSL "$REPO_RAW/install.sh" -o "$INSTALLER"; then
  zenity --error --title="ZeroCode" --text="Impossible de télécharger l’installateur. Vérifiez votre connexion Internet."
  exit 1
fi
chmod 700 "$INSTALLER"

if command -v x-terminal-emulator >/dev/null 2>&1; then
  x-terminal-emulator -e bash -c '
    bash "$1" --source --mode "$2" --yes
    result=$?
    echo
    if [ "$result" -eq 0 ]; then
      echo "ZeroCode est prêt. Vous pouvez fermer cette fenêtre."
    else
      echo "L’installation a échoué (code $result)."
    fi
    read -r -p "Appuyez sur Entrée pour fermer…"
    rm -rf -- "$3"
    exit "$result"
  ' zerocode-installer "$INSTALLER" "$MODE" "$TMP_DIR"
  trap - EXIT
else
  zenity --info --title="ZeroCode" --text="Aucun émulateur de terminal n’a été détecté. L’installation va continuer dans ce terminal."
  bash "$INSTALLER" --source --mode "$MODE" --yes
fi
