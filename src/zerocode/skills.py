from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

from .config import config_dir
from .security import redact_secrets
from .tokens import truncate_text

DEFAULT_ACTIVE_SKILLS: tuple[str, ...] = ("ultra-dev", "cyber-sec", "sys-tech")


@dataclass(frozen=True)
class SkillSpec:
    name: str
    label: str
    category: str
    summary: str
    prompt: str
    builtin: bool = True


BUILTIN_SKILLS: dict[str, SkillSpec] = {
    "ultra-dev": SkillSpec(
        name="ultra-dev",
        label="Ultra-Dev · Ingénierie & Architecture Senior",
        category="dev",
        summary=(
            "Architecture propre, typage strict, refactoring chirurgical (`multi_edit`), "
            "cartographie AST (`symbols`) et tests automatisés."
        ),
        prompt=(
            "COMPETENCE ULTRA-DEV (Ingénierie Logicielle Senior):\n"
            "- Analyse la structure avec `symbols`, `grep` et `read` avant de modifier.\n"
            "- Privilégie `multi_edit` pour appliquer plusieurs modifications atomiques dans un même fichier.\n"
            "- Écris du code de qualité production : typage explicite, gestion propre des erreurs, "
            "aucune duplication inutile, invariants clairs et respect strict des conventions du dépôt.\n"
            "- Traite systématiquement les cas limites (entrées vides, timeouts, concurrence, encodage, permissions).\n"
            "- Après chaque changement, exécute les tests/linters pertinents et corrige immédiatement toute régression."
        ),
    ),
    "cyber-sec": SkillSpec(
        name="cyber-sec",
        label="Cyber-Sec · Expert Cybersécurité, Audit & DevSecOps",
        category="security",
        summary=(
            "Audit SAST (`security_audit`), OWASP Top 10, CWE, cryptographie, durcissement "
            "Linux/réseau/conteneurs, forensique et remédiation défensive."
        ),
        prompt=(
            "COMPETENCE EXPERT CYBERSECURITE & DEVSECOPS:\n"
            "- Agis en expert senior en cybersécurité (AppSec, DevSecOps, SecOps, système/réseau et forensique) "
            "pour assister les développeurs, administrateurs et techniciens sur leurs systèmes et dépôts.\n"
            "- Utilise l'outil `security_audit` pour scanner rapidement un dépôt à la recherche de failles "
            "de code, secrets exposés, configurations risquées ou dépendances non verrouillées.\n"
            "- Couvre méthodiquement l'OWASP Top 10 et le CWE Top 25 : injections (SQL, OS command, SSTI, LDAP, XXE), "
            "contrôle d'accès défaillant (IDOR, élévation de privilèges), SSRF, XSS, CSRF, désérialisation non sûre "
            "(`pickle`, `yaml.load`), traversée de chemin (Path Traversal) et faiblesses cryptographiques.\n"
            "- Exige des primitives cryptographiques modernes : Argon2id/bcrypt/scrypt pour les mots de passe, "
            "AES-GCM ou ChaCha20-Poly1305 pour le chiffrement, `secrets`/`os.urandom` pour l'aléatoire, "
            "` hmac.compare_digest` contre les timing attacks, et TLS 1.2+/1.3 avec vérification stricte des certificats.\n"
            "- Pour chaque vulnérabilité identifiée, indique : la gravité (Critique/Haute/Moyenne/Faible), "
            "l'emplacement exact (`fichier:ligne`), le mécanisme technique (CWE/OWASP) et le correctif concret."
        ),
    ),
    "sys-tech": SkillSpec(
        name="sys-tech",
        label="Sys-Tech · Technicien Système, Réseau & Infra",
        category="ops",
        summary=(
            "Diagnostic poste/serveur (`sys_diag`), systemd/logs, réseau/DNS/TLS/ports, "
            "stockage, permissions POSIX et conteneurs."
        ),
        prompt=(
            "COMPETENCE TECHNICIEN SYSTEME, RESEAU & INFRASTRUCTURE:\n"
            "- Utilise `sys_diag` pour obtenir instantanément l'état de santé de l'hôte, des outils, du réseau et de Git.\n"
            "- Procède avec une méthodologie de dépannage terrain rigoureuse : observation factuelle (symptôme, code retour, "
            "journaux `journalctl`/`dmesg`, métriques CPU/RAM/disque/inodes), isolation de la couche fautive "
            "(matériel, OS, permissions POSIX/ACL, réseau/DNS/TLS/pare-feu, service ou application), puis remédiation sûre.\n"
            "- Propose et exécute des commandes non destructives d'abord, vérifie l'état avant/après chaque intervention "
            "et préserve toujours la disponibilité et les sauvegardes."
        ),
    ),
    "review": SkillSpec(
        name="review",
        label="Review · Revue de Code & Fiabilité Production",
        category="dev",
        summary=(
            "Détection des bugs subtils, race conditions, fuites de ressources, "
            "régressions d'API et manque de tests."
        ),
        prompt=(
            "COMPETENCE REVUE DE CODE & FIABILITE:\n"
            "- Inspecte les diffs et fichiers avec un niveau d'exigence staff engineer.\n"
            "- Signale uniquement les problèmes réels par ordre de criticité : bugs fonctionnels, failles de sécurité, "
            "conditions de course (race conditions), fuites de descripteurs/mémoire, erreurs silencieuses et dette critique."
        ),
    ),
    "perf": SkillSpec(
        name="perf",
        label="Perf · Haute Performance & Optimisation",
        category="dev",
        summary=(
            "Analyse de complexité, élimination des requêtes N+1, cache, "
            "parallélisme I/O et réduction de l'empreinte mémoire."
        ),
        prompt=(
            "COMPETENCE HAUTE PERFORMANCE:\n"
            "- Identifie les goulots d'étranglement CPU, mémoire, disque et réseau.\n"
            "- Optimise la complexité algorithmique, élimine les lectures/requêtes redondantes (N+1), "
            "privilégie le streaming/générateurs pour les gros volumes et mesure l'impact réel."
        ),
    ),
    "sec-hardening": SkillSpec(
        name="sec-hardening",
        label="Sec-Hardening · Durcissement & Remédiation Active",
        category="security",
        summary=(
            "Remédiation directe des vulnérabilités, verrouillage des permissions, "
            "validation stricte des entrées et politique moindre privilège."
        ),
        prompt=(
            "COMPETENCE DURCISSEMENT & REMEDIATION SECURITE:\n"
            "- Remplace systématiquement les appels dangereux (`shell=True`, `eval`, `exec`, `pickle`, SQL concaténé, "
            "`verify=False`, permissions `0777`) par des équivalents sûrs et validés.\n"
            "- Applique le principe du moindre privilège sur les fichiers (`0600` pour secrets, `0755`/`0644` standard), "
            "les processus, les conteneurs (utilisateur non-root, capabilities minimales) et les entrées utilisateur."
        ),
    ),
}


