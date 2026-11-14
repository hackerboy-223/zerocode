# Intégration native de Fabric dans ZeroCode

ZeroCode importe les ressources du dépôt officiel [Daniel Miessler/Fabric](https://github.com/danielmiessler/fabric) directement dans son répertoire de données utilisateur.

## Installation en une commande

Après mise à jour de ZeroCode :

```bash
zerocode skills --sync-fabric
```

Cette commande télécharge :
- Tous les Patterns sous `data/patterns/*/system.md` et les rend immédiatement détectables comme Skills personnalisés.
- Toutes les stratégies JSON sous `data/strategies/*.json` dans un dossier distinct.

Les fichiers sont enregistrés dans `~/.config/zerocode/skills/` et `~/.config/zerocode/strategies/`. Aucun paquet Fabric ni clé API supplémentaire n'est nécessaire.

## Commandes

```bash
zerocode skills --sync-fabric          # importer les nouvelles ressources
zerocode skills --sync-fabric --force  # actualiser aussi les ressources existantes
zerocode skills                       # voir les Skills importés
zerocode strategies                   # voir les stratégies installées
zerocode strategies --show cot        # afficher le prompt d'une stratégie
```

Les fichiers existants ne sont pas écrasés sans `--force`, afin de préserver les modifications locales. Les Patterns sont des instructions Markdown et ne sont jamais exécutés comme du code. Les stratégies restent stockées séparément des Skills.

## Source et licence

Les ressources proviennent de [danielmiessler/fabric](https://github.com/danielmiessler/fabric), distribué sous licence MIT. Chaque Pattern importé conserve son chemin source et la mention de licence. Voir la [licence officielle Fabric](https://github.com/danielmiessler/fabric/blob/main/LICENSE).

La synchronisation est volontaire, nécessite une connexion Internet et peut être relancée après une mise à jour du dépôt amont.
