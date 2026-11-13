#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ACARBOT56 — Birleşik Çoklu Yapay Zeka Motoru & Adaptif Kantitatif Zeka Katmanı
==============================================================================
1. MultiModelRouter:
   - GitHub Models (GITHUB_TOKEN ile GitHub Actions'ta ücretsiz & anahtarsız!)
   - NVIDIA NIM (Nemotron / DeepSeek-R1)
   - DeepSeek, OpenAI, Groq, Google Gemini, OpenRouter
   - Otomatik sağlık kontrolü, zaman aşımı, yeniden deneme ve yedek modele geçiş (failover)
   - Çoklu Model Konseyi (Multi-Agent Council) mutabakat modu

2. AdaptiveQuantAI:
   - Çevrimdışı/Sıfır Gecikmeli Kantitatif Rejim Sınıflandırıcı:
     * Hurst Üssü (Trend kalıcılığı vs Ortalamaya dönüş)
     * Kaufman Verimlilik Oranı - KER (Temiz trend vs Testere piyasası)
     * Volatilite Sıkışması (Squeeze) ve Likidite/Fitil Tuzağı (Wick Trap) Tespiti
     * Dinamik Ensemble Grup Ağırlığı Optimizasyonu
   - Hibrit LLM Sinyal Danışmanı (Önbellekli, hız sınırı korumalı ikinci göz onayı)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)


def load_dotenv_safe(env_path: str = ".env") -> None:
    """Harici paket gerektirmeden .env dosyasını güvenli şekilde yükler."""
    p = Path(env_path)
    if not p.exists():
        return
    try:
        for raw_line in p.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val
    except Exception as exc:
        logger.debug(".env okunamadı: %s", exc)


# ============================================================
# 1) ÇOKLU YAPAY ZEKA MODEL YÖNLENDİRİCİSİ (MULTI-MODEL ROUTER)
# ============================================================
@dataclass(frozen=True)
class ModelProviderSpec:
    name: str
    env_key: str
    endpoint: str
    default_model: str
    fallback_models: Tuple[str, ...] = ()
    extra_headers: Tuple[Tuple[str, str], ...] = ()
    requires_auth: bool = True


PROVIDER_SPECS: Tuple[ModelProviderSpec, ...] = (
    ModelProviderSpec(
        name="github_models",
        env_key="GITHUB_TOKEN",
        endpoint="https://models.github.ai/inference/chat/completions",
        default_model="openai/gpt-4.1",
        fallback_models=(
            "openai/gpt-4o-mini",
            "deepseek/DeepSeek-R1",
            "meta/Llama-3.3-70B-Instruct",
        ),
        extra_headers=(("Accept", "application/vnd.github+json"),),
    ),
    ModelProviderSpec(
        name="nvidia_nim",
        env_key="NVIDIA_API_KEY",
        endpoint="https://integrate.api.nvidia.com/v1/chat/completions",
        default_model="nvidia/llama-3.3-nemotron-super-49b-v1",
        fallback_models=(
            "deepseek-ai/deepseek-r1",
            "meta/llama-3.3-70b-instruct",
            "nvidia/nemotron-3-ultra-550b-a55b",
        ),
    ),
    ModelProviderSpec(
        name="deepseek",
        env_key="DEEPSEEK_API_KEY",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        default_model="deepseek-chat",
        fallback_models=("deepseek-reasoner",),
    ),
    ModelProviderSpec(
        name="openai",
        env_key="OPENAI_API_KEY",
        endpoint="https://api.openai.com/v1/chat/completions",
        default_model="gpt-4.1-mini",
        fallback_models=("gpt-4o-mini", "gpt-4.1"),
    ),
    ModelProviderSpec(
        name="groq",
        env_key="GROQ_API_KEY",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        default_model="llama-3.3-70b-versatile",
        fallback_models=("llama-3.1-8b-instant",),
    ),
    ModelProviderSpec(
        name="gemini",
        env_key="GEMINI_API_KEY",
        endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        default_model="gemini-2.5-flash",
        fallback_models=("gemini-2.0-flash",),
    ),
    ModelProviderSpec(
        name="openrouter",
        env_key="OPENROUTER_API_KEY",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        default_model="deepseek/deepseek-chat-v3-0324:free",
        fallback_models=("meta-llama/llama-3.3-70b-instruct:free",),
    ),
)


