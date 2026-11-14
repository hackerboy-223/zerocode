#!/usr/bin/env python3
"""Importe les Patterns Fabric comme skills ZeroCode locaux.

Les fichiers importés sont des instructions Markdown : ils ne sont jamais exécutés.
Source : https://github.com/danielmiessler/fabric (MIT).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com/repos/danielmiessler/fabric"
RAW = "https://raw.githubusercontent.com/danielmiessler/fabric"
USER_AGENT = "ZeroCode-Fabric-Skill-Sync/1.0"
MAX_FILE_BYTES = 180_000
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def request(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read(MAX_FILE_BYTES + 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Importer les Patterns Fabric dans les skills ZeroCode.")
    parser.add_argument("--branch", default="main", help="Branche Fabric (défaut : main).")
    parser.add_argument("--category", action="append", default=[], help="Catégorie à importer (répétable).")
    parser.add_argument("--dest", type=Path, help="Dossier cible (défaut : ~/.config/zerocode/skills).")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les fichiers sans rien écrire.")
    parser.add_argument("--force", action="store_true", help="Remplacer les skills déjà présents.")
    args = parser.parse_args()

    destination = (args.dest or Path.home() / ".config" / "zerocode" / "skills").expanduser()
    try:
        tree = json.loads(request(f"{API}/git/trees/{args.branch}?recursive=1"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Impossible de récupérer l'arborescence Fabric : {exc}", file=sys.stderr)
        return 1

    wanted = {item.strip().lower() for item in args.category if item.strip()}
    patterns = []
    for entry in tree.get("tree", []):
        path = entry.get("path", "")
        parts = path.split("/")
        if len(parts) != 4 or parts[0] != "data" or parts[1] != "patterns" or parts[3] != "system.md":
            continue
        slug = parts[2].lower()
        if not SLUG_RE.fullmatch(slug) or (wanted and not any(tag in slug for tag in wanted)):
            continue
        patterns.append((slug, path))

    if not patterns:
        print("Aucun pattern correspondant trouvé.")
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    installed = skipped = failed = 0
    for slug, source_path in sorted(patterns):
        target = destination / f"fabric-{slug}.md"
        if target.exists() and not args.force:
            skipped += 1
            continue
        try:
            content = request(f"{RAW}/{args.branch}/{source_path}")
            if len(content) > MAX_FILE_BYTES:
                print(f"Ignoré (trop volumineux) : {slug}")
                skipped += 1
                continue
            text = content.decode("utf-8").strip()
            if not text:
                skipped += 1
                continue
            rendered = (
                f"# Fabric · {slug}\n\n"
                f"> Source : {source_path} · Dépôt officiel Fabric (licence MIT).\n"
                "> Instructions importées comme skill. Vérifier le contenu avant utilisation.\n\n"
                f"{text}\n"
            )
            if args.dry_run:
                print(f"[prévisualisation] {target}")
            else:
                target.write_text(rendered, encoding="utf-8")
                installed += 1
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, OSError) as exc:
            failed += 1
            print(f"Échec {slug}: {exc}", file=sys.stderr)

    print(f"Patterns détectés : {len(patterns)} | importés : {installed} | ignorés : {skipped} | erreurs : {failed}")
    if not args.dry_run:
        print(f"Skills installés dans : {destination}")
        print("Dans ZeroCode : /skills puis /skill fabric-<nom> (ou --skill fabric-<nom>).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
