from __future__ import annotations

from .types import ModelSpec, ProviderSpec

KILO_FREE = (
    ModelSpec(
        "kilo-auto/free",
        "Auto Free (Kilo)",
        context=256_000,
        max_output=32_000,
        tier="free",
        tools=True,
        notes="Routage gratuit sans cle, 200 requetes/h/IP. Donnees potentiellement journalisees.",
    ),
    ModelSpec(
        "cohere/north-mini-code:free",
        "North Mini Code",
        context=256_000,
        max_output=32_000,
        tier="free",
        notes="Modele de code gratuit via Kilo.",
    ),
    ModelSpec(
        "poolside/laguna-s-2.1:free",
        "Laguna S 2.1",
        context=262_144,
        max_output=32_000,
        tier="free",
        notes="Modele de code gratuit via Kilo.",
    ),
    ModelSpec(
        "nvidia/nemotron-3.5-lightning:free",
        "Nemotron 3.5 Lightning",
        context=1_000_000,
        max_output=32_000,
        tier="free",
        notes="Endpoint NVIDIA gratuit via Kilo, usage d'essai.",
    ),
    ModelSpec(
        "openrouter/free",
        "OpenRouter Free",
        context=200_000,
        max_output=32_000,
        tier="free",
        notes="Routage automatique vers un modele gratuit OpenRouter.",
    ),
)

OPENCODE_FREE = (
    ModelSpec(
        "glm-5.3-flash-free",
        "GLM 5.3 Flash Free",
        context=1_000_000,
        max_output=128_000,
        tier="free",
        tools=True,
        reasoning=True,
        notes="Zero retention, pas d'entrainement. Quota gratuit via OpenCode Zen.",
    ),
    ModelSpec(
        "big-pickle",
        "Big Pickle",
        context=200_000,
        max_output=32_000,
        tier="free",
        notes="Modele furtif gratuit; donnees utilisables pour ameliorer le modele.",
    ),
    ModelSpec(
        "deepseek-v4.1-flash-free",
        "DeepSeek V4.1 Flash Free",
        context=200_000,
        max_output=32_000,
        tier="free",
        notes="Zero retention, pas d'entrainement.",
    ),
    ModelSpec(
        "mimo-v2.6-flash-free",
        "MiMo V2.6 Flash Free",
        context=200_000,
        max_output=32_000,
        tier="free",
        notes="Donnees utilisables pendant la periode gratuite.",
    ),
    ModelSpec(
        "nemotron-3.5-lightning-free",
        "Nemotron 3.5 Lightning Free",
        context=1_000_000,
        max_output=32_000,
        tier="free",
        notes="Usage d'essai; eviter les donnees personnelles.",
    ),
    ModelSpec(
        "nemotron-3.5-super-vl-free",
        "Nemotron 3.5 Super VL Free",
        context=1_000_000,
        max_output=32_000,
        tier="free",
        notes="Usage d'essai; eviter les donnees personnelles.",
    ),
    ModelSpec(
        "beam-free",
        "Beam Free",
        context=1_000_000,
        max_output=32_000,
        tier="free",
        notes="Donnees conservees 30 jours pour securite.",
    ),
    ModelSpec(
        "flint-40b-free",
        "Flint 40B Free",
        context=262_144,
        max_output=32_000,
        tier="free",
        notes="Donnees utilisables pendant la periode gratuite.",
    ),
    ModelSpec(
        "jev-1.13-free",
        "Jev 1.13 Free",
        context=200_000,
        max_output=32_000,
        tier="free",
        notes="Gratuit pour une duree limitee.",
    ),
    ModelSpec(
        "glm-5.3",
        "GLM 5.3",
        context=1_000_000,
        max_output=128_000,
        tier="paid",
        tools=True,
        reasoning=True,
        notes="Payant via OpenCode Zen.",
    ),
)

