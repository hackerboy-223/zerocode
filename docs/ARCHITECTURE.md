# Architecture

## Vue d'ensemble

```text
main() / CLI
   |
   +-- Config, sessions, catalogue
   |
   +-- TUI Textual (défaut) ou ConsoleUI (--classic)
   |     |
   |     +-- TuiBridge <--> workers asyncio / thread
   |
   +-- Agent
   |     |
   |     +-- Router ---> OpenAICompatibleClient ---> fournisseurs
   |     |
   |     +-- ToolRegistry ---> outils fichiers / recherche / shell / tâches
   |     |
   |     +-- compaction du contexte
   |
   +-- SessionStore
```

Le cœur de l'agent reste synchrone : une requête, un flux, un tour d'agent. Le TUI exécute ce tour dans un worker Textual et utilise `TuiBridge` pour renvoyer le streaming, les outils et les confirmations vers la boucle d'événements. L'interface ne bloque donc pas pendant les appels réseau. Les cartes d'outils sont des `Collapsible` : le résultat court reste visible, les sorties longues se replient et peuvent être ouvertes au clavier.

## Modules

| Module | Responsabilité |
| --- | --- |
| `cli.py` | argparse, commandes, choix TUI/REPL, slash-commands classiques |
| `tui/` | application Textual, bridge, palette, fichiers, confirmations, commandes, cartes d'outils et historique de saisie |
| `ui.py` | rendu Rich de l'interface classique, streaming et confirmations |
| `agent.py` | boucle agent, appels d'outils, sauvegarde, compaction |
| `router.py` | sélection des candidats, fallback, cooldown |
| `providers.py` | résolution des clés, HTTP/SSE, erreurs, découverte |
| `catalog.py` | fournisseurs, modèles, tiers, chaînes de repli |
| `config.py` | configuration JSON, environnement, clés, chemins XDG |
| `session.py` | sérialisation des sessions et historique |
| `tokens.py` | estimation, troncature, compaction |
| `prompts.py` | prompt système et instructions projet |
| `security.py` | masquage DLP des secrets (`redact_secrets`) et pare-feu contre les commandes shell destructrices (`check_dangerous_command`) |
| `checkpoints.py` | sauvegarde atomique avant écriture/édition et restauration sécurisée (`/undo`) |
| `mcp.py` | client JSON-RPC stdio pour outils, ressources et prompts MCP, avec environnement assaini et approbation des actions distantes |
| `tools/` | outils de fichiers, recherche, Git, shell, web, cartographie et vérification multi-stack, tâches, sous-agents spécialisés et permissions |

## Déroulement d'un tour

1. `cli.run_agent` charge la configuration, la session et construit le routeur et les outils.
2. Le TUI installe `TuiBridge` sur l'agent, le registre et le routeur, puis démarre `Agent.run_turn` dans un worker.
3. `Agent.run_turn` ajoute le message utilisateur et sauvegarde la session.
4. Si le contexte approche de la limite, `compact_messages` résume les anciens messages et conserve les plus récents.
5. `Router.resolve_candidates` construit la liste ordonnée des couples fournisseur/modèle admissibles.
6. Le premier client essaie en streaming. En cas d'erreur récupérable, le routeur met le candidat en cooldown et passe au suivant.
7. Si le modèle demande des outils, chaque appel est validé, autorisé, exécuté, puis renvoyé comme message `tool`.
8. La boucle recommence jusqu'à une réponse sans outil ou jusqu'à `max_steps`.
9. La session et l'usage sont sauvegardés à la fin du tour.

## Routage

`Router.resolve_candidates` applique les règles suivantes :

1. Un préfixe `fournisseur:modèle` force le fournisseur.
2. Les alias (`auto`, `glm-5.3`, `glm-5.3-flash`) sont développés en chaînes.
3. Un identifiant exact est cherché dans tous les fournisseurs, puis par correspondance partielle.
4. `provider` force un fournisseur et, si le modèle demandé est payant, bascule vers son premier modèle gratuit.
5. `AUTO_CHAIN` est ajoutée quand le fallback est actif.
6. Le routeur filtre les fournisseurs indisponibles, les modèles payants si `free_only` est actif, et les modèles sans outils quand l'agent en a besoin.

Les erreurs `AuthError`, `RateLimitError` et les erreurs récupérables imposent un cooldown différent. `AllProvidersFailed` contient la liste des échecs.

## Permissions et outils

Chaque outil possède un niveau `approval` :

- `never` : lecture seule ou sans effet de bord sur le dépôt (`read`, `list`, `grep`, `fetch`, `web_search`, `todo_write`), exécution directe.
- `auto` : autorisé automatiquement en mode `ask` si l'opération est sûre (création de nouveau fichier via `write`, modification d'un fichier existant non secret via `edit`, ou commande de test/lint/diagnostic reconnue par `is_safe_auto_command`).
- `ask` : confirmation utilisateur selon le mode.
- Le mode global vaut `ask`, `allow` ou `deny`.

