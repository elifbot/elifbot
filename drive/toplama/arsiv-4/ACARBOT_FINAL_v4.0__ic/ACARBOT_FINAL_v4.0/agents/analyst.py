"""v4.0 — Analist ajanı (madde 21): oturum raporunu yorumlar, ÖNERİ verir.

Sözleşme: işlem kararı VERMEZ — yalnız okunabilir gözlem ve öneri üretir.
İki katman:
  1. Kurallı analiz (varsayılan, çevrimdışı, deterministik, test edilebilir):
     işlem/PF/uzman performansı/engel nedenleri/bayat iptalleri üzerinden
     somut tespitler.
  2. Opsiyonel LLM yorumu: `analyst_llm=True` + ortam değişkenleri
     (ACARBOT_LLM_API_URL, ACARBOT_LLM_API_KEY, opsiyonel
     ACARBOT_LLM_MODEL) verildiyse OpenAI-uyumlu chat completions ucuna
     kısa özet gönderilir; her hata sessizce kurallı katmana düşer
     (rapor çıktısı ASLA LLM hatası yüzünden bozulmaz).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from urllib.error import URLError

logger = logging.getLogger(__name__)


def _rule_based_observations(report: dict) -> tuple[list[str], list[str]]:
    observations: list[str] = []
    suggestions: list[str] = []
    closes = report.get("closes", 0) or 0
    entries = report.get("entries", 0) or 0
    balance_start = report.get("start_balance", 0.0)
    balance_end = report.get("end_balance", 0.0)
    net = balance_end - balance_start
    duration = report.get("duration_seconds", 0.0) or 0.0

    if closes == 0 and entries == 0:
        observations.append(
            "Oturumda hiç giriş adayı oluşmadı — eşikler sıkı veya "
            "pencere kısa olabilir."
        )
        suggestions.append(
            "Kısa denemelerde daha çok sinyal görmek için --min-rvol "
            "1.2 gibi gevşetilmiş eşik veya --motors trend deneyin."
        )
    if closes == 0 and entries > 0:
        observations.append(
            f"{entries} giriş emri açıldı ama hiçbiri kapanmadı "
            "(TTL/stop/TP tetiklenmedi)."
        )
    if closes > 0:
        blocks = report.get("counters", {}) or {}
        stale = report.get("stale_entry_cancels", 0) or 0
        if stale > 0:
            observations.append(
                f"{stale} bayat sinyal girişi önlendi (canlı fiyat stopun "
                "ötesindeydi) — koruma çalışıyor."
            )
        rate = blocks.get("rate_limit_deferred")
        if isinstance(rate, (int, float)) and rate >= 3:
            observations.append(
                f"Giriş hız limiti {int(rate)} adayı bekletti."
            )
            suggestions.append(
                "Aday yoğunluğu yüksekse --entry-rate-limit değerini "
                "artırmayı değerlendirin."
            )
        if net < 0:
            observations.append(
                f"Oturum net sonucu negatif ({net:+.2f} USDT)."
            )
            suggestions.append(
                "Kâr gerçekliği kanıtlanmamıştır: eşik/motor kombinasyonunu "
                "backtest + walk-forward ile karşılaştırın (backtest/v4.0 "
                "rejim dökümü tablosuna bakın)."
            )
        elif net > 0:
            observations.append(
                f"Oturum net sonucu pozitif ({net:+.2f} USDT) — tek oturum "
                "istatistiksel kanıt DEĞİLDİR."
            )
    perf = report.get("expert_performance", {}) or {}
    worst, worst_r, worst_n = None, 0.0, 0
    for motor, stats in perf.items():
        trades = int(stats.get("trades", 0) or 0)
        avg_r = float(stats.get("avg_r", 0.0) or 0.0)
        if trades >= 3 and avg_r < worst_r:
            worst, worst_r, worst_n = motor, avg_r, trades
    if worst is not None:
        observations.append(
            f"Uzman motoru '{worst}' {worst_n} işlemde ortalama "
            f"{worst_r:+.2f}R ile en zayıf performansı verdi."
        )
        suggestions.append(
            f"'{worst}' ağırlığı paper/backtest kapanışlarıyla otomatik "
            "azalır; kalıcı zayıflıkta uzman setini gözden geçirin."
        )
    if report.get("safe_mode"):
        observations.append("Oturum güvenli mod gördü (veri sağlığı koruması).")
    kill = report.get("kill_switch", "NORMAL")
    if kill != "NORMAL":
        observations.append(f"Kill switch durumu: {kill} "
                            f"({report.get('halt_reason') or '-'}).")
    if duration and duration < 900:
        observations.append(
            "Oturum 15 dakikanın kısa — sonuçlar gürültü barındırır."
        )
    return observations, suggestions


def _llm_comment(report: dict) -> str | None:
    """OpenAI-uyumlu uçtan kısa yorum; her hata → None (kurallı katman kalır)."""
    base = os.environ.get("ACARBOT_LLM_API_URL", "").strip()
    key = os.environ.get("ACARBOT_LLM_API_KEY", "").strip()
    if not base or not key:
        return None
    model = os.environ.get("ACARBOT_LLM_MODEL", "gpt-4o-mini").strip()
    compact = {
        k: report.get(k)
        for k in (
            "version", "profile", "duration_seconds", "start_balance",
            "end_balance", "realized_pnl_session", "entries", "closes",
            "open_positions", "kill_switch", "safe_mode", "counters",
            "stale_entry_cancels", "signal_thresholds", "expert_performance",
        )
    }
    prompt = (
        "Aşağıdaki crypto paper-trading oturum raporunu 6 cümleyi aşmadan "
        "yorumla. İşlem kararı ÖNERME; yalnız gözlem + iyileştirme fikri "
        "ver. Türkçe yaz.\n" + json.dumps(compact, ensure_ascii=False)
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 400,
    }).encode()
    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(
            (payload.get("choices") or [{}])[0]
            .get("message", {}).get("content", "")
        ).strip() or None
    except (URLError, OSError, ValueError, KeyError, IndexError) as exc:
        logger.warning("Analist LLM yorumu alınamadı (kurallı katman sürer): %s", exc)
        return None


class AnalystAgent:
    """Oturum raporu yorumcusu — ÖNERİ verir, işlem kararı VERMEZ."""

    name = "analyst"

    def __init__(self, llm_enabled: bool = False) -> None:
        self.llm_enabled = llm_enabled

    def analyze(self, report: dict) -> dict:
        observations, suggestions = _rule_based_observations(report)
        comment = None
        if self.llm_enabled:
            comment = _llm_comment(report)
        return {
            "observations": observations,
            "suggestions": suggestions,
            "llm_comment": comment,
            "llm_used": comment is not None,
        }
