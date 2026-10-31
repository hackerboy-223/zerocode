# zerocode

Agent de codage autonome pour le terminal, gratuit par défaut et compatible avec plusieurs fournisseurs de modèles.

Créé par **H@CKERBOY** · [GitHub](https://github.com/hackerboy-223) · [Portfolio](https://hackerboy-223.vercel.app)

zerocode inspecte un dépôt, lit et modifie des fichiers, lance des tests et exécute des commandes. Il ne se contente pas de générer du texte : chaque action est vérifiable, les écritures et les commandes demandent une autorisation par défaut, et les résultats proviennent réellement des outils.

## Points clés

- Démarre sans clé API grâce à Kilo Gateway en accès anonyme.
- Chaîne de repli automatique si un modèle est indisponible, limité ou saturé.
- GLM 5.3 Flash gratuit, plus GLM 4.7/4.5 Flash, Kimi/Kilo, Groq, Gemini, OpenRouter, etc.
- Outils intégrés : lecture, écriture, édition, liste, recherche regex, shell et plan de tâches.
- Sessions reprenables, compaction du contexte et estimation des jetons.
- Interface TUI Textual : sidebar projet/sessions, chat Markdown, streaming et approbations.
- Mode `/full-stack` : projet complet autonome avec raisonnement, contexte, étapes et timeouts maximaux.
- Palette de commandes, recherche de fichiers `@` et panneaux de tâches/outils.
- Aucun secret affiché ; clés stockées avec des permissions restrictives.

## Installation

Prérequis : **Python 3.10 ou plus récent** et Git. Pour une installation isolée, `pipx` est recommandé : il installe ZeroCode dans son propre environnement et expose la commande `zerocode` sans modifier les dépendances Python des autres projets.

### Linux et macOS

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
# Redémarre le terminal si nécessaire, puis :
pipx install git+https://github.com/hackerboy-223/zerocode.git
zerocode --version
zerocode doctor
```

### Windows · PowerShell

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
# Redémarre PowerShell si nécessaire, puis :
pip install git+https://github.com/hackerboy-223/zerocode.git
zerocode --version
zerocode doctor
```

### Installer depuis le code source

Cette méthode convient aux personnes qui souhaitent contribuer ou modifier ZeroCode :

```bash
git clone https://github.com/hackerboy-223/zerocode.git
cd zerocode
python -m venv .venv
```

Active l’environnement virtuel, puis installe le projet :

```bash
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell : .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
ruff check src tests
```

Si l’accès public au dépôt n’est pas encore activé, l’installation directe depuis GitHub ne fonctionnera pas pour les personnes qui n’ont pas l’autorisation d’y accéder.

## Démarrage rapide

Sans aucune clé :

```bash
zerocode "explique la structure de ce projet"
zerocode
zerocode tui
```

Sans prompt, `zerocode` ouvre l'interface TUI Textual. Elle affiche la sidebar du projet, les sessions, le chat Markdown, l'état du routeur et les confirmations d'outils. Tapez `/help` ou `Ctrl+K` pour les commandes.

Pour revenir à l'ancienne boucle REPL :

```bash
zerocode --classic
zerocode chat --classic
```

Exemples :

```bash
zerocode "corrige le test qui échoue" --yolo
zerocode -m glm-5.3-flash --show-thinking
zerocode -m auto
zerocode -c
```

`--yolo` autorise toutes les actions de la session. À utiliser uniquement dans un dépôt de confiance.

## Interface TUI

L'interface par défaut s'appuie sur [Textual](https://textual.textualize.io/). Elle est pensée pour garder le contexte visible sans bloquer le terminal.

- **Sidebar** : branche Git, arborescence du projet et sessions récentes avec leur premier message.
- **Chat** : réponses Markdown, blocs de code colorés, raisonnement et cartes d'outils repliables.
- **Modes agent** : `BUILD` pour modifier, `PLAN` pour inspecter sans toucher aux fichiers (`Shift+Tab`), `FULL-STACK` pour construire un projet complet en autonomie.
- **Panneaux** : barre `CHAT / TÂCHES / OUTILS` toujours visible, synchronisée avec `Tab`.
- **Statut** : modèle, fournisseur, route prévue, permissions, session et jetons, avec animation de réflexion et indicateur d'activité.
- **Approbations** : `write`, `edit` et `bash` ouvrent un panneau `Autoriser / Refuser` avec aperçu défilable.
- **Confort** : historique des demandes avec `↑`/`↓`, recherche floue et défilement qui ne vous arrache pas la lecture si vous êtes remonté.

| Raccourci | Action |
| --- | --- |
| `Ctrl+K` | Palette de commandes avec recherche floue |
| `@` | Recherche floue de fichiers du dépôt |
| `↑` / `↓` | Naviguer dans l'historique des demandes |
| `Shift+Tab` | Basculer entre les modes build et plan |
| `Tab` | Chat → tâches → outils |
| `F2` | Replier ou ouvrir le dernier résultat d'outil |
| `F6` | Focus prompt → fichiers → sessions → chat |
| `Ctrl+B` | Afficher ou masquer la sidebar |
| `F1` | Aide et commandes |
| `Ctrl+Q` | Quitter |

Le mode plan masque `write`, `edit` et `bash`, ajoute une consigne de lecture seule au prompt système et refuse toute tentative de mutation.

`/full-stack` active un preset autonome : raisonnement `max`, 500 étapes, 128k jetons de sortie (plafonnés par le modèle), timeout de commande d'une heure, compaction à 95 %, raisonnement affiché et permissions `allow`. L'agent est invité à planifier, scaffolder, implémenter, installer les dépendances locales, tester, corriger et livrer un projet complet sans demander confirmation à chaque étape. Un retour en `BUILD`, `PLAN` ou `/safe` restaure automatiquement les réglages et permissions précédents. Le répertoire de travail reste confiné et les secrets restent protégés.

Les réponses et le raisonnement sont diffusés en streaming via un worker, avec une animation de réflexion visible pendant l'attente, sans figer l'interface. Les confirmations de sécurité restent actives en mode `ask`.

## GLM 5.3 et offre gratuite

Il n'existe pas d'API gratuite permanente pour GLM 5.3 complet. Les routes gratuites ou d'essai dépendent des fournisseurs et peuvent changer.

| Modèle | Accès gratuit réel | Remarque |
| --- | --- | --- |
| GLM 5.3 complet | Essai ou crédit selon le fournisseur | Pas de gratuité permanente connue |
| GLM 5.3 Flash | NVIDIA Build, OpenCode Zen | `glm-5.3-flash-free` chez OpenCode Zen |
| GLM 4.7 Flash | Z.AI | Gratuit en permanence sur l'API publique |
| GLM 4.5 Flash | Z.AI | Gratuit en permanence sur l'API publique |
| Modèles `:free` | OpenRouter | Quota gratuit, conditions variables |
| Kilo Auto Free | Kilo Gateway | Sans clé, 200 requêtes/heure/IP |

L'endpoint NVIDIA de GLM 5.3 est annoncé en fin de vie le **27/10/2026**. Privilégiez GLM 5.3 Flash ou les modèles gratuits des autres fournisseurs pour un usage durable.

Détails et identifiants exacts : [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Configuration

```bash
zerocode setup
zerocode setup --show
zerocode setup --test
zerocode doctor --live
```

Les clés peuvent aussi être fournies par l'environnement (voir `.env.example`) :

```bash
export NVIDIA_API_KEY="..."
export ZAI_API_KEY="..."
export OPENROUTER_API_KEY="..."
```

Ou stockées dans `~/.config/zerocode/keys.json` avec les droits `600`. Ne commitez jamais ce fichier.

### Fichiers

| Élément | Chemin |
| --- | --- |
| Configuration globale | `~/.config/zerocode/config.json` |
| Clés | `~/.config/zerocode/keys.json` |
| Sessions | `~/.local/share/zerocode/sessions/` |
| Configuration projet | `zerocode.json` ou `.zerocode.json` |
| Instructions projet | `ZEROCODE.md`, `AGENTS.md` |

Les variables `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `ZEROCODE_CONFIG` et `ZEROCODE_KEYS_FILE` permettent de déplacer ces fichiers.

### Exemple de configuration projet

```json
{
  "model": "auto",
  "free_only": true,
  "fallback": true,
  "permissions": "ask",
  "max_steps": 40,
  "max_tokens": 8192,
  "providers": {
    "zai": { "base_url": "https://api.z.ai/api/coding/paas/v4" }
  }
}
```

Les overrides disponibles : `--model`, `--provider`, `--free-only/--no-free-only`, `--fallback/--no-fallback`, `--reasoning`, `--temperature`, `--max-tokens`, `--max-steps`, `--permissions`, `--allow-outside-cwd`.

## Commandes

| Commande | Rôle |
| --- | --- |
| `zerocode [prompt]` | Exécuter une demande ou ouvrir le TUI |
| `zerocode tui` | Ouvrir explicitement l'interface TUI |
| `zerocode --classic` | Ouvrir l'ancienne interface REPL |
| `zerocode doctor [--live]` | Diagnostic local et test réel du routeur |
| `zerocode models [--free] [--live]` | Catalogue des modèles |
| `zerocode providers` | État des fournisseurs et des clés |
| `zerocode sessions` | Lister, reprendre ou supprimer des sessions |
| `zerocode config` | Afficher ou initialiser la configuration |

Dans le chat : `/help`, `/build`, `/plan`, `/full-stack`, `/model`, `/provider`, `/permissions`, `/yolo`, `/safe`, `/reasoning`, `/think`, `/temp`, `/max-steps`, `/compact`, `/cost`, `/todos`, `/tools`, `/models`, `/free`, `/providers`, `/session`, `/new`, `/resume`, `/sessions`, `/cd`, `/init`, `/clear`, `/quit`.

## Outils et sécurité

- `read`, `list`, `grep` sont en lecture seule et ne demandent pas de confirmation.
- `write`, `edit` et `bash` demandent une confirmation par défaut, sauf en mode `/full-stack` qui active explicitement `allow`.
- Le mode `deny` bloque toutes les mutations ; `ask` est le mode recommandé.
- Les chemins hors du répertoire de travail sont refusés sauf avec `--allow-outside-cwd`.
- Les écritures dans `.git` et les clés privées sont bloquées.
- Les commandes ont un délai maximal et leur sortie est tronquée.
- zerocode ne commit, ne pousse et n'installe rien sans demande explicite.

Aucun agent ne remplace une revue humaine. Vérifiez les diffs et les commandes avant de les accepter, surtout en mode `--yolo`.

## Architecture

Le fonctionnement interne, le routage et les points d'extension sont décrits dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```text
CLI / TUI Textual
   |
   v
Agent <--> Router <--> Fournisseurs OpenAI-compatibles
   |
   +--> Outils (fichiers, recherche, shell, tâches)
   |
   +--> Sessions et compaction du contexte
```

## Développement

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

Les tests n'effectuent aucun appel réseau. Les fournisseurs sont simulés avec `httpx.MockTransport`.

## Limites

- Les offres gratuites, quotas et identifiants de modèles changent fréquemment.
- Les données envoyées à un fournisseur anonyme ou gratuit peuvent être journalisées.
- La qualité et le respect des appels d'outils varient selon le modèle.
- Le mode gratuit peut être plus lent ou temporairement saturé.
- La compaction du contexte est une estimation, pas un comptage exact de jetons.

## Auteur

**H@CKERBOY**

- GitHub : [github.com/hackerboy-223](https://github.com/hackerboy-223)
- Portfolio : [hackerboy-223.vercel.app](https://hackerboy-223.vercel.app)
- Dépôt : [github.com/hackerboy-223/zerocode](https://github.com/hackerboy-223/zerocode)

## Licence

MIT. Voir [LICENSE](LICENSE).