PROVIDERS: dict[str, ProviderSpec] = {
    "kilo": ProviderSpec(
        name="kilo",
        label="Kilo Gateway",
        base_url="https://ai-gateway.kilo.ai/api/v1",
        api_key_envs=("KILO_API_KEY",),
        signup_url="https://kilo.ai",
        docs_url="https://kilo.ai/docs/gateway",
        keyless=True,
        models=(
            *KILO_FREE,
            ModelSpec(
                "z-ai/glm-5.3",
                "GLM 5.3",
                context=1_000_000,
                max_output=128_000,
                tier="paid",
                tools=True,
                reasoning=True,
                notes="Payant via Kilo.",
            ),
            ModelSpec(
                "z-ai/glm-5.3-flash",
                "GLM 5.3 Flash",
                context=1_000_000,
                max_output=128_000,
                tier="paid",
                tools=True,
                reasoning=True,
                notes="Tres bon marche via Kilo, non gratuit.",
            ),
            ModelSpec(
                "z-ai/glm-5.3-prime",
                "GLM 5.3 Prime",
                context=1_000_000,
                max_output=128_000,
                tier="paid",
                tools=True,
                reasoning=True,
                notes="Payant via Kilo.",
            ),
        ),
        headers=(("X-KiloCode-Version", "zerocode/0.1.0"),),
        notes="Acces anonyme aux modeles gratuits, 200 requetes/heure par IP.",
    ),
    "nvidia": ProviderSpec(
        name="nvidia",
        label="NVIDIA Build",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_envs=("NVIDIA_API_KEY",),
        signup_url="https://build.nvidia.com/settings/api-keys",
        docs_url="https://build.nvidia.com/z-ai/glm-5-3",
        models=(
            ModelSpec(
                "z-ai/glm-5.3",
                "GLM 5.3",
                context=1_000_000,
                max_output=128_000,
                tier="trial",
                tools=True,
                reasoning=True,
                notes="Essai gratuit. L'endpoint est annonce en fin de vie le 27/10/2026.",
            ),
            ModelSpec(
                "z-ai/glm-5.3-flash",
                "GLM 5.3 Flash",
                context=1_000_000,
                max_output=128_000,
                tier="trial",
                tools=True,
                reasoning=True,
                notes="Essai gratuit NVIDIA, multilingue et multimodal.",
            ),
        ),
        notes="Cles gratuites sans carte bancaire pour prototyper.",
    ),
    "opencode-zen": ProviderSpec(
        name="opencode-zen",
        label="OpenCode Zen",
        base_url="https://opencode.ai/zen/v1",
        api_key_envs=("OPENCODE_ZEN_API_KEY", "OPENCODE_API_KEY"),
        signup_url="https://opencode.ai/auth",
        docs_url="https://opencode.ai/docs/zen/",
        models=OPENCODE_FREE,
        notes="Les modeles gratuits peuvent demander un compte OpenCode et sont soumis a quota.",
    ),
    "zai": ProviderSpec(
        name="zai",
        label="Z.AI (Zhipu)",
        base_url="https://api.z.ai/api/paas/v4",
        api_key_envs=("ZAI_API_KEY", "ZHIPU_API_KEY", "Z_AI_API_KEY"),
        signup_url="https://z.ai",
        docs_url="https://docs.z.ai/guides/llm/glm-5.3",
        models=(
            ModelSpec(
                "glm-5.3",
                "GLM 5.3",
                context=1_000_000,
                max_output=128_000,
                tier="paid",
                tools=True,
                reasoning=True,
                notes="Payant a l'usage ou via GLM Coding Plan.",
            ),
            ModelSpec(
                "glm-4.7-flash",
                "GLM 4.7 Flash",
                context=200_000,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="Gratuit en permanence sur l'API Z.AI.",
            ),
            ModelSpec(
                "glm-4.5-flash",
                "GLM 4.5 Flash",
                context=131_072,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="Gratuit en permanence sur l'API Z.AI.",
            ),
        ),
        notes=(
            "GLM 5.3 n'est pas gratuit en API publique. GLM 4.7/4.5 Flash le sont. "
            "Pour un plan Coding, remplace base_url par https://api.z.ai/api/coding/paas/v4."
        ),
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_envs=("OPENROUTER_API_KEY",),
        signup_url="https://openrouter.ai/keys",
        docs_url="https://openrouter.ai/collections/free-models",
        models=(
            ModelSpec(
                "openrouter/free",
                "OpenRouter Free Router",
                context=200_000,
                max_output=32_000,
                tier="free",
                notes="Choisit automatiquement un modele gratuit compatible.",
            ),
            ModelSpec(
                "cohere/north-mini-code:free",
                "North Mini Code",
                context=256_000,
                max_output=32_000,
                tier="free",
            ),
            ModelSpec(
                "nvidia/nemotron-3.5-lightning:free",
                "Nemotron 3.5 Lightning",
                context=1_000_000,
                max_output=32_000,
                tier="free",
                notes="Usage d'essai.",
            ),
            ModelSpec(
                "poolside/laguna-s-2.1:free",
                "Laguna S 2.1",
                context=262_144,
                max_output=32_000,
                tier="free",
            ),
            ModelSpec(
                "dots-studio/dots-3-note-preview:free",
                "Dots 3 Note Preview",
                context=512_000,
                max_output=32_000,
                tier="free",
            ),
            ModelSpec(
                "z-ai/glm-5.3",
                "GLM 5.3",
                context=1_000_000,
                max_output=128_000,
                tier="paid",
                tools=True,
                reasoning=True,
                notes="Payant via OpenRouter.",
            ),
        ),
        headers=(
            ("HTTP-Referer", "https://github.com/zerocode/zerocode"),
            ("X-Title", "zerocode"),
        ),
        notes="Modeles :free limites a 50 requetes/jour (1000/jour apres 10 $ achetes).",
    ),
    "groq": ProviderSpec(
        name="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_envs=("GROQ_API_KEY",),
        signup_url="https://console.groq.com/keys",
        docs_url="https://console.groq.com/docs/rate-limits",
        models=(
            ModelSpec(
                "openai/gpt-oss-120b",
                "GPT OSS 120B",
                context=131_072,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="Tres rapide. 30 req/min, 1000 req/jour.",
            ),
            ModelSpec(
                "openai/gpt-oss-20b",
                "GPT OSS 20B",
                context=131_072,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="30 req/min, 1000 req/jour.",
            ),
            ModelSpec(
                "qwen/qwen3.8-27b",
                "Qwen 3.8 27B",
                context=262_144,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="30 req/min, 1000 req/jour.",
            ),
        ),
        notes="Offre gratuite sans carte bancaire.",
    ),
    "gemini": ProviderSpec(
        name="gemini",
        label="Google AI Studio",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_envs=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        signup_url="https://aistudio.google.com/apikey",
        docs_url="https://ai.google.dev/gemini-api/docs/openai",
        models=(
            ModelSpec(
                "gemini-2.5-flash",
                "Gemini 2.5 Flash",
                context=1_000_000,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="Offre gratuite; les donnees peuvent servir a ameliorer Google.",
            ),
            ModelSpec(
                "gemini-2.5-flash-lite",
                "Gemini 2.5 Flash Lite",
                context=1_000_000,
                max_output=32_000,
                tier="free",
                tools=True,
                notes="Offre gratuite.",
            ),
            ModelSpec(
                "gemini-3.5-flash",
                "Gemini 3.5 Flash",
                context=1_000_000,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="Offre gratuite; quotas variables.",
            ),
            ModelSpec(
                "gemini-3.1-flash-lite",
                "Gemini 3.1 Flash Lite",
                context=1_000_000,
                max_output=32_000,
                tier="free",
                tools=True,
                notes="Offre gratuite.",
            ),
        ),
        notes="Palier gratuit genereux, sans carte bancaire.",
    ),
    "mistral": ProviderSpec(
        name="mistral",
        label="Mistral AI",
        base_url="https://api.mistral.ai/v1",
        api_key_envs=("MISTRAL_API_KEY",),
        signup_url="https://console.mistral.ai/api-keys",
        docs_url="https://docs.mistral.ai",
        models=(
            ModelSpec(
                "devstral-medium-latest",
                "Devstral Medium",
                context=128_000,
                max_output=32_000,
                tier="trial",
                tools=True,
                notes="10 $ de credit gratuit par mois (plan gratuit).",
            ),
            ModelSpec(
                "mistral-large-latest",
                "Mistral Large",
                context=128_000,
                max_output=32_000,
                tier="trial",
                tools=True,
                notes="10 $ de credit gratuit par mois.",
            ),
            ModelSpec(
                "codestral-latest",
                "Codestral",
                context=256_000,
                max_output=32_000,
                tier="trial",
                tools=False,
                notes="Optimise code; sans appels d'outils fiables.",
            ),
        ),
        notes="Credit mensuel gratuit; verification par telephone possible.",
    ),
    "sambanova": ProviderSpec(
        name="sambanova",
        label="SambaNova Cloud",
        base_url="https://api.sambanova.ai/v1",
        api_key_envs=("SAMBANOVA_API_KEY",),
        signup_url="https://cloud.sambanova.ai/apis",
        docs_url="https://docs.sambanova.ai/cloud/docs/get-started/rate-limits",
        models=(
            ModelSpec(
                "DeepSeek-V3.1",
                "DeepSeek V3.1",
                context=131_072,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="20 req/min, 20 req/jour, 200k tokens/jour.",
            ),
            ModelSpec(
                "gpt-oss-120b",
                "GPT OSS 120B",
                context=131_072,
                max_output=32_000,
                tier="free",
                tools=True,
                reasoning=True,
                notes="20 req/min, 20 req/jour.",
            ),
        ),
        notes="Palier gratuit sans carte bancaire.",
    ),
    "together": ProviderSpec(
        name="together",
        label="Together AI",
        base_url="https://api.together.xyz/v1",
        api_key_envs=("TOGETHER_API_KEY",),
        signup_url="https://api.together.ai/settings/api-keys",
        docs_url="https://docs.together.ai",
        models=(
            ModelSpec(
                "zai-org/GLM-5.3-FP8",
                "GLM 5.3 FP8",
                context=1_000_000,
                max_output=128_000,
                tier="trial",
                tools=True,
                reasoning=True,
                notes="Endpoint annonce en usage equitable; verifier le quota du compte.",
            ),
            ModelSpec(
                "zai-org/GLM-5.3-FP8-Lora",
                "GLM 5.3 FP8 LoRA",
                context=1_000_000,
                max_output=128_000,
                tier="trial",
                tools=True,
                reasoning=True,
                notes="Variante LoRA; usage equitable.",
            ),
        ),
        notes="L'acces gratuit depend du compte et de la charge; une carte peut etre demandee.",
    ),
    "ollama": ProviderSpec(
        name="ollama",
        label="Ollama local",
        base_url="http://localhost:11434/v1",
        models=(
            ModelSpec(
                "qwen2.5-coder:7b",
                "Qwen 2.5 Coder 7B",
                context=32_768,
                max_output=8_192,
                tier="local",
                tools=True,
                notes="Local et illimite. `ollama pull qwen2.5-coder:7b`.",
            ),
            ModelSpec(
                "qwen2.5-coder:14b",
                "Qwen 2.5 Coder 14B",
                context=32_768,
                max_output=8_192,
                tier="local",
                tools=True,
                notes="Local; necessite ~10 Go de RAM.",
            ),
            ModelSpec(
                "llama3.1:8b",
                "Llama 3.1 8B",
                context=131_072,
                max_output=8_192,
                tier="local",
                tools=True,
                notes="Local; `ollama pull llama3.1:8b`.",
            ),
            ModelSpec(
                "deepseek-coder-v2:16b",
                "DeepSeek Coder V2 16B",
                context=131_072,
                max_output=8_192,
                tier="local",
                tools=False,
                notes="Local; sans appels d'outils fiables.",
            ),
        ),
        keyless=True,
        enabled_by_default=False,
        notes="Desactive par defaut. Active-le dans config.json ou avec OLLAMA_BASE_URL.",
    ),
}