def discover_custom_skills(cwd: Path | None = None) -> dict[str, SkillSpec]:
    """Découvre les skills personnalisés dans ~/.config/zerocode/skills/*.md et .zerocode/skills/*.md."""
    found: dict[str, SkillSpec] = {}
    roots: list[Path] = [config_dir() / "skills"]
    if cwd is not None:
        roots.append(cwd.resolve() / ".zerocode" / "skills")
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            if not path.is_file():
                continue
            try:
                if path.stat().st_size > 200_000:
                    continue
                raw = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if not raw:
                continue
            slug = path.stem.lower().strip()
            first_line = raw.splitlines()[0].lstrip("# ").strip() or slug
            cleaned = truncate_text(redact_secrets(raw), 4_000)
            found[slug] = SkillSpec(
                name=slug,
                label=f"{slug} · Skill personnalisé",
                category="custom",
                summary=first_line[:110],
                prompt=f"COMPETENCE PERSONNALISEE ({slug}):\n{cleaned}",
                builtin=False,
            )
    return found


def all_skills(cwd: Path | None = None) -> dict[str, SkillSpec]:
    catalog = dict(BUILTIN_SKILLS)
    catalog.update(discover_custom_skills(cwd))
    return catalog


def normalize_skill_names(
    names: list[str] | tuple[str, ...] | None,
    cwd: Path | None = None,
) -> list[str]:
    if names is None:
        return list(DEFAULT_ACTIVE_SKILLS)
    catalog = all_skills(cwd)
    resolved: list[str] = []
    for raw in names:
        for part in str(raw).split(","):
            token = part.strip().lower()
            if not token:
                continue
            if token in {"none", "off", "aucun", "0"}:
                return []
            if token in {"all", "tous", "*"}:
                for key in catalog:
                    if key not in resolved:
                        resolved.append(key)
                continue
            if token in catalog and token not in resolved:
                resolved.append(token)
    return resolved


