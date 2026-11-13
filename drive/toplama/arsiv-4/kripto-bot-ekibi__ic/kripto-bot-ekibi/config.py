"""Yapılandırma: .env yüklemesi, sabitler ve model kataloğu."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ---- Telegram ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
}

# ---- Veritabanı ----
DB_PATH = BASE_DIR / "bot_data.db"

# ---- Zamanlanmış tarama ----
SCAN_INTERVAL_MIN = int(os.getenv("SCAN_INTERVAL_MIN", "15"))      # dakika
STRONG_ALERT_SCORE = int(os.getenv("STRONG_ALERT_SCORE", "45"))    # |skor| eşiği
ALERT_COOLDOWN_H = int(os.getenv("ALERT_COOLDOWN_H", "2"))         # aynı yönde tekrar alarm (saat)

# ---- Piyasa verisi ----
BYBIT_BASE = "https://api.bybit.com"
OKX_BASE = "https://www.okx.com"
HTTP_TIMEOUT = 15

SCAN_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv(
        "SCAN_SYMBOLS",
        "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,SUIUSDT",
    ).split(",")
    if s.strip()
]

# ---- EVREN LLM (SAYZEK) ----
EVREN_API_KEY = os.getenv("EVREN_API_KEY", "").strip()
EVREN_BASE_URL = os.getenv(
    "EVREN_BASE_URL", "https://evren-llmapi.ssyz.org.tr/v1"
).strip().rstrip("/")

# ---- AI sistem promptu (Türkçe) ----
SYSTEM_PROMPT = (
    "Sen 'KriptoBot'sun: kripto para ve vadeli (futures) işlem konularında yardımcı, "
    "samimi ve net konuşan bir Türkçe yapay zekâ asistanı. Kuralların: "
    "1) Her zaman Türkçe yanıt ver. 2) Yanıtları kısa ve öz tut (en fazla 200 kelime), "
    "gerektiğinde madde işaretleri kullan. 3) Teknik terimleri (long, short, kaldıraç, "
    "funding oranı, likidasyon, RSI vb.) ilk kullanımda kısaca açıkla. 4) Asıl uzmanlık "
    "alanın kripto piyasaları, teknik analiz ve risk yönetimidir; konu dışı sorularda da "
    "yardımcı ol ama uzman olmadığın konularda bunu dürüstçe söyle. 5) ASLA kesin yatırım "
    "tavsiyesi verme; önemli analizlerde 'yatırım tavsiyesi değildir, kendi araştırmanı yap' "
    "notunu ekle. 6) Vadeli işlemlerin yüksek risk taşıdığını, kaldıraçlı işlemlerde "
    "likidasyon riski olduğunu vurgula. 7) Uydurma fiyat/veri verme; güncel fiyat gerekirse "
    "kullanıcıya /fiyat veya /sinyal komutlarını öner."
)

DISCLAIMER = (
    "⚠️ <i>Bu sinyal otomatik teknik analize dayanır, <b>yatırım tavsiyesi değildir</b>. "
    "Vadeli işlemler kaldıraç nedeniyle yüksek risk taşır. Kendi araştırmanı yap, "
    "risk yönetimine uy.</i>"
)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ---- Çoklu-model kataloğu ----
# saglayici: glm | pollinations | ollama | openai_uyumlu | anthropic | gemini
MODEL_CATALOG = {
    "glm": {
        "etiket": "GLM (gömülü) • anahtarsız ✅",
        "saglayici": "glm",
    },
    # ---- EVREN LLM (SAYZEK) — tek anahtarla çok model ----
    "evren-glm": {
        "etiket": "EVREN GLM-5.3 • 512K bağlam",
        "saglayici": "openai_uyumlu",
        "base": EVREN_BASE_URL,
        "model": "glm-5.3",
        "anahtar": EVREN_API_KEY,
    },
    "evren-deepseek": {
        "etiket": "EVREN DeepSeek-V4.1 • 1M bağlam, görüş",
        "saglayici": "openai_uyumlu",
        "base": EVREN_BASE_URL,
        "model": "deepseek-v4.1-flash",
        "anahtar": EVREN_API_KEY,
    },
    "evren-qwen": {
        "etiket": "EVREN Qwen3.8-Flash • hızlı sohbet",
        "saglayici": "openai_uyumlu",
        "base": EVREN_BASE_URL,
        "model": "qwen3.8-flash-next",
        "anahtar": EVREN_API_KEY,
    },
    "evren-gemma": {
        "etiket": "EVREN Gemma-4-31B • görüntü destekli",
        "saglayici": "openai_uyumlu",
        "base": EVREN_BASE_URL,
        "model": "gemma-4-31b",
        "anahtar": EVREN_API_KEY,
    },
    "evren-auto": {
        "etiket": "EVREN Auto • otomatik model yönlendirme",
        "saglayici": "openai_uyumlu",
        "base": EVREN_BASE_URL,
        "model": "auto",
        "anahtar": EVREN_API_KEY,
    },
    "pollinations": {
        "etiket": "Pollinations • ücretsiz, anahtarsız ✅",
        "saglayici": "pollinations",
        "model": "openai",
    },
    "ollama": {
        "etiket": "Ollama yerel • anahtarsız ✅ (senin makinen)",
        "saglayici": "ollama",
        "model": _env("OLLAMA_MODEL", "llama3.2"),
    },
    "ozel": {
        "etiket": "Özel endpoint • senin API adresin",
        "saglayici": "openai_uyumlu",
        "base": _env("CUSTOM_BASE_URL"),
        "model": _env("CUSTOM_MODEL"),
        "anahtar": _env("CUSTOM_API_KEY"),
    },
    "gpt-4o": {
        "etiket": "OpenAI GPT-4o",
        "saglayici": "openai_uyumlu",
        "base": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "anahtar": _env("OPENAI_API_KEY"),
    },
    "gpt-4o-mini": {
        "etiket": "OpenAI GPT-4o-mini",
        "saglayici": "openai_uyumlu",
        "base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "anahtar": _env("OPENAI_API_KEY"),
    },
    "claude-sonnet": {
        "etiket": "Anthropic Claude Sonnet",
        "saglayici": "anthropic",
        "model": _env("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        "anahtar": _env("ANTHROPIC_API_KEY"),
    },
    "gemini-flash": {
        "etiket": "Google Gemini Flash",
        "saglayici": "gemini",
        "model": _env("GEMINI_MODEL", "gemini-2.0-flash"),
        "anahtar": _env("GEMINI_API_KEY"),
    },
    "deepseek": {
        "etiket": "DeepSeek Chat (resmî)",
        "saglayici": "openai_uyumlu",
        "base": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "anahtar": _env("DEEPSEEK_API_KEY"),
    },
    "qwen": {
        "etiket": "Qwen (DashScope)",
        "saglayici": "openai_uyumlu",
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "anahtar": _env("DASHSCOPE_API_KEY"),
    },
    "mistral": {
        "etiket": "Mistral Large",
        "saglayici": "openai_uyumlu",
        "base": "https://api.mistral.ai/v1",
        "model": "mistral-large-latest",
        "anahtar": _env("MISTRAL_API_KEY"),
    },
    "groq-llama": {
        "etiket": "Llama 3.3 70B (Groq • ücretsiz katman)",
        "saglayici": "openai_uyumlu",
        "base": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "anahtar": _env("GROQ_API_KEY"),
    },
    "openrouter": {
        "etiket": "OpenRouter • tek anahtarla 100+ model",
        "saglayici": "openai_uyumlu",
        "base": "https://openrouter.ai/api/v1",
        "model": _env("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "anahtar": _env("OPENROUTER_API_KEY"),
    },
}

FALLBACK_CHAIN = ["glm", "evren-glm", "pollinations"]  # seçilen model çalışmazsa sırayla dene


def default_model() -> str:
    """EVREN anahtarı varsa onu, yoksa gömülü GLM'i kullan."""
    return "evren-glm" if EVREN_API_KEY else "glm"


def model_available(mid: str) -> bool:
    """Model şu an kullanılabilir mi? (anahtar/yapılandırma kontrolü)"""
    m = MODEL_CATALOG.get(mid)
    if not m:
        return False
    p = m["saglayici"]
    if p in ("glm", "pollinations"):
        return True
    if p == "ollama":
        return True  # kullanıcı makinesinde çalışır; yoksa fallback devreye girer
    if p in ("openai_uyumlu", "anthropic", "gemini"):
        base_ok = bool(m.get("base")) or p != "openai_uyumlu"
        model_ok = bool(m.get("model"))
        return base_ok and model_ok
    return False