@dataclass
class LLMResponse:
    ok: bool
    content: str
    provider: str = "none"
    model: str = "none"
    latency_ms: int = 0
    error: str = ""


class MultiModelRouter:
    """
    Mevcut API anahtarlarını otomatik algılar ve en güçlü modelden başlayarak
    hataya dayanıklı (failover) şekilde yanıt üretir.
    """

    def __init__(self, timeout_sec: int = 60, allow_pollinations: Optional[bool] = None):
        load_dotenv_safe()
        self.timeout_sec = timeout_sec
        if allow_pollinations is None:
            self.allow_pollinations = os.getenv("AI_ALLOW_POLLINATIONS", "0").strip() in ("1", "true", "yes")
        else:
            self.allow_pollinations = allow_pollinations
        self.preferred_model = os.getenv("AI_PREFERRED_MODEL", "").strip()

    def available_providers(self) -> List[ModelProviderSpec]:
        active: List[ModelProviderSpec] = []
        for spec in PROVIDER_SPECS:
            token = os.getenv(spec.env_key, "").strip()
            if token:
                active.append(spec)
        return active

    def status_summary(self) -> Dict[str, Any]:
        avail = self.available_providers()
        return {
            "active_provider_count": len(avail),
            "active_providers": [
                {"provider": s.name, "default_model": s.default_model, "env": s.env_key}
                for s in avail
            ],
            "pollinations_fallback": self.allow_pollinations,
            "preferred_model": self.preferred_model or "auto",
        }

    def chat(
        self,
        prompt: str,
        system_prompt: str = "Sen disiplinli bir algoritmik ticaret ve yazılım mühendisliği uzmanısın.",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        preferred_provider: Optional[str] = None,
    ) -> LLMResponse:
        providers = self.available_providers()
        if preferred_provider:
            providers = sorted(providers, key=lambda p: 0 if p.name == preferred_provider else 1)

        errors: List[str] = []
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        for spec in providers:
            token = os.getenv(spec.env_key, "").strip()
            models_to_try = [spec.default_model, *spec.fallback_models]
            if self.preferred_model and self.preferred_model not in models_to_try:
                models_to_try.insert(0, self.preferred_model)

            for model_name in models_to_try:
                t0 = time.time()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                for hk, hv in spec.extra_headers:
                    headers[hk] = hv

                payload = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                try:
                    resp = requests.post(
                        spec.endpoint,
                        headers=headers,
                        json=payload,
                        timeout=self.timeout_sec,
                    )
                    latency = int((time.time() - t0) * 1000)
                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices") or []
                        if choices:
                            msg = choices[0].get("message") or {}
                            text = (msg.get("content") or "").strip()
                            # DeepSeek-R1 <think>...</think> bloklarını temizle (varsa ana cevabı koru)
                            clean_text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
                            if clean_text:
                                return LLMResponse(
                                    ok=True,
                                    content=clean_text,
                                    provider=spec.name,
                                    model=model_name,
                                    latency_ms=latency,
                                )
                    errors.append(f"{spec.name}/{model_name}: HTTP {resp.status_code}")
                except Exception as exc:
                    errors.append(f"{spec.name}/{model_name}: {str(exc)[:120]}")

        if self.allow_pollinations:
            t0 = time.time()
            try:
                resp = requests.post(
                    "https://text.pollinations.ai/openai",
                    json={"model": "openai", "messages": messages, "temperature": temperature},
                    timeout=self.timeout_sec,
                )
                latency = int((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"].strip()
                    except Exception:
                        content = resp.text.strip()
                    if content:
                        return LLMResponse(
                            ok=True,
                            content=content,
                            provider="pollinations",
                            model="openai-fallback",
                            latency_ms=latency,
                        )
            except Exception as exc:
                errors.append(f"pollinations: {str(exc)[:120]}")

        return LLMResponse(
            ok=False,
            content="",
            error="; ".join(errors) if errors else "Aktif yapay zeka API anahtarı bulunamadı.",
        )

    def chat_json(
        self,
        prompt: str,
        system_prompt: str = "Sadece geçerli JSON döndür. Açıklama ekleme.",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> Tuple[Optional[Dict[str, Any]], LLMResponse]:
        """LLM'den yapılandırılmış JSON yanıt alır ve güvenli şekilde ayrıştırır."""
        res = self.chat(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not res.ok:
            return None, res

        parsed = extract_json_object(res.content)
        return parsed, res

    def ask_council(self, prompt: str, max_members: int = 2) -> Dict[str, Any]:
        """
        Birden fazla farklı sağlayıcı veya uzman persona kullanarak konsey mutabakatı üretir.
        """
        personas = [
            (
                "Kantitatif Stratejist",
                "Sen kıdemli bir kantitatif kripto vadeli işlemler stratejistisin. Sinyal kalitesi, rejim uyumu ve beklenen değere (EV) odaklan.",
            ),
            (
                "Baş Risk Yöneticisi (CRO)",
                "Sen acımasız bir risk yöneticisisin. Likidasyon güvenliği, sahte kırılım tuzakları, korelasyon ve sermaye korumasına odaklan.",
            ),
        ]
        providers = self.available_providers()
        opinions: List[Dict[str, Any]] = []

        for idx in range(min(max_members, len(personas))):
            role_name, sys_prompt = personas[idx]
            pref = providers[idx % len(providers)].name if providers else None
            resp = self.chat(
                prompt=prompt,
                system_prompt=sys_prompt,
                temperature=0.2,
                max_tokens=1500,
                preferred_provider=pref,
            )
            if resp.ok:
                opinions.append(
                    {
                        "role": role_name,
                        "provider": resp.provider,
                        "model": resp.model,
                        "latency_ms": resp.latency_ms,
                        "analysis": resp.content,
                    }
                )

        return {
            "council_size": len(opinions),
            "opinions": opinions,
        }


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Markdown blokları veya düz metin içerisinden ilk geçerli JSON nesnesini çıkarır."""
    if not text:
        return None
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates = []
    if fence_match:
        candidates.append(fence_match.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def extract_python_code(text: str) -> str:
    """LLM çıktısından temiz Python kodunu ayıklar."""
    if not text:
        return ""
    fence = re.search(r"```python\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    generic = re.search(r"```\s*(.*?)```", text, flags=re.DOTALL)
    if generic:
        return generic.group(1).strip()
    return text.strip()


# ============================================================
# 2) ADAPTİF KANTİTATİF ZEKA VE PİYASA REJİMİ DANIŞMANI
# ============================================================
@dataclass
class MarketRegimeInsight:
    regime: str  # STRONG_TREND, SQUEEZE_BREAKOUT, MEAN_REVERTING, HIGH_VOL_CHOP, NEUTRAL
    hurst: float
    efficiency_ratio: float
    volatility_z: float
    squeeze_active: bool
    wick_trap_side: int  # +1 = bull trap (long açma!), -1 = bear trap (short açma!), 0 = temiz
    confidence_mult: float
    stop_mult: float
    weights: Dict[str, float] = field(default_factory=dict)
    veto: bool = False
    veto_reason: str = ""
    llm_used: bool = False
    llm_model: str = ""
    llm_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AdaptiveQuantAI:
    """
    Tüm botlar tarafından paylaşılabilen 2 katmanlı yapay zeka motoru:
      Katman 1 (Her mumda 0ms gecikmeyle çalışır):
        - Hurst Üssü + Kaufman Efficiency Ratio + Volatilite Z-Skoru + Fitil Tuzağı Analizi
        - Piyasa rejimine göre Ensemble ağırlıklarını ve risk çarpanlarını dinamik ayarlar.
      Katman 2 (İsteğe bağlı / Önbellekli LLM İkinci Göz Onayı):
        - Yüksek skorlu aday sinyalleri aktif LLM modeline (GPT-4.1 / Nemotron / DeepSeek)
          sorarak sahte kırılım (bull/bear trap) veto veya güven artışı uygular.
    """

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "trend": 0.25,
        "momentum": 0.25,
        "breakout": 0.25,
        "volume_flow": 0.25,
        "fade": 0.0,
    }

    def __init__(
        self,
        enable_llm: bool = True,
        llm_cache_ttl_sec: int = 300,
        router: Optional[MultiModelRouter] = None,
    ):
        self.router = router or MultiModelRouter(timeout_sec=20)
        self.enable_llm = enable_llm
        self.llm_cache_ttl_sec = llm_cache_ttl_sec
        self._llm_cache: Dict[str, Tuple[float, Dict[str, Any], str]] = {}

    @staticmethod
    def compute_hurst(close: pd.Series, max_lag: int = 20) -> float:
        """Log-fiyat farklarının gecikmeli varyans eğiminden Hurst üssünü tahmin eder."""
        arr = np.asarray(close.dropna(), dtype=float)
        if len(arr) < max_lag * 3 or np.any(arr <= 0):
            return 0.5
        log_px = np.log(arr[-120:])
        lags = range(2, min(max_lag, len(log_px) // 3))
        taus = []
        valid_lags = []
        for lag in lags:
            diff = log_px[lag:] - log_px[:-lag]
            std = float(np.std(diff))
            if std > 1e-12 and np.isfinite(std):
                taus.append(std)
                valid_lags.append(lag)
        if len(valid_lags) < 4:
            return 0.5
        poly = np.polyfit(np.log(valid_lags), np.log(taus), 1)
        return float(np.clip(poly[0], 0.15, 0.85))

    @staticmethod
    def compute_efficiency_ratio(close: pd.Series, period: int = 20) -> float:
        """Kaufman Efficiency Ratio (0 = tam gürültü/testere, 1 = kusursuz doğrusal trend)."""
        arr = np.asarray(close.dropna(), dtype=float)
        if len(arr) <= period:
            return 0.3
        window = arr[-(period + 1) :]
        net_move = abs(window[-1] - window[0])
        path_move = float(np.sum(np.abs(np.diff(window))))
        if path_move <= 1e-12:
            return 0.0
        return float(np.clip(net_move / path_move, 0.0, 1.0))

    @staticmethod
    def detect_wick_trap(df: pd.DataFrame, closed_bar_idx: int = -2) -> int:
        """
        Son kapanmış mumda aşırı likidite avı / sahte kırılım fitili var mı tespit eder.
        +1 -> Üstte devasa reddedilme fitili (Bull Trap -> LONG tehlikeli!)
        -1 -> Altta devasa reddedilme fitili (Bear Trap -> SHORT tehlikeli!)
         0 -> Temiz
        """
        if len(df) < 25:
            return 0
        idx = closed_bar_idx if len(df) >= abs(closed_bar_idx) else -1
        o = float(df["open"].iloc[idx])
        h = float(df["high"].iloc[idx])
        l = float(df["low"].iloc[idx])
        c = float(df["close"].iloc[idx])
        rng = h - l
        if rng <= 1e-12 or c <= 0:
            return 0

        avg_rng = float((df["high"] - df["low"]).iloc[-22:-2].mean())
        if avg_rng <= 0 or rng < avg_rng * 1.4:
            return 0

        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        recent_high = float(df["high"].iloc[-22:idx].max())
        recent_low = float(df["low"].iloc[-22:idx].min())

        if upper_wick / rng >= 0.62 and h >= recent_high and c < o:
            return 1  # Bull trap
        if lower_wick / rng >= 0.62 and l <= recent_low and c > o:
            return -1  # Bear trap
        return 0

    def analyze_regime(
        self,
        df: pd.DataFrame,
        proposed_side: int = 0,
        funding_rate: Optional[float] = None,
        closed_bar: bool = True,
    ) -> MarketRegimeInsight:
        """OHLCV verisinden piyasa rejimini, dinamik ağırlıkları ve tuzak vetolarını hesaplar."""
        if len(df) < 60:
            return MarketRegimeInsight(
                regime="NEUTRAL",
                hurst=0.5,
                efficiency_ratio=0.3,
                volatility_z=0.0,
                squeeze_active=False,
                wick_trap_side=0,
                confidence_mult=1.0,
                stop_mult=1.0,
                weights=dict(self.DEFAULT_WEIGHTS),
            )

        idx = -2 if (closed_bar and len(df) >= 62) else -1
        sub = df.iloc[: idx + 1] if idx == -2 else df
        close = sub["close"].astype(float)
        high = sub["high"].astype(float)
        low = sub["low"].astype(float)

        hurst = self.compute_hurst(close)
        ker = self.compute_efficiency_ratio(close, 20)

        # Volatilite Z-skoru ve Bollinger Sıkışması (Squeeze)
        ret = close.pct_change().dropna()
        vol_now = float(ret.iloc[-12:].std()) if len(ret) >= 12 else 0.0
        vol_mean = float(ret.iloc[-60:].std()) if len(ret) >= 30 else vol_now
        vol_z = (vol_now - vol_mean) / (vol_mean * 0.35 + 1e-9) if vol_mean > 0 else 0.0
        vol_z = float(np.clip(vol_z, -3.0, 3.0))

        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_width = ((4.0 * std20) / sma20.replace(0, np.nan)).dropna()
        squeeze_active = False
        if len(bb_width) >= 40:
            bw_now = float(bb_width.iloc[-1])
            bw_q25 = float(np.percentile(bb_width.iloc[-40:], 25))
            squeeze_active = bw_now <= bw_q25

        trap = self.detect_wick_trap(df, closed_bar_idx=idx)

        # Rejim Sınıflandırması + Dinamik Ağırlık Optimizasyonu
        weights = dict(self.DEFAULT_WEIGHTS)
        conf_mult = 1.0
        stop_mult = 1.0
        veto = False
        veto_reason = ""

        if vol_z > 2.1 and ker < 0.22:
            regime = "HIGH_VOL_CHOP"
            weights = {
                "trend": 0.15,
                "momentum": 0.15,
                "breakout": 0.10,
                "volume_flow": 0.25,
                "fade": 0.35,
            }
            conf_mult = 0.78
            stop_mult = 1.15
        elif squeeze_active and ker >= 0.28:
            regime = "SQUEEZE_BREAKOUT"
            weights = {
                "trend": 0.24,
                "momentum": 0.22,
                "breakout": 0.30,
                "volume_flow": 0.18,
                "fade": 0.06,
            }
            conf_mult = 1.12
            stop_mult = 1.0
        elif hurst >= 0.54 and ker >= 0.35:
            regime = "STRONG_TREND"
            weights = {
                "trend": 0.34,
                "momentum": 0.24,
                "breakout": 0.18,
                "volume_flow": 0.18,
                "fade": 0.06,
            }
            conf_mult = 1.15
            stop_mult = 1.05
        elif hurst <= 0.48 and ker <= 0.22 and not squeeze_active:
            regime = "MEAN_REVERTING"
            weights = {
                "trend": 0.20,
                "momentum": 0.20,
                "breakout": 0.15,
                "volume_flow": 0.20,
                "fade": 0.25,
            }
            conf_mult = 0.88
            stop_mult = 1.0
            if ker < 0.20 and vol_z < 1.2:
                veto = True
                veto_reason = f"ai_testere_piyasasi_korumasi(ker={ker:.2f})"
        else:
            regime = "NEUTRAL"

        # Tuzak & Aşırı Fonlama Vetosu
        if proposed_side > 0 and trap == 1:
            veto = True
            veto_reason = "ai_bull_trap_fitil_reddi"
        elif proposed_side < 0 and trap == -1:
            veto = True
            veto_reason = "ai_bear_trap_fitil_reddi"
        elif funding_rate is not None:
            if proposed_side > 0 and funding_rate > 0.0012:
                veto = True
                veto_reason = f"ai_asiri_kalabalik_long_funding({funding_rate:.4%})"
            elif proposed_side < 0 and funding_rate < -0.0012:
                veto = True
                veto_reason = f"ai_asiri_kalabalik_short_funding({funding_rate:.4%})"

        return MarketRegimeInsight(
            regime=regime,
            hurst=round(hurst, 4),
            efficiency_ratio=round(ker, 4),
            volatility_z=round(vol_z, 3),
            squeeze_active=squeeze_active,
            wick_trap_side=trap,
            confidence_mult=round(conf_mult, 3),
            stop_mult=round(stop_mult, 3),
            weights=weights,
            veto=veto,
            veto_reason=veto_reason,
        )

    def evaluate_signal_with_llm(
        self,
        symbol: str,
        side: int,
        score: float,
        confidence: float,
        regime_insight: MarketRegimeInsight,
        indicators: Dict[str, Any],
    ) -> MarketRegimeInsight:
        """
        Aktif bir LLM sağlayıcısı varsa, aday sinyali kantitatif risk filtresinden geçirir.
        Önbellek sayesinde aynı sembol/yön için gereksiz API çağrısı yapmaz.
        """
        if not self.enable_llm or regime_insight.veto or side == 0:
            return regime_insight
        if not self.router.available_providers() and not self.router.allow_pollinations:
            return regime_insight

        cache_raw = f"{symbol}:{side}:{regime_insight.regime}:{round(score, 1)}"
        cache_key = hashlib.sha256(cache_raw.encode()).hexdigest()[:16]
        now = time.time()
        cached = self._llm_cache.get(cache_key)
        if cached and (now - cached[0]) < self.llm_cache_ttl_sec:
            data, model_tag = cached[1], cached[2]
            return self._apply_llm_decision(regime_insight, data, model_tag)

        direction_str = "LONG" if side > 0 else "SHORT"
        prompt = (
            f"Sembol: {symbol} | Yön: {direction_str} | Ensemble Skor: {score:+.3f} | Güven: {confidence:.2f}\n"
            f"Rejim: {regime_insight.regime} | Hurst: {regime_insight.hurst} | KER: {regime_insight.efficiency_ratio} "
            f"| VolZ: {regime_insight.volatility_z} | Squeeze: {regime_insight.squeeze_active}\n"
            f"Göstergeler: {json.dumps(indicators, ensure_ascii=False)}\n\n"
            "Bu vadeli işlem sinyalini risk/getiri ve tuzak olasılığı açısından değerlendir. "
            "SADECE aşağıdaki JSON şemasıyla yanıt ver:\n"
            '{"approve": true, "confidence_mult": 1.0, "reason": "kısa Türkçe gerekçe"}'
        )

        parsed, resp = self.router.chat_json(
            prompt=prompt,
            system_prompt=(
                "Sen kurumsal bir kripto vadeli işlemler kantitatif risk komitesisin. "
                "Yalnızca geçerli JSON döndür. confidence_mult 0.70 ile 1.20 arasında olmalı."
            ),
            temperature=0.1,
            max_tokens=300,
        )
        if parsed and resp.ok:
            model_tag = f"{resp.provider}/{resp.model}"
            self._llm_cache[cache_key] = (now, parsed, model_tag)
            return self._apply_llm_decision(regime_insight, parsed, model_tag)
        return regime_insight

    @staticmethod
    def _apply_llm_decision(
        insight: MarketRegimeInsight, data: Dict[str, Any], model_tag: str
    ) -> MarketRegimeInsight:
        approve = bool(data.get("approve", True))
        try:
            mult = float(data.get("confidence_mult", 1.0))
        except Exception:
            mult = 1.0
        mult = float(np.clip(mult, 0.70, 1.20))
        note = str(data.get("reason", ""))[:180]

        insight.llm_used = True
        insight.llm_model = model_tag
        insight.llm_note = note
        insight.confidence_mult = round(insight.confidence_mult * mult, 3)
        if not approve:
            insight.veto = True
            insight.veto_reason = f"llm_veto({note or model_tag})"
        return insight