def format_skills_prompt(
    active_skills: list[str] | tuple[str, ...] | None,
    cwd: Path | None = None,
) -> str:
    names = normalize_skill_names(active_skills, cwd)
    if not names:
        return ""
    catalog = all_skills(cwd)
    sections = [catalog[name].prompt for name in names if name in catalog]
    if not sections:
        return ""
    return "\n\n".join(sections)


FABRIC_API = "https://api.github.com/repos/danielmiessler/fabric"
FABRIC_RAW = "https://raw.githubusercontent.com/danielmiessler/fabric"
FABRIC_USER_AGENT = "ZeroCode-Fabric-Integration/1.0"
FABRIC_MAX_FILE_BYTES = 180_000


def _fabric_request(url: str, limit: int = FABRIC_MAX_FILE_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": FABRIC_USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"Ressource Fabric trop volumineuse: {url}")
    return payload


def sync_fabric_assets(*, force: bool = False, branch: str = "main") -> dict[str, int]:
    """Télécharge les Patterns et stratégies Fabric dans les données utilisateur ZeroCode."""
    root = config_dir().resolve()
    skills_root, strategies_root = root / "skills", root / "strategies"
    skills_root.mkdir(parents=True, exist_ok=True)
    strategies_root.mkdir(parents=True, exist_ok=True)
    tree = json.loads(_fabric_request(f"{FABRIC_API}/git/trees/{branch}?recursive=1", 20_000_000))
    if tree.get("truncated"):
        raise RuntimeError("Arborescence Fabric tronquée : synchronisation annulée.")
    paths = [x["path"] for x in tree.get("tree", []) if x.get("type") == "blob"]
    patterns = sorted(p for p in paths if re.fullmatch(r"data/patterns/[a-zA-Z0-9_-]+/system\\.md", p))
    strategies = sorted(p for p in paths if re.fullmatch(r"data/strategies/[a-zA-Z0-9_-]+\\.json", p))
    counts = {"patterns": 0, "strategies": 0, "skipped": 0, "failed": 0}
    for source in patterns:
        slug = source.split("/")[-2].lower()
        target = skills_root / f"fabric-{slug}.md"
        if target.exists() and not force:
            counts["skipped"] += 1
            continue
        try:
            content = _fabric_request(f"{FABRIC_RAW}/{branch}/{source}").decode("utf-8").strip()
            if not content:
                counts["skipped"] += 1
                continue
            target.write_text(f"# Fabric · {slug}\\n\\n> Source : https://github.com/danielmiessler/fabric/blob/{branch}/{source}\\n> Licence : MIT. Instructions importées comme données, jamais exécutées.\\n\\n{content}\\n", encoding="utf-8")
            counts["patterns"] += 1
        except (OSError, UnicodeDecodeError, urllib.error.URLError, TimeoutError, ValueError):
            counts["failed"] += 1
    for source in strategies:
        slug = source.rsplit("/", 1)[-1][:-5].lower()
        target = strategies_root / f"fabric-{slug}.json"
        if target.exists() and not force:
            counts["skipped"] += 1
            continue
        try:
            data = json.loads(_fabric_request(f"{FABRIC_RAW}/{branch}/{source}").decode("utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("prompt"), str):
                raise ValueError("Format de stratégie invalide")
            target.write_text(json.dumps({"name": slug, "description": str(data.get("description", "")), "prompt": data["prompt"], "source": f"https://github.com/danielmiessler/fabric/blob/{branch}/{source}", "license": "MIT"}, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
            counts["strategies"] += 1
        except (OSError, UnicodeDecodeError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            counts["failed"] += 1
    return counts


def list_fabric_strategies() -> list[dict[str, str]]:
    """Retourne les stratégies Fabric installées séparément des Skills."""
    root = config_dir() / "strategies"
    result: list[dict[str, str]] = []
    if not root.is_dir():
        return result
    for path in sorted(root.glob("fabric-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        result.append({"name": str(data.get("name", path.stem.removeprefix("fabric-"))), "description": str(data.get("description", "")), "prompt": str(data.get("prompt", "")), "source": str(data.get("source", ""))})
    return result
