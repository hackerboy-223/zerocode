# Fournisseurs et modèles

ZeroCode utilise le protocole OpenAI-compatible lorsqu'un fournisseur expose `/chat/completions`, le streaming SSE et les appels d'outils. Les adaptateurs et le catalogue de modèles intégrés sont définis dans `src/zerocode/catalog.py`.

> **Important :** les identifiants de modèles, prix, quotas, disponibilités et conditions de confidentialité changent fréquemment. Le catalogue intégré est une sélection connue par ZeroCode, pas une garantie de disponibilité ni une promesse de gratuité permanente. Vérifie les offres au moment de l'utilisation.

## Démarrage sans clé API personnelle

Sur une installation neuve, ZeroCode utilise `model=auto` et `free_only=true`. La chaîne automatique utilise exclusivement les routes gratuites anonymes de **Kilo Gateway**. Elle n'active pas silencieusement un fournisseur nécessitant une clé personnelle et ne bascule pas vers un modèle payant.

Kilo documente le modèle virtuel `kilo-auto/free`, dont les modèles sous-jacents sont sélectionnés côté serveur et peuvent changer. Les limites anonymes et les fournisseurs amont sont définis par Kilo, pas par ZeroCode. Les modèles gratuits peuvent journaliser les prompts ou les utiliser pour améliorer leurs services : n'envoie pas de secrets, de données personnelles ou de code confidentiel.