GLM53_CHAIN: tuple[tuple[str, str], ...] = (
    ("nvidia", "z-ai/glm-5.3"),
    ("together", "zai-org/GLM-5.3-FP8"),
    ("zai", "glm-5.3"),
    ("openrouter", "z-ai/glm-5.3"),
    ("kilo", "z-ai/glm-5.3"),
)

GLM53_FLASH_CHAIN: tuple[tuple[str, str], ...] = (
    ("nvidia", "z-ai/glm-5.3-flash"),
    ("opencode-zen", "glm-5.3-flash-free"),
    ("kilo", "kilo-auto/free"),
)

AUTO_CHAIN: tuple[tuple[str, str], ...] = (
    ("kilo", "kilo-auto/free"),
    ("nvidia", "z-ai/glm-5.3-flash"),
    ("opencode-zen", "glm-5.3-flash-free"),
    ("zai", "glm-4.7-flash"),
    ("openrouter", "openrouter/free"),
    ("groq", "openai/gpt-oss-120b"),
    ("gemini", "gemini-2.5-flash"),
    ("mistral", "devstral-medium-latest"),
    ("sambanova", "DeepSeek-V3.1"),
    ("together", "zai-org/GLM-5.3-FP8"),
    ("ollama", "qwen2.5-coder:7b"),
)


