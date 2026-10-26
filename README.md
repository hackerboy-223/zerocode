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
- Interface Rich lisible, streaming des réponses et du raisonnement.
- Aucun secret affiché ; clés stockées avec des permissions restrictives.

## Installation

Prérequis : Python 3.10 ou plus récent.

```bash
git clone git@github.com:hackerboy-223/zerocode.git
cd zerocode
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Pour disposer de la commande globalement, utilisez `pipx` si disponible :

```bash
pipx install .
```

Vérification :

```bash
zerocode --version
zerocode doctor
```

## Démarrage rapide

Sans aucune clé :

```bash
zerocode "explique la structure de ce projet"
zerocode
```

Le mode interactif affiche l'état du routeur, la session courante et la chaîne de modèles prévue. Tapez `/help` pour les commandes internes.

Exemples :

```bash
zerocode "corrige le test qui échoue" --yolo
zerocode -m glm-5.3-flash --show-thinking
zerocode -m auto
zerocode -c
```

`--yolo` autorise toutes les actions de la session. À utiliser uniquement dans un dépôt de confiance.

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
| `zerocode [prompt]` | Exécuter une demande ou ouvrir le chat |
| `zerocode doctor [--live]` | Diagnostic local et test réel du routeur |
| `zerocode models [--free] [--live]` | Catalogue des modèles |
| `zerocode providers` | État des fournisseurs et des clés |
| `zerocode sessions` | Lister, reprendre ou supprimer des sessions |
| `zerocode config` | Afficher ou initialiser la configuration |

Dans le chat : `/model`, `/provider`, `/permissions`, `/compact`, `/cost`, `/todos`, `/tools`, `/session`, `/new`, `/resume`, `/cd`, `/init`, `/clear`, `/quit`.

## Outils et sécurité

- `read`, `list`, `grep` sont en lecture seule et ne demandent pas de confirmation.
- `write`, `edit` et `bash` demandent une confirmation par défaut.
- Le mode `deny` bloque toutes les mutations ; `ask` est le mode recommandé.
- Les chemins hors du répertoire de travail sont refusés sauf avec `--allow-outside-cwd`.
- Les écritures dans `.git` et les clés privées sont bloquées.
- Les commandes ont un délai maximal et leur sortie est tronquée.
- zerocode ne commit, ne pousse et n'installe rien sans demande explicite.

Aucun agent ne remplace une revue humaine. Vérifiez les diffs et les commandes avant de les accepter, surtout en mode `--yolo`.

## Architecture

Le fonctionnement interne, le routage et les points d'extension sont décrits dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```text
CLI / UI
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
