"""20 gerçek YZ sağlayıcısının kayıt defteri.

DÜRÜSTLÜK KURALI (v9 hattının `ten_agent_debate.py` ilkesinden devralınır):
Buradaki isimler GERÇEK sağlayıcı ve GERÇEK API uçlarıdır. Ancak:

  * Anahtar yoksa `configured=False` olur ve sağlayıcı ÇAĞRILMAZ.
  * Anahtarsız modda üretilen çıktı YZ cevabı DEĞİLDİR; kural tabanlı
    kantitatif denetimdir ve çıktıda açıkça `RULE_BASED_QUANT` etiketlenir.
  * Model kimlikleri zamanla değişir; `model` alanı .env/config ile
    geçilebilir. Buradaki değerler makul varsayılanlardır, doğrulanmış
    "en iyi model" iddiası değildir.

"En iyi 20" sıralaması nesnel değildir; aşağıdaki sıra sağlayıcı adının
alfabetik/grup mantığıdır, üstünlük iddiası taşımaz. `tier` yalnızca
konseydeki rolü belirler (hakem / denetçi / hızlı ön eleme).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    provider_id: str
    label: str
    protocol: str          # openai | anthropic | gemini | cohere
    base_url: str
    default_model: str
    env_key: str
    role: str              # arbiter | auditor | screener
    tier: int              # 1=hakem, 2=denetçi, 3=hızlı eleme
    supports_json: bool = True
    notes: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)

    def api_key(self) -> str:
        return (os.environ.get(self.env_key) or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key())

    def model(self) -> str:
        override = (os.environ.get(f"{self.env_key}_MODEL") or "").strip()
        return override or self.default_model

    def public_info(self) -> dict[str, Any]:
        """Anahtar İÇERMEYEN görünüm — panele/rapora güvenle yazılır."""
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "protocol": self.protocol,
            "model": self.model(),
            "role": self.role,
            "tier": self.tier,
            "configured": self.configured,
            "env_key": self.env_key,
            "base_url": self.base_url,
            "notes": self.notes,
        }


_OPENAI = "openai"
_ANTHROPIC = "anthropic"
_GEMINI = "gemini"
_COHERE = "cohere"

#: 20 gerçek sağlayıcı. OpenAI-uyumlu uçlar tek adapter ile çalışır.
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec("openai", "OpenAI", _OPENAI,
                 "https://api.openai.com/v1", "gpt-4o",
                 "OPENAI_API_KEY", "arbiter", 1,
                 notes="Genel amaçlı hakem; JSON mode destekli."),
    ProviderSpec("anthropic", "Anthropic Claude", _ANTHROPIC,
                 "https://api.anthropic.com/v1", "claude-sonnet-4-5",
                 "ANTHROPIC_API_KEY", "arbiter", 1,
                 notes="Uzun bağlam, muhakeme ağırlıklı hakem."),
    ProviderSpec("google", "Google Gemini", _GEMINI,
                 "https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-pro",
                 "GEMINI_API_KEY", "arbiter", 1,
                 notes="Çok modlu; responseSchema ile katı JSON."),
    ProviderSpec("xai", "xAI Grok", _OPENAI,
                 "https://api.x.ai/v1", "grok-4",
                 "XAI_API_KEY", "auditor", 2,
                 notes="OpenAI uyumlu uç."),
    ProviderSpec("deepseek", "DeepSeek", _OPENAI,
                 "https://api.deepseek.com/v1", "deepseek-chat",
                 "DEEPSEEK_API_KEY", "auditor", 2,
                 notes="Düşük maliyetli muhakeme; v9 hattının varsayılan hakem modeliydi."),
    ProviderSpec("mistral", "Mistral AI", _OPENAI,
                 "https://api.mistral.ai/v1", "mistral-large-latest",
                 "MISTRAL_API_KEY", "auditor", 2),
    ProviderSpec("groq", "Groq", _OPENAI,
                 "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile",
                 "GROQ_API_KEY", "screener", 3,
                 notes="Çok düşük gecikme; hızlı ön eleme için ideal."),
    ProviderSpec("together", "Together AI", _OPENAI,
                 "https://api.together.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                 "TOGETHER_API_KEY", "auditor", 2),
    ProviderSpec("fireworks", "Fireworks AI", _OPENAI,
                 "https://api.fireworks.ai/inference/v1", "accounts/fireworks/models/llama-v3p3-70b-instruct",
                 "FIREWORKS_API_KEY", "screener", 3),
    ProviderSpec("perplexity", "Perplexity", _OPENAI,
                 "https://api.perplexity.ai", "sonar-pro",
                 "PERPLEXITY_API_KEY", "auditor", 2,
                 notes="Web bağlantılı; haber/olgu doğrulamada güçlü."),
    ProviderSpec("cohere", "Cohere", _COHERE,
                 "https://api.cohere.com/v2", "command-r-plus",
                 "COHERE_API_KEY", "auditor", 2),
    ProviderSpec("openrouter", "OpenRouter (çoklu model)", _OPENAI,
                 "https://openrouter.ai/api/v1", "deepseek/deepseek-chat",
                 "OPENROUTER_API_KEY", "auditor", 2,
                 notes="Tek anahtarla çok sağlayıcı. Anahtar varsa diğerlerinin çoğu buna yönlendirilebilir.",
                 extra_headers={"HTTP-Referer": "https://localhost", "X-Title": "AI OmniStudio"}),
    ProviderSpec("cerebras", "Cerebras", _OPENAI,
                 "https://api.cerebras.ai/v1", "llama-3.3-70b",
                 "CEREBRAS_API_KEY", "screener", 3,
                 notes="Yüksek token/sn; hızlı eleme."),
    ProviderSpec("sambanova", "SambaNova", _OPENAI,
                 "https://api.sambanova.ai/v1", "Meta-Llama-3.3-70B-Instruct",
                 "SAMBANOVA_API_KEY", "screener", 3),
    ProviderSpec("hyperbolic", "Hyperbolic", _OPENAI,
                 "https://api.hyperbolic.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct",
                 "HYPERBOLIC_API_KEY", "auditor", 2),
    ProviderSpec("deepinfra", "DeepInfra", _OPENAI,
                 "https://api.deepinfra.com/v1/openai", "meta-llama/Llama-3.3-70B-Instruct",
                 "DEEPINFRA_API_KEY", "auditor", 2),
    ProviderSpec("novita", "Novita AI", _OPENAI,
                 "https://api.novita.ai/v3/openai", "meta-llama/llama-3.3-70b-instruct",
                 "NOVITA_API_KEY", "auditor", 2),
    ProviderSpec("qwen", "Alibaba Qwen (DashScope)", _OPENAI,
                 "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-plus",
                 "DASHSCOPE_API_KEY", "auditor", 2),
    ProviderSpec("moonshot", "Moonshot Kimi", _OPENAI,
                 "https://api.moonshot.ai/v1", "kimi-latest",
                 "MOONSHOT_API_KEY", "auditor", 2),
    ProviderSpec("zhipu", "Zhipu GLM", _OPENAI,
                 "https://open.bigmodel.cn/api/paas/v4", "glm-4-plus",
                 "ZHIPU_API_KEY", "auditor", 2),
)

BY_ID: dict[str, ProviderSpec] = {p.provider_id: p for p in PROVIDERS}

assert len(PROVIDERS) == 20, f"20 sağlayıcı bekleniyordu, {len(PROVIDERS)} bulundu"
assert len(BY_ID) == 20, "provider_id çakışması"


def configured_providers() -> list[ProviderSpec]:
    return [p for p in PROVIDERS if p.configured]


def registry_status() -> dict[str, Any]:
    conf = configured_providers()
    return {
        "total": len(PROVIDERS),
        "configured": len(conf),
        "unconfigured": len(PROVIDERS) - len(conf),
        "mode": "LIVE_LLM" if conf else "RULE_BASED_QUANT",
        "honesty_note": (
            "Anahtarsız sağlayıcılar çağrılmaz. Konsey çıktısı kural tabanlı "
            "kantitatif denetimdir; YZ cevabı olarak sunulmaz."
        ),
        "providers": [p.public_info() for p in PROVIDERS],
    }