def get_provider(name: str) -> ProviderSpec | None:
    return PROVIDERS.get(name)


def all_choices() -> list[tuple[ProviderSpec, ModelSpec]]:
    return [
        (provider, model)
        for provider in PROVIDERS.values()
        for model in provider.models
    ]


def find_model(query: str) -> list[tuple[ProviderSpec, ModelSpec]]:
    needle = query.strip().lower()
    if not needle:
        return []
    result = []
    for provider, model in all_choices():
        haystack = f"{provider.name} {model.id} {model.label}".lower()
        if needle in haystack:
            result.append((provider, model))
    return result


def model_chain(model: str) -> tuple[tuple[str, str], ...]:
    key = model.strip().lower()
    if key in {"auto", "free", "gratuit"}:
        return AUTO_CHAIN
    if key in {"glm-5.3", "glm5.3", "glm-5.3-full"}:
        return GLM53_CHAIN + GLM53_FLASH_CHAIN + AUTO_CHAIN
    if key in {"glm-5.3-flash", "glm-5.3-flash-free", "glm-flash"}:
        return GLM53_FLASH_CHAIN + AUTO_CHAIN
    return ()


def resolve_choice(provider_name: str, model_id: str) -> tuple[ProviderSpec, ModelSpec] | None:
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        return None
    model = provider.model(model_id)
    if model is None:
        return None
    return provider, model
