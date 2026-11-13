"""BAĞIMSIZ ADAY TARAMASI — portföyden ve yürütmeden tamamen ayrı.

v5.4 denetiminde bulunan kusur
------------------------------
`entry_edge`, adaylarını `BacktestEngine.gate_probe`'dan alıyordu. O
kayıt `_evaluate_signal` içinde, ŞU kontrollerden SONRA yapılıyordu:

  1. `cooldown.blocked(symbol, ts)`      — yeniden giriş beklemesi
  2. `rate_limiter.allow(ts)`            — giriş hız limiti
  3. çağıran döngüde `symbol not in portfolio.positions`
     ve `symbol not in pending_limits`   — açık pozisyon / bekleyen emir

Yani aday evreni SİMÜLE EDİLEN İŞLEMLERE BAĞLIYDI. Zarar eden bir
koşu, sonraki adayları cooldown ve drawdown kilidiyle eliyordu.
"Kapıların hiçbirine bakma" iddiası bu hâliyle YANLIŞTI.

Bu modül ne yapar
-----------------
Portföy, broker, risk ölçekleyici, cooldown ve hız limiti HİÇ kurulmaz.
Her sembol için kayan pencerede yalnız `SignalPipeline.evaluate` çağrılır.

DÜRÜST KAPSAM NOTU
------------------
Bu tarama "kapısız"dır ama "filtresiz" DEĞİLDİR. Pipeline'ın kendi
ön filtreleri (hacim, trend onayı, rejim, fake-breakout) sinyal
TANIMININ parçasıdır ve burada da uygulanır. Ölçülen soru şudur:

    "Bu sinyal, KENDİ ön filtrelerinden geçenlerinde yön bilgisi
     taşıyor mu?"

Şu soru DEĞİLDİR: "Ham fiyat hareketi yön bilgisi taşıyor mu?"
İkincisi için ayrı bir çalışma gerekir. `kapsam` alanı bunu açıkça
yazar; raporlarda taşınmalıdır.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.pipeline import SignalPipeline
from infra.market_data.models import Candle

logger = logging.getLogger(__name__)

KAPSAM_NOTU = (
    "Portföy/broker/cooldown/hız limiti/açık pozisyon kontrolü YOK. "
    "Pipeline'ın kendi ön filtreleri (hacim, trend, rejim, fake-breakout) "
    "sinyal tanımının parçası olduğu için UYGULANIR. Ölçülen: 'sinyalin "
    "kendi filtrelerinden geçenlerinde yön bilgisi var mı?'"
)


@dataclass
class ScanResult:
    """Tarama çıktısı."""

    candidates: list[dict] = field(default_factory=list)
    rejections: dict[str, int] = field(default_factory=dict)
    evaluated: int = 0
    kapsam: str = KAPSAM_NOTU

    def summary(self) -> dict:
        return {
            "aday": len(self.candidates),
            "degerlendirilen_mum": self.evaluated,
            "red_dagilimi": dict(
                sorted(self.rejections.items(), key=lambda kv: -kv[1]),
            ),
            "kapsam": self.kapsam,
        }


def scan_candidates(
    candles: dict[str, list[Candle]],
    config,
    *,
    min_bars: int = 30,
    window_bars: int = 300,
    btc_symbol: str | None = None,
    progress_every: int = 0,
) -> ScanResult:
    """Portföyden bağımsız aday taraması.

    Args:
        candles: sembol -> kapanmış mum listesi (artan zaman).
        config: SuperConfig.
        min_bars: değerlendirme için gereken asgari geçmiş.
        window_bars: pipeline'a verilecek kayan pencere uzunluğu.
            Backtest motorunun `max_history_bars` değeriyle AYNI
            tutulmalı ki canlı/backtest sinyal tanımı eşleşsin.
        btc_symbol: BTC bağlamı için sembol anahtarı.
        progress_every: >0 ise her N sembolde bir logla.

    Returns:
        ScanResult — adaylar portföy durumundan ETKİLENMEZ.
    """
    pipeline = SignalPipeline(config)
    out = ScanResult()

    def _pct_change(rows: list[Candle], n: int, upto: int) -> float:
        if upto < n or upto >= len(rows):
            return 0.0
        prev = rows[upto - n].close
        cur = rows[upto].close
        if prev <= 0:
            return 0.0
        return (cur - prev) / prev * 100.0

    btc_rows = candles.get(btc_symbol) if btc_symbol else None

    for si, (sym, rows) in enumerate(candles.items()):
        n = len(rows)
        for i in range(min_bars, n):
            lo = max(0, i + 1 - window_bars)
            window = rows[lo:i + 1]
            if btc_rows and btc_symbol != sym:
                # BTC bağlamı da aynı zaman damgasına kadar kesilir;
                # ileriye bakma olmaması için BTC'nin kendi dizini kullanılır.
                bpos = _btc_index(btc_rows).get(rows[i].timestamp)
                btc_ctx = _pct_change(btc_rows, 3, bpos) if bpos is not None else 0.0
            else:
                btc_ctx = 0.0

            out.evaluated += 1
            decision = pipeline.evaluate(
                symbol=sym, candles=window, btc_change_pct_15m=btc_ctx,
            )
            sig = decision.signal
            if sig.side == "HOLD":
                code = decision.rejection_code or sig.rejection_code or "sinyal_yok"
                out.rejections[code] = out.rejections.get(code, 0) + 1
                continue
            stop = sig.stop_distance_fraction
            if stop is None or not 0 < stop < 1:
                out.rejections["gecersiz_stop"] = (
                    out.rejections.get("gecersiz_stop", 0) + 1
                )
                continue
            out.candidates.append({
                "symbol": sym,
                "ts_ms": int(rows[i].timestamp),
                "side": sig.side,
                "entry_ref": float(window[-1].close),
                "stop_fraction": float(stop),
                "motor": sig.motor,
                "score": float(decision.score.total if decision.score else 0.0),
                "reason": None,
            })
        if progress_every and (si + 1) % progress_every == 0:
            logger.info(
                "Tarama %d/%d sembol — %d aday, %d değerlendirme",
                si + 1, len(candles), len(out.candidates), out.evaluated,
            )

    logger.info(
        "Bağımsız tarama: %d aday / %d değerlendirme (portföyden bağımsız)",
        len(out.candidates), out.evaluated,
    )
    return out


_BTC_IDX_CACHE: dict[int, dict[int, int]] = {}


def _btc_index(rows: list[Candle]) -> dict[int, int]:
    key = id(rows)
    idx = _BTC_IDX_CACHE.get(key)
    if idx is None:
        idx = {c.timestamp: i for i, c in enumerate(rows)}
        _BTC_IDX_CACHE.clear()
        _BTC_IDX_CACHE[key] = idx
    return idx
