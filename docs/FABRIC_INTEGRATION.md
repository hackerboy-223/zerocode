# Intégration Fabric dans ZeroCode

ZeroCode peut importer les Patterns du projet [Daniel Miessler/Fabric](https://github.com/danielmiessler/fabric) comme skills Markdown locaux.

## Pourquoi cette approche

- Les Patterns Fabric sont des instructions textuelles, pas des plugins exécutables.
- L'import se fait à la demande : aucun poids supplémentaire dans l'installation de base.
- Les fichiers sont installés dans le répertoire de skills personnalisé déjà reconnu par ZeroCode.
- Les patterns restent modifiables et peuvent être supprimés indépendamment du code de ZeroCode.
- Le dépôt source reste attribué et la licence MIT doit être conservée avec les fichiers redistribués.

## Importer les patterns

Depuis la racine du dépôt ZeroCode :

```bash
python scripts/sync_fabric_patterns.py --dry-run
python scripts/sync_fabric_patterns.py
```

L'import par défaut utilise la branche `main` et installe les fichiers dans `~/.config/zerocode/skills/`.
Les fichiers sont nommés `fabric-<pattern>.md`. Les skills existants ne sont pas écrasés, sauf avec `--force`.

Options :

```bash
python scripts/sync_fabric_patterns.py --category development
python scripts/sync_fabric_patterns.py --dest .zerocode/skills
python scripts/sync_fabric_patterns.py --branch main --force
```

Le filtre `--category` sélectionne les noms de patterns contenant le terme fourni ; il ne s'agit pas d'une taxonomie officielle complète.

## Utiliser dans ZeroCode

```text
/skills
/skill fabric-review_code
```

Le nom exact dépend du pattern importé. Le skill peut aussi être activé avec `--skill fabric-<nom>`.

## Stratégies de raisonnement

Fabric publie aussi des stratégies distinctes des Patterns : CoT, CoD, ToT, AoT, Least-to-Most, Self-Consistency, Self-Refine, Reflexion et Standard. Elles ne sont pas importées comme skills automatiquement : leur activation doit rester un choix explicite du modèle et de l'utilisateur.

## Sécurité et maintenance

- Le script ne télécharge que les fichiers `data/patterns/*/system.md`.
- Les contenus sont traités comme des instructions non fiables : ils ne sont jamais exécutés comme du code.
- Vérifier les instructions importées avant de les utiliser, particulièrement celles qui touchent au shell, aux données ou à la sécurité.
- Relancer le script après consultation des changements amont ; l'import ne s'auto-met pas à jour.
- Les appels réseau se font uniquement vers l'API et les fichiers bruts GitHub officiels.
- La synchronisation ne doit pas être lancée dans un environnement sans accès réseau.

Source amont : https://github.com/danielmiessler/fabric
