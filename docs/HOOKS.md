# Hooks de cycle de vie

Les hooks permettent d'ajouter des contrôles locaux autour de l'exécution des outils ZeroCode. Ils sont exécutés uniquement depuis la configuration globale de l'utilisateur, jamais depuis les fichiers de configuration d'un dépôt.

## Configuration

Ajoute les hooks dans `~/.config/zerocode/config.json` (ou sous le répertoire défini par `XDG_CONFIG_HOME`) :

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "command": "python3",
        "args": ["/home/utilisateur/.config/zerocode/hooks/policy.py"],
        "timeout": 5
      }
    ],
    "PostToolUse": [
      {
        "command": "python3",
        "args": ["/home/utilisateur/.config/zerocode/hooks/audit.py"],
        "timeout": 5
      }
    ]
  }
}
```

Les commandes sont lancées sous forme de tableau d'arguments, sans shell. Le programme reçoit un objet JSON sur stdin :

```json
{
  "event": "PreToolUse",
  "tool": "bash",
  "arguments": {"command": "npm test"},
  "result": null,
  "cwd": "/chemin/du/projet"
}
```

## Événements disponibles

| Événement | Moment | Effet |
| --- | --- | --- |
| `PreToolUse` | Après l'autorisation, juste avant l'outil | Peut autoriser ou bloquer l'exécution |
| `PostToolUse` | Après une exécution réussie | Peut journaliser ou signaler un problème |

Pour bloquer une action depuis `PreToolUse`, le script peut renvoyer un objet JSON :

```json
{"decision": "deny", "reason": "Cette commande n'est pas autorisée dans ce projet."}
```

Un code de sortie différent de zéro bloque également l'action. Une sortie vide ou une décision autre que `deny` laisse passer l'action.

Une erreur ou un timeout de `PreToolUse` bloque l'action par défaut (échec fermé). Une erreur de `PostToolUse` ajoute un avertissement au résultat sans annuler l'action déjà effectuée.

## Limites et sécurité

- Maximum 8 hooks par événement, 30 secondes par hook et 4 000 caractères de sortie.
- Les clés API des fournisseurs ZeroCode sont retirées de l'environnement transmis aux scripts.
- Les arguments sont fournis sur stdin ; la commande et ses arguments ne sont jamais interprétés par un shell.
- Le contenu transmis est filtré par le masquage des secrets de ZeroCode.
- Les hooks définis dans `zerocode.json` ou `.zerocode.json` sont ignorés. Cela empêche un dépôt cloné de lancer du code local au démarrage.
- Un hook est un programme local exécuté avec les droits de l'utilisateur. N'ajoute que des scripts que tu as écrits ou audités.

Les hooks complètent les permissions ZeroCode ; ils ne les remplacent pas. Les contrôles de sécurité intégrés, les confirmations sudo et les approbations des intégrations externes restent actifs.
