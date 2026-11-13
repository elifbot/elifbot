"""Korku / Açgözlülük motoru — haberlerin psikolojik etkisi (0..100).

  0  = aşırı KORKU (panik)  → yeni işlemleri VETO et
  50 = nötr
  100 = aşırı AÇGÖZLÜLÜK   → LONG kovalamayı VETO et (zirve avcılığı yapma)

İki katmanlı çalışır (hız + zekâ dengesi):
  1) YEREL motor (milisaniyeler): Türkçe+İngilizce ağırlıklı sözlük, güçlendirici
     (çok/devasa/tarihi) ve olumsuzluk (değil/not) algısıyla. HER ZAMAN çalışır.
  2) LLM API (opsiyonel, saniyeler): OpenAI-uyumlu herhangi bir uç
     (OpenAI, Groq, Together, yerel Ollama/vLLM...). Sonuçlar önbelleğe alınır
     ve arka planda zenginleştirme yapılır; asla işlem hızını kesmez.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time

# -- ağırlıklı sözlükler --------------------------------------------------------
FEAR_WORDS = {
    # kritik (ağır)
    "hack": 3, "hacked": 3, "exploit": 3, "stolen": 3, "çalındı": 3,
    "dolandırıcılık": 3, "fraud": 3, "scam": 3, "rug": 3, "ponzi": 3,
    "bankrupt": 3, "iflas": 3, "insolvent": 3, "collapse": 3, "çöküş": 3,
    "depeg": 3, "lawsuit": 2.5, "dava": 2.5, "sec": 2, "delist": 2.5,
    "yasak": 2.5, "banned": 2.5, "ban": 2, "tutuklandı": 2.5, "arrested": 2.5,
    "soruşturma": 2, "investigation": 2, "ceza": 2, "fine": 2,
    "çekimleri durdur": 3, "freeze": 2.5, "saldırı": 2.5, "attack": 2.5,
    # orta
    "crash": 2, "dump": 2, "plunge": 2, "düşüş": 1.5, "drop": 1.5,
    "ayı": 1.5, "bearish": 1.5, "bear": 1.5, "korku": 2, "fear": 2,
    "panik": 2.5, "panic": 2.5, "kapitülasyon": 2, "capitulation": 2,
    "satış baskısı": 2, "selling pressure": 2, "outflow": 1.5, "çıkış": 1.5,
    "düzeltme": 1, "correction": 1, "pullback": 1, "geri çekilme": 1,
    "faiz artırımı": 1.5, "rate hike": 1.5, "hawkish": 1.5, "şahin": 1.5,
    "resesyon": 1.5, "recession": 1.5, "savaş": 1.5, "war": 1.5,
    "tarife": 1, "tariff": 1, "riskten kaçış": 1.5, "risk-off": 1.5,
    "likidasyon": 1.5, "liquidation": 1.5, "tasfiye": 1.5,
}

GREED_WORDS = {
    "etf": 2.5, "onay": 2.5, "approval": 2.5, "approved": 2.5, "onaylandı": 2.5,
    "listing": 2.5, "listeleme": 2.5, "listed": 2, "listelendi": 2,
    "ortaklık": 2, "partnership": 2, "partnered": 2,
    "yakım": 2, "burn": 2, "burned": 2,
    "kurumsal": 2, "institutional": 2, "benimseme": 2, "adoption": 2,
    "rekor": 2.5, "record": 2.5, "all-time high": 3, "ath": 2.5,
    "ralli": 2, "rally": 2, "surge": 2, "artış": 1.5, "soar": 2,
    "yükseliş": 1.5, "yükselişi": 1.5, "boğa": 2, "boğası": 2,
    "bullish": 2, "bull": 1.5, "moon": 2.5, "coşku": 2, "coşkusu": 2,
    "artışı": 1.5, "rekoru": 2.5,
    "breakout": 2, "kırılım": 2, "faiz indirimi": 2, "rate cut": 2,
    "teşvik": 1.5, "stimulus": 1.5, "lansman": 1.5, "launch": 1.5,
    "mainnet": 1.5, "upgrade": 1, "yükseltme": 1, "giriş": 1.5, "inflow": 1.5,
    "güven": 1, "confidence": 1, "iyimserlik": 1.5, "optimism": 1.5,
    "büyüme": 1, "growth": 1, "rekor giriş": 2.5, "milyar": 1,
    "fon topladı": 1.5, "raised": 1.5, "destek": 1, "support": 1,
}

INTENSIFIERS = {"çok": 1.4, "son derece": 1.6, "devasa": 1.6, "dev": 1.5,
                "tarihi": 1.6, "historic": 1.6, "massive": 1.6, "huge": 1.5,
                "extreme": 1.6, "aşırı": 1.6, "eşi görülmemiş": 1.7,
                "unprecedented": 1.7, "sharp": 1.4, "keskin": 1.4,
                "sert": 1.4, "büyük": 1.3, "big": 1.3, "major": 1.4}
NEGATIONS = {"değil", "not", "no", "yok", "olmadan", "without", "neither", "nor"}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zçğıöşüâîû0-9]+(?:'[a-z]+)?", text.lower())


def local_fear_greed(text: str) -> float:
    """Yerel sözlük motoru → 0 (korku) .. 100 (açgözlülük). ~1ms sürer."""
    if not text:
        return 50.0
    low = text.lower()
    tokens = _tokenize(low)
    score = 0.0

    # Çok kelimeli kalıplar önce (örn. "satış baskısı")
    for phrase, w in list(FEAR_WORDS.items()) + list(GREED_WORDS.items()):
        if " " in phrase and phrase in low:
            score += -w if phrase in FEAR_WORDS else w

    for i, tok in enumerate(tokens):
        w = 0.0
        if tok in FEAR_WORDS and " " not in tok:
            w = -FEAR_WORDS[tok]
        elif tok in GREED_WORDS and " " not in tok:
            w = GREED_WORDS[tok]
        if w == 0.0:
            continue
        window = tokens[max(0, i - 2):i]
        if any(n in window for n in NEGATIONS):
            w = -w * 0.7  # olumsuzluk: etkiyi tersine çevir
        elif any(x in window for x in INTENSIFIERS):
            mult = max(INTENSIFIERS.get(x, 1.0) for x in window if x in INTENSIFIERS)
            w *= mult
        score += w

    # Büyük para + yön kelimesi = psikolojik etki büyür
    if re.search(r"\$\s?\d{2,}|milyar|billion", low):
        score *= 1.25

    fg = 50 + score * 6
    return round(max(0.0, min(100.0, fg)), 1)


class LLMScorer:
    """OpenAI-uyumlu API ile korku/açgözlülük skoru (opsiyonel)."""

    def __init__(self, api_url: str = "", api_key: str = "", model: str = "",
                 timeout: int = 8):
        self.api_url = (api_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or "gpt-4o-mini"
        self.timeout = timeout
        self._cache: dict[str, tuple[float, float]] = {}  # hash -> (skor, ts)

    @property
    def enabled(self) -> bool:
        return bool(self.api_url and self.api_key)

    def _cached(self, key: str) -> float | None:
        hit = self._cache.get(key)
        if hit and time.time() - hit[1] < 24 * 3600:
            return hit[0]
        return None

    async def score(self, title: str, body: str = "") -> float | None:
        """LLM'den 0..100 skor ister. Başarısızlıkta None (yerel motora düşülür)."""
        if not self.enabled:
            return None
        key = hashlib.md5(f"{title}|{body[:200]}".encode()).hexdigest()
        hit = self._cached(key)
        if hit is not None:
            return hit
        try:
            import aiohttp
            prompt = ("Kripto haberinin piyasada yaratacağı psikolojik etkiyi puanla: "
                      "0=tam panik/korku, 100=tam coşku/açgözlülük. "
                      'SADECE şu JSON ile cevap ver: {"fear_greed": SAYI}')
            payload = {"model": self.model, "temperature": 0, "max_tokens": 20,
                       "messages": [{"role": "system", "content": prompt},
                                    {"role": "user", "content": f"{title}\n{body[:500]}"}]}
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{self.api_url}/chat/completions",
                                  json=payload, headers=headers,
                                  timeout=self.timeout) as r:
                    data = await r.json()
            text = data["choices"][0]["message"]["content"]
            m = re.search(r"(\d+(?:\.\d+)?)", text)
            if not m:
                return None
            val = max(0.0, min(100.0, float(m.group(1))))
            self._cache[key] = (val, time.time())
            return val
        except Exception:
            return None


class FearGreedEngine:
    """Yerel + LLM birleşik motor. Senkron hızlı yol + asenkron zenginleştirme."""

    def __init__(self, api_url: str = "", api_key: str = "", model: str = ""):
        self.llm = LLMScorer(api_url, api_key, model)

    def score_sync(self, text: str) -> float:
        return local_fear_greed(text)

    async def ascore(self, title: str, body: str = "") -> tuple[float, str]:
        """(skor, kaynak). LLM varsa %60 LLM + %40 yerel harmanı."""
        local = local_fear_greed(f"{title} {body}")
        llm_val = await self.llm.score(title, body)
        if llm_val is None:
            return local, "yerel"
        return round(llm_val * 0.6 + local * 0.4, 1), "llm+yerel"


async def demo():
    eng = FearGreedEngine()
    for t in ["Bitcoin ETF onaylandı, milyarlarca dolar giriş bekleniyor",
              "Borsadan 200 milyon dolar çalındı, panik satışları başladı",
              "Ethereum güncellemesi planlandığı gibi tamamlandı"]:
        print(t, "→", await eng.ascore(t))


if __name__ == "__main__":
    asyncio.run(demo())