Les arguments sont validés par `_validate_arguments` avant l'exécution. Les commandes `bash` passent par `check_dangerous_command` et s'exécutent dans un environnement nettoyé des clés API (`_clean_environment`). Les écritures et éditions déclenchent un checkpoint (`/undo`) ainsi qu'un diagnostic syntaxique immédiat (`_syntax_diagnostic` sur Python et JSON). Toutes les sorties d'outils sont filtrées par `redact_secrets` avant d'être renvoyées au modèle.

Dans le TUI, `TuiBridge.confirm_tool` bloque uniquement le worker et affiche un `ConfirmScreen`. La décision utilisateur est renvoyée via un `threading.Event`.

Les modes agent sont gérés par `Agent.set_mode` :

- `build` : tous les outils sont proposés au modèle.
- `plan` : `ToolRegistry.read_only` masque les outils dont l'approbation n'est pas `never` et refuse leur exécution ; le prompt système reçoit une consigne de lecture seule.
- `full-stack` : preset autonome (`FULL_STACK_PRESET`) avec raisonnement max, 128k jetons de sortie, 500 étapes, timeout 3600 s, compaction à 0.95, permissions `allow`, raisonnement affiché et auto-continuation tant qu'il reste des tâches non terminées dans `todos`. Le prompt système impose de cartographier le dépôt (`project_map`), planifier, déléguer les analyses aux sous-agents spécialisés en lecture seule, puis vérifier tests/lint/types/build via `project_verify`. L'agent peut effectuer jusqu'à six reprises automatiques de continuation lorsqu'il reste des tâches. Les intégrations MCP nécessitent toujours une confirmation dédiée. Les réglages précédents sont sauvegardés en mémoire et restaurés dès que l'on quitte le mode.

## Capacités d'autonomie

Le mode Full-Stack s'appuie sur des outils dédiés plutôt que sur une suite de commandes shell improvisées :
- `project_map` dresse un inventaire borné du dépôt, identifie les manifestes, les piles et les points d'entrée, sans suivre les liens symboliques ni lire les secrets.
- `git_status` et `git_diff` exposent les modifications suivies ; les chemins sensibles sont exclus du diff.
- `project_verify` détecte les scripts et commandes de validation pour JavaScript/TypeScript, PHP, Python, Go, Rust, JVM, Ruby, .NET, Dart/Flutter, Swift et Elixir.
- `subagent` délègue des analyses isolées à sept profils en lecture seule : explorer, architect, reviewer, security, performance, tester et researcher. L'agent principal reste seul responsable des modifications.
- MCP peut fournir des outils, des ressources et des prompts. Les actions distantes exigent une confirmation, sauf serveur explicitement marqué `trusted: true` dans la configuration globale détenue par l'utilisateur. Les annotations `readOnlyHint` restent des indications fournies par le serveur.

Les serveurs Playwright et Filesystem sont optionnels et documentés dans [MCP_SERVERS.md](MCP_SERVERS.md). Ils ne sont pas téléchargés avec ZeroCode.

## Contexte et compaction

L'estimation utilise environ un jeton pour 3,5 caractères. La compaction :

- conserve le message système ;
- résume les messages anciens dans le message système ;
- conserve les derniers messages ;
- supprime les messages `tool` orphelins ;
- tronque les contenus trop longs ;
- réduit progressivement le contexte jusqu'à la cible.

Ce mécanisme est une approximation. Il ne remplace pas un comptage exact par modèle.

## Sessions et configuration

- Les sessions sont des fichiers JSON atomiques dans `~/.local/share/zerocode/sessions/`.
- Les clés sont stockées dans `~/.config/zerocode/keys.json` avec les droits `600`.
- La configuration globale est fusionnée avec la configuration projet, puis les variables d'environnement, puis les options CLI.
- Les valeurs sont validées avant utilisation.

## Tests

```bash
pytest
ruff check src tests
```

Les tests couvrent la configuration, le catalogue, le routage, les fournisseurs simulés, les outils, l'agent, les sessions, la compaction et le TUI headless (`run_test`). Aucun test ne contacte le réseau.

## Points d'extension

- Nouveau fournisseur : ajouter un `ProviderSpec` dans `catalog.py`.
- Nouvel outil : créer un `Tool` et l'enregistrer dans `tools/__init__.py`.
- Nouvelle commande : ajouter un sous-parser dans `cli.py`, une branche dans `_slash_command`, puis une entrée dans `tui/commands.py`.
- Nouveau panneau TUI : ajouter un widget Textual dans `tui/app.py` et un mode dans `action_cycle_mode`.
- Nouvelle politique de permissions : étendre `PermissionManager`.
- Nouveau format de session : versionner `Session.to_dict` et adapter `from_dict`.
