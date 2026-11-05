from __future__ import annotations

import re

PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
API_TOKEN_RE = re.compile(
    r"\b(?:"
    r"sk-or-v1-[A-Za-z0-9_-]{20,}|"
    r"sk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,}|"
    r"nvapi-[A-Za-z0-9_-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{35}|"
    r"gsk_[A-Za-z0-9]{20,}|"
    r"hf_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}"
    r")\b"
)
BEARER_TOKEN_RE = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._\-]{20,}\b")
DSN_PASSWORD_RE = re.compile(
    r"(?i)\b((?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss|amqp)://"
    r"[^:/@\s]+:)([^@/\s]{4,})(@"
    r"[^\s\"']+)"
)

CATASTROPHIC_SHELL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?:^|[;&|]\s*)(?:sudo\s+)?rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+|--no-preserve-root\s+)+"
            r"(?:/(?:\*|\s|$)|~(?:/|\s|$)|\$HOME(?:/|\s|$))"
        ),
        "Suppression recursive de la racine (/) ou du repertoire personnel (~) interdite.",
    ),
    (
        re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
        "Fork bomb detectee et bloquee.",
    ),
    (
        re.compile(
            r"(?:^|[;&|]\s*)(?:sudo\s+)?(?:mkfs(?:\.[a-z0-9]+)?|wipefs)\s+/dev/"
        ),
        "Formatage direct de peripherique bloc (/dev/*) interdit.",
    ),
    (
        re.compile(
            r"(?:^|[;&|]\s*)(?:sudo\s+)?dd\s+[^;&|\n]*\bof=/dev/(?:sd[a-z]|nvme\d+n\d+|vd[a-z]|hd[a-z]|disk\d+)"
        ),
        "Ecriture brute sur un peripherique disque (/dev/*) interdite.",
    ),
    (
        re.compile(
            r"(?:^|[;&|]\s*)(?:sudo\s+)?chmod\s+(?:-[a-zA-Z]*R[a-zA-Z]*\s+|--recursive\s+)+[0-7]{3,4}\s+/(?:\s|$)"
        ),
        "Modification recursive des permissions sur la racine (/) interdite.",
    ),
)


def redact_secrets(text: str) -> str:
    """Masque les clés privées, jetons API et mots de passe de connexion dans un texte."""
    if not text:
        return text
    cleaned = PEM_PRIVATE_KEY_RE.sub("[SECRET MASQUE: CLE PRIVEE]", text)
    cleaned = API_TOKEN_RE.sub("[SECRET MASQUE: JETON API]", cleaned)
    cleaned = BEARER_TOKEN_RE.sub(r"\1[SECRET MASQUE]", cleaned)
    cleaned = DSN_PASSWORD_RE.sub(r"\1[SECRET MASQUE]\3", cleaned)
    return cleaned


def check_dangerous_command(command: str) -> str | None:
    """Retourne un motif de blocage si la commande shell est catastrophique pour l'hôte."""
    normalized = " ".join(command.strip().split())
    if not normalized:
        return None
    for pattern, reason in CATASTROPHIC_SHELL_PATTERNS:
        if pattern.search(normalized):
            return reason
    return None
