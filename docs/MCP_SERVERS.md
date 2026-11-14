# Connecteurs MCP pour ZeroCode

ZeroCode prend en charge les serveurs MCP locaux en transport **stdio**. Il découvre leurs outils, ressources et prompts au démarrage de la session et les expose automatiquement au modèle.

Un serveur MCP est un programme externe : connecte uniquement des serveurs dont tu connais la provenance et les permissions.

## Playwright : piloter un navigateur

Prérequis : Node.js 20+ et npm/npx disponibles dans le terminal.

Dans le fichier `zerocode.json` à la racine du projet :

```json
{
  "mcp_servers": {
    "browser": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest", "--headless"],
      "timeout": 120,
      "trusted": true
    }
  }
}
```

Relance ZeroCode dans ce dossier. Le serveur Playwright sera démarré automatiquement et ses fonctions de navigateur apparaîtront dans la liste d'outils.

Exemples de tâches :
- Ouvre le site local, parcours les pages et signale les erreurs.
- Remplis les champs de test, vérifie le rendu et capture les régressions.
- Vérifie un parcours de connexion avec un compte de test.
- Contrôle une interface sur plusieurs tailles d'écran.

Le mode headless évite d'ouvrir une fenêtre visible. Les interactions peuvent toutefois effectuer des actions réelles sur le site. N'utilise `trusted: true` que pour un serveur que tu as choisi et dont tu acceptes les effets : en mode Full-Stack, ses outils pourront être appelés sans confirmation individuelle. Ne donne pas au navigateur des identifiants de production ni l'accès à des comptes sensibles.

Documentation officielle : [Playwright MCP](https://github.com/microsoft/playwright-mcp).

## Accès fichiers avec périmètre limité

Tu peux ajouter un serveur de fichiers pour des opérations spécialisées sur un dossier précis :

```json
{
  "mcp_servers": {
    "project_files": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/chemin/absolu/vers/le/projet"
      ],
      "timeout": 60
    }
  }
}
```

Remplace le chemin par le dossier autorisé. Ne donne pas accès à la racine du système, au dossier personnel complet, aux clés SSH ou aux répertoires contenant des secrets.

Documentation officielle : [MCP Filesystem Server](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem).

## Politique d'approbation

| Configuration | Comportement |
| --- | --- |
| Pas de `trusted` | Les outils MCP ordinaires exigent une confirmation explicite. |
| `trusted: true` | Les outils sont utilisables en mode autonome, selon les permissions de la session. |
| `readOnlyHint: true` | L'outil est traité comme non modificateur et suit les permissions normales. |
| Ressource ou prompt MCP | Lecture via une autorisation normale ; aucune commande distante n'est déclenchée par leur simple découverte. |

Les annotations MCP sont des indications déclarées par le serveur, pas une preuve de sûreté. Un serveur malveillant peut mentir sur ses annotations. Le flag `trusted` est donc une décision de confiance explicite, pas un mécanisme de sandbox.

Même avec un serveur de confiance, les commandes système `sudo` conservent leur confirmation dédiée. La politique de sécurité de ZeroCode bloque également les actions catastrophiques reconnues.

## Diagnostic

- Lance `zerocode doctor` pour vérifier la toolchain locale.
- Vérifie que `npx` est accessible si le serveur ne démarre pas.
- Contrôle le nom du serveur et les arguments dans `zerocode.json`.
- Redémarre la session après toute modification de configuration.
- Si un serveur MCP est indisponible, ZeroCode signale l'erreur sans bloquer le reste des outils intégrés.

Les serveurs MCP sont des extensions facultatives. ZeroCode ne télécharge pas de navigateur ni de paquet npm dans son installation de base.
