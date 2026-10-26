# Fournisseurs et modèles

État vérifié le **26 octobre 2026**. Les offres gratuites, quotas et identifiants changent souvent : utilisez `zerocode doctor --live` et `zerocode models --live` avant de vous appuyer sur une offre.

## Principe

zerocode parle le protocole OpenAI (`/chat/completions`, streaming SSE, appels d'outils). Chaque fournisseur est décrit dans `src/zerocode/catalog.py`.

- `tier="free"` : gratuit ou local.
- `tier="trial"` : essai, crédit ou quota limité.
- `tier="paid"` : payant.
- `free_only=true` par défaut : seuls les modèles `free`, `trial` et `local` sont retenus.
- Kilo Gateway est utilisable sans clé et sert de point de départ.

## Tableau des fournisseurs

| Fournisseur | Clé | Offre gratuite | Base URL |
| --- | --- | --- | --- |
| Kilo Gateway | facultative | `kilo-auto/free`, 200 req/h/IP en anonyme | `https://ai-gateway.kilo.ai/api/v1` |
| NVIDIA Build | `NVIDIA_API_KEY` | GLM 5.3 / 5.3 Flash en essai | `https://integrate.api.nvidia.com/v1` |
| OpenCode Zen | `OPENCODE_ZEN_API_KEY` | `glm-5.3-flash-free` et autres `-free` | `https://opencode.ai/zen/v1` |
| Z.AI | `ZAI_API_KEY` | GLM 4.7 Flash, GLM 4.5 Flash | `https://api.z.ai/api/paas/v4` |
| OpenRouter | `OPENROUTER_API_KEY` | modèles `:free` | `https://openrouter.ai/api/v1` |
| Groq | `GROQ_API_KEY` | GPT OSS, Qwen, quotas journaliers | `https://api.groq.com/openai/v1` |
| Google AI Studio | `GEMINI_API_KEY` | Gemini Flash, palier gratuit | `https://generativelanguage.googleapis.com/v1beta/openai` |
| Mistral | `MISTRAL_API_KEY` | crédit mensuel | `https://api.mistral.ai/v1` |
| SambaNova | `SAMBANOVA_API_KEY` | DeepSeek, GPT OSS, quota journalier | `https://api.sambanova.ai/v1` |
| Together AI | `TOGETHER_API_KEY` | GLM 5.3 en essai selon le compte | `https://api.together.xyz/v1` |
| Ollama | aucune | local et illimité | `http://localhost:11434/v1` |

## Détails utiles

### Kilo Gateway

- Accès anonyme : aucune clé nécessaire pour les modèles gratuits.
- `kilo-auto/free` route automatiquement vers un modèle gratuit disponible.
- `KILO_API_KEY` augmente les quotas.
- Les données peuvent être journalisées. Évitez les secrets et les données personnelles.

### NVIDIA Build

- Clé gratuite sans carte bancaire pour prototyper.
- GLM 5.3 complet : endpoint annoncé en fin de vie le **27/10/2026**.
- GLM 5.3 Flash : `z-ai/glm-5.3-flash`.
- Les quotas et la disponibilité peuvent varier.

### OpenCode Zen

- `glm-5.3-flash-free` est le modèle GLM Flash gratuit.
- L'accès sans clé peut renvoyer `429 FreeUsageLimitError`.
- Créez une clé sur `https://opencode.ai/auth` pour utiliser les modèles gratuits.
- Les autres modèles `-free` sont listés dans le catalogue et peuvent changer.

### Z.AI

- GLM 5.3 est payant en API publique.
- GLM 4.7 Flash (`glm-4.7-flash`) et GLM 4.5 Flash (`glm-4.5-flash`) sont gratuits.
- Pour un plan Coding, la base URL est `https://api.z.ai/api/coding/paas/v4`.

### OpenRouter

- Les modèles gratuits se terminent souvent par `:free`.
- Le quota est d'environ 50 requêtes/jour, porté à 1000/jour après un achat de 10 $.
- `openrouter/free` choisit automatiquement un modèle gratuit.

### Groq, Gemini, SambaNova

- Offres gratuites avec quotas par minute et par jour.
- Excellents pour les tests et les petites tâches.
- Les identifiants de modèles évoluent : vérifiez `zerocode models --live`.

### Ollama

Désactivé par défaut. Pour l'activer :

```bash
ollama pull qwen2.5-coder:7b
export OLLAMA_BASE_URL=http://localhost:11434/v1
```

Ou dans la configuration :

```json
{
  "providers": {
    "ollama": { "enabled": true, "base_url": "http://localhost:11434/v1" }
  }
}
```

## Chaînes de repli

Elles sont définies dans `catalog.py` :

- `AUTO_CHAIN` : Kilo, NVIDIA Flash, OpenCode Zen, Z.AI Flash, OpenRouter, Groq, Gemini, Mistral, SambaNova, Together, Ollama.
- `GLM53_FLASH_CHAIN` : NVIDIA Flash, OpenCode Zen, Kilo.
- `GLM53_CHAIN` : NVIDIA, Together, Z.AI, OpenRouter, Kilo (GLM 5.3 complet).

Le routeur ignore les fournisseurs sans clé, les modèles payants quand `free_only` est actif, et les modèles incompatibles avec les outils quand l'agent en a besoin. En cas d'échec, il applique un cooldown et passe au candidat suivant.

## Vérification

```bash
zerocode providers
zerocode doctor
zerocode doctor --live
zerocode models --free
zerocode models --live
zerocode -m auto "réponds uniquement OK"
```

## Ajouter un fournisseur

1. Ajouter un `ProviderSpec` et ses `ModelSpec` dans `catalog.py`.
2. Ajouter une entrée dans `AUTO_CHAIN` si le fournisseur doit être utilisé en repli.
3. Documenter la variable de clé et la provenance des modèles.
4. Ajouter un test si la logique de routage est particulière.

Aucun code spécifique n'est nécessaire si l'API respecte le protocole OpenAI.
