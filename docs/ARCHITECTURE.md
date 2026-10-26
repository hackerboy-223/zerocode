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
| `tools/` | outils et gestion des permissions |

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

- `never` : lecture seule, exécution directe.
- `ask` : confirmation utilisateur selon le mode.
- Le mode global vaut `ask`, `allow` ou `deny`.

Les arguments sont validés par `_validate_arguments` avant l'exécution. Le contexte d'outil résout les chemins et bloque les sorties du répertoire de travail, `.git` et les clés privées. Les erreurs d'outil sont renvoyées au modèle sous forme de texte, ce qui lui permet de corriger son approche.

Dans le TUI, `TuiBridge.confirm_tool` bloque uniquement le worker et affiche un `ConfirmScreen`. La décision utilisateur est renvoyée via un `threading.Event`.

Les modes agent sont gérés par `Agent.set_mode` :

- `build` : tous les outils sont proposés au modèle.
- `plan` : `ToolRegistry.read_only` masque les outils dont l'approbation n'est pas `never` et refuse leur exécution ; le prompt système reçoit une consigne de lecture seule.

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
