# ZeroCode Desktop

Application native locale basée sur Tauri 2, React et TypeScript. Elle réutilise le moteur Python ZeroCode installé sur la machine et ouvre un vrai shell local via un pseudo-terminal (PTY).

## Prérequis

- Node.js 20.19+ ou 22.12+
- Rust stable et Cargo
- Dépendances système Tauri 2 pour Linux
- ZeroCode installé et accessible dans PATH

## Développement

Depuis ce dossier :

    npm install
    npm run tauri dev

## Compilation

    npm run tauri build

Les paquets Linux DEB et AppImage sont configurés pour la machine de développement. Pour produire un installateur Windows NSIS, lance la compilation depuis Windows avec la cible NSIS.

## Architecture

- src/ : interface React, animations, mascotte LUPUS et terminal xterm.js.
- src-tauri/ : hôte natif Rust, PTY local et lancement du moteur ZeroCode.
- Le shell est lancé par Rust dans le dossier sélectionné.
- L'agent est démarré comme processus local zerocode --json ; aucune commande n'est exécutée sur un serveur distant.

## Sécurité actuelle

Le mode prudent est sélectionné par défaut. Le CLI utilise un protocole JSON bidirectionnel : chaque opération qui nécessite une autorisation déclenche une demande dans l'interface, et l'agent attend la réponse avant de continuer. Le mode autonome doit être activé explicitement dans l'interface ; il lance alors le moteur avec --permissions allow, autorisant les modifications et commandes avec les droits du compte utilisateur.

N'active le mode autonome que dans un dépôt de confiance. Le terminal est un shell complet et n'est pas une sandbox. Le processus de commande et l'accès aux fichiers sont locaux ; le fournisseur de modèle peut toutefois être distant. Pour conserver aussi l'inférence sur la machine, configure un fournisseur local comme Ollama. Une prochaine étape doit ajouter un protocole d'approbation JSON bidirectionnel pour afficher chaque demande sensible avant de l'autoriser.