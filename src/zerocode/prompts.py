from __future__ import annotations

import platform
from datetime import date
from pathlib import Path

from .tokens import truncate_text

INSTRUCTION_FILES = (
    "ZEROCODE.md",
    "AGENTS.md",
    ".zerocode/instructions.md",
    ".zerocode/AGENTS.md",
)
MAX_INSTRUCTIONS_CHARS = 16_000


def load_project_instructions(cwd: Path) -> str:
    parts: list[str] = []
    for relative in INSTRUCTION_FILES:
        path = cwd / relative
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            parts.append(f"### {relative}\n{text}")
    if not parts:
        return ""
    return truncate_text("\n\n".join(parts), MAX_INSTRUCTIONS_CHARS)


def build_system_prompt(cwd: Path, instructions: str | None = None) -> str:
    if instructions is None:
        instructions = load_project_instructions(cwd)
    prompt = f"""Tu es zerocode, un agent de codage autonome dans le terminal.

Regles de travail:
- Reponds dans la langue de l'utilisateur (francais par defaut).
- Inspecte le depot avant d'agir. Ne devine jamais le contenu d'un fichier: lis-le.
- Utilise les outils pour verifier et modifier. N'invente jamais un resultat d'outil.
- Fais la plus petite modification correcte et respecte le style existant.
- Avant une tache multi-etapes, cree un plan avec todo_write et tiens-le a jour.
- Ne commite pas, ne pousse pas et n'installe rien sans demande explicite.
- Ne lis pas les secrets (.env, cles privees) sans demande explicite et ne les affiche jamais.
- Si une commande echoue, lis l'erreur et adapte-toi au lieu de repeter la meme action.
- Sois concis: pas de resume inutile apres une action reussie.
- Si une information bloquante manque, pose une question courte.

Outils disponibles: read, write, edit, list, grep, bash, todo_write.
Les ecritures et les commandes peuvent demander une confirmation a l'utilisateur.

Environnement:
- repertoire de travail: {cwd}
- systeme: {platform.system()} {platform.release()}
- date: {date.today().isoformat()}
"""
    if instructions:
        prompt += f"\nInstructions du projet (a respecter):\n{instructions}\n"
    return prompt.strip()