- [Catalogue dynamique Kilo](https://kilo.ai/docs/gateway/models-and-providers)
- [API Kilo et endpoint /models](https://kilo.ai/docs/gateway/api-reference)

Pour commencer :

```bash
zerocode -m auto "explique ce projet"
zerocode doctor --live
zerocode models --provider kilo --live
```

## Fournisseurs pris en charge

Les fournisseurs ci-dessous sont déclarés dans le catalogue. La présence d'une entrée ne signifie pas que le fournisseur est activé ou qu'un modèle gratuit est accessible à ton compte.

| Fournisseur | Variable(s) de clé | Base URL par défaut |
| --- | --- | --- |
| Kilo Gateway | `KILO_API_KEY` (facultative pour les routes anonymes) | `https://ai-gateway.kilo.ai/api/v1` |
| NVIDIA Build | `NVIDIA_API_KEY` | `https://integrate.api.nvidia.com/v1` |
| OpenCode Zen | `OPENCODE_ZEN_API_KEY`, `OPENCODE_API_KEY` | `https://opencode.ai/zen/v1` |
| Z.AI | `ZAI_API_KEY`, `ZHIPU_API_KEY`, `Z_AI_API_KEY` | `https://api.z.ai/api/paas/v4` |
| OpenRouter | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| Groq | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` |
| Google AI Studio | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| Mistral AI | `MISTRAL_API_KEY` | `https://api.mistral.ai/v1` |
| SambaNova Cloud | `SAMBANOVA_API_KEY` | `https://api.sambanova.ai/v1` |
| Together AI | `TOGETHER_API_KEY` | `https://api.together.xyz/v1` |
| Ollama | aucune | `http://localhost:11434/v1` |

Les clés peuvent être définies dans l'environnement ou enregistrées avec `zerocode setup`. Ne colle jamais une clé dans un dépôt ou dans une conversation. Le stockage local des clés et les variables d'environnement sont prioritaires sur les valeurs par défaut du catalogue.

## Consulter les modèles réellement détectés

Affiche les modèles de la sélection locale :

```bash
zerocode models
zerocode models --free
zerocode models --provider kilo
zerocode providers
```

Interroge les catalogues en direct (les fournisseurs live actuellement interrogés par cette commande sont Kilo, OpenRouter et OpenCode Zen) :

```bash
zerocode models --provider kilo --live
zerocode models --provider openrouter --live
zerocode models --provider opencode-zen --live
```

Une liste live confirme qu'un identifiant est annoncé par l'endpoint interrogé ; elle ne garantit pas que le modèle accepte tous les paramètres, les outils ou les images, ni que ton compte dispose du quota nécessaire. Pour les fournisseurs qui n'exposent pas de découverte compatible, vérifie leur documentation et lance `zerocode doctor --live`.

## Comprendre les niveaux

- `free` : le catalogue ZeroCode considère le modèle comme gratuit au moment où l'entrée a été ajoutée ; revérifie toujours la fiche du fournisseur.
- `trial` : essai, crédit promotionnel ou quota limité. Il peut expirer ou demander une carte.
- `paid` : modèle facturé selon le tarif du fournisseur.
- `local` : modèle exécuté sur ta machine, par exemple avec Ollama.

Avec `free_only=true` (valeur par défaut), ZeroCode filtre le catalogue local sur les niveaux gratuits, d'essai et locaux. Ce filtre ne peut pas savoir qu'une promotion vient de se terminer : la vérification live et la page de tarification du fournisseur restent nécessaires. ZeroCode n'active pas un modèle payant à la place d'une route gratuite en cas d'échec.

## OpenRouter et OpenCode

Les catalogues de modèles gratuits de ces services évoluent souvent. Les variantes gratuites peuvent être plafonnées, limitées à un compte donné ou soumises aux conditions du fournisseur amont. Consulte leurs pages officielles avant d'utiliser un modèle avec des données sensibles :

- [OpenRouter — modèles gratuits et limites](https://openrouter.ai/collections/free-models/)
- [OpenRouter — documentation API](https://openrouter.ai/docs)
- [OpenCode — modèles et tarifs](https://opencode.ai/docs/console/models/)
- [OpenCode — politique de confidentialité](https://opencode.ai/docs/console/privacy/)

Ne déduis pas qu'un modèle est gratuit uniquement parce que son nom contient `free` : il faut vérifier le tarif, la route et les conditions actuelles du fournisseur.

## Utiliser un modèle local avec Ollama

Ollama est désactivé par défaut. Installe Ollama, télécharge un modèle compatible puis active-le via l'environnement :

```bash
ollama pull qwen2.5-coder:7b
export OLLAMA_BASE_URL=http://localhost:11434/v1
zerocode doctor
```

Ou dans la configuration globale `~/.config/zerocode/config.json` :

```json
{
  "providers": {
    "ollama": {
      "enabled": true,
      "base_url": "http://localhost:11434/v1"
    }
  }
}
```

Un modèle local n'exige pas de clé API distante, mais il utilise les ressources de ta machine. Vérifie la mémoire disponible et la compatibilité du modèle avec les appels d'outils si tu veux l'utiliser comme agent de code.

## Chaînes de repli

Les chaînes d'alias sont définies dans `src/zerocode/catalog.py` :

- `auto` : routes gratuites anonymes de Kilo uniquement.
- `glm-5.3` : chaîne GLM 5.3 configurée par ZeroCode, sous réserve de l'offre active chez chaque fournisseur.
- `glm-5.3-flash` : chaîne GLM Flash et route gratuite Kilo de secours.

Le routeur écarte les fournisseurs qui n'ont pas de clé, les modèles payants lorsque `free_only` est actif et les modèles qui ne déclarent pas les capacités nécessaires. En cas de limite ou d'indisponibilité, il applique un cooldown puis essaie la suite de la chaîne. Si aucune route compatible n'est disponible, il signale l'échec sans activer un fournisseur payant en douce.

## Ajouter ou corriger un fournisseur

1. Vérifie la documentation officielle, la base URL, les conditions de facturation et de traitement des données.
2. Ajoute ou mets à jour le `ProviderSpec` et les `ModelSpec` dans `catalog.py`.
3. Marque un modèle `free` uniquement avec une source officielle actuelle ; utilise `trial` lorsque la gratuité est temporaire ou conditionnelle.
4. Ajoute des tests de catalogue et de routage.
5. Vérifie l'identifiant avec `zerocode models --live` lorsqu'une découverte est disponible.

La compatibilité OpenAI d'un endpoint ne garantit pas la compatibilité des appels d'outils, du streaming ou de la vision : ces capacités doivent être vérifiées séparément.
