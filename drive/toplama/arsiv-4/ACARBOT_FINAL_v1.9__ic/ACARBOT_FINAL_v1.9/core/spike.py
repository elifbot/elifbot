"""Birim-tutarlı hacim patlaması (RVOL) ölçümü.

Yorum 2, madde 1'deki KRİTİK hatanın düzeltmesidir:

  Eski kod, canlı akışta saniyelik sentetik mum üretip (`quote_hacim / fiyat`
  = 1 saniyelik BAZ hacim) bunu `measure_impulse_rvol` ile 5 dakikalık
  TAM mumların ortalamasına karşılaştırıyordu. Payda 300 saniyelik,
  pay 1 saniyelik olduğu için RVOL ≈ gerçek değer / 300 çıkıyordu.
  3x'lik patlama RVOL ≈ 0.01 veriyor, 1.5 eşiği ≈ 450x patlama istiyordu
  ve canlıda her aday "dusuk_hacim" ile reddediliyordu.

Çözüm: pay ve payda AYNI ölçekte olmalı.
  - Canlı (tick/ticker akışı): saniyelik baz hacim ↔ saniyelik baz hacim.
  - Mum yolu (backtest / 5m kapanışı): mum baz hacmi ↔ mum baz hacmi ortalaması.
  - Birim doğrulama: RVOL makul aralığın (sanity cap) çok üzerindeyse veri
    hatalı kabul edilir (ör. OKX kontrat birimi baz hacim sanılmışsa).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class SpikeEvent:
    """Bir hacim patlamasının ölçümü — tüm hacimler BAZ varlık birimindedir."""

    base_volume: float                  # patlama penceresindeki baz hacim
    window_seconds: float               # patlama penceresi süresi
    base_volume_per_second: float       # patlama / pencere
    baseline_per_second: float          # geçmiş pencere ortalaması (aynı ölçek)
    rvol: float                         # 1.0 = normal, 3.0 = 3 katı
    direction: str | None               # "LONG" / "SHORT" / None (yön belirsiz)
    price_change_pct: float             # yön penceresindeki % fiyat değişimi
    price: float
    timestamp_ms: int
    suspect: bool = False               # birim/veri şüphesi varsa True
    # v1.9: likiditesiz enstrüman ayrımı
    illiquid: bool = False              # taban hacim çok düşükse True
    baseline_notional_per_second: float = 0.0   # taban hacmin USDT karşılığı


@dataclass
class _SecondBucket:
    second: int
    base_volume: float
    price: float


class SpikeDetector:
    """Saniyelik baz-hacim tabanlı RVOL dedektörü (canlı akış için).

    Girdi olarak her fiyat güncellemesinde o saniyede işlem gören BAZ varlık
    hacmi verilir (ör. ticker 24s hacim deltası / fiyat, ya da aggTrade miktarı).
    Kritik nokta: `update` fonksiyonuna verilen hacim ZATEN saniyelik baz hacim
    olduğu için taban da saniyelik ortalamadır → RVOL boyutsuz ve dürüsttür.
    """

    def __init__(
        self,
        multiplier: float = 3.0,
        lookback_seconds: int = 300,
        window_seconds: int = 3,
        direction_seconds: int = 5,
        sanity_cap: float = 100.0,
        min_baseline_notional_per_second: float = 0.0,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not isfinite(multiplier) or multiplier <= 0:
            raise ValueError("multiplier pozitif ve sonlu olmalı")
        if not isinstance(lookback_seconds, int) or lookback_seconds < 1:
            raise ValueError("lookback_seconds pozitif tam sayı olmalı")
        if window_seconds < 1 or direction_seconds < 1:
            raise ValueError("pencere süreleri >= 1 olmalı")
        if sanity_cap <= multiplier:
            raise ValueError("sanity_cap, multiplier'dan büyük olmalı")
        self.multiplier = multiplier
        self.lookback_seconds = lookback_seconds
        self.window_seconds = window_seconds
        self.direction_seconds = direction_seconds
        self.sanity_cap = sanity_cap
        if (
            not isfinite(min_baseline_notional_per_second)
            or min_baseline_notional_per_second < 0
        ):
            raise ValueError("min_baseline_notional_per_second >= 0 olmalı")
        self.min_baseline_notional_per_second = min_baseline_notional_per_second
        # v1.9: aynı patlama penceresi tekrar tekrar olay üretmesin.
        # Eski davranış yalnızca AYNI saniyede tek olay diyordu; 3 sn pencere
        # boyunca aynı patlama 3 kez loglanıyordu (log seli).
        self.cooldown_seconds = max(
            1, window_seconds if cooldown_seconds is None else cooldown_seconds
        )
        self._buckets: dict[str, deque[_SecondBucket]] = {}
        self._last_spike: dict[str, int] = {}

    def update(
        self,
        symbol: str,
        price: float,
        base_volume: float,
        timestamp_ms: int,
    ) -> SpikeEvent | None:
        """Bir saniyelik baz hacim ekler ve patlama oluşursa SpikeEvent döndürür.

        `base_volume`, `timestamp_ms` içindeki saniyeye ait TOPLAM baz hacimdir.
        """
        symbol = symbol.upper()
        if (
            not isfinite(price) or price <= 0
            or not isfinite(base_volume) or base_volume < 0
            or timestamp_ms < 0
        ):
            raise ValueError("fiyat/hacim/zaman damgası geçersiz")

        second = timestamp_ms // 1000
        buckets = self._buckets.get(symbol)
        if buckets is None:
            buckets = deque(maxlen=self.lookback_seconds + self.window_seconds)
            self._buckets[symbol] = buckets

        if buckets and second < buckets[-1].second:
            return None  # geç gelen güncelleme yok sayılır

        if not buckets or second > buckets[-1].second:
            buckets.append(_SecondBucket(second, 0.0, price))

        buckets[-1].base_volume += base_volume
        buckets[-1].price = price

        # Isınma: taban hesabı için yeterli geçmiş yoksa sinyal üretilmez.
        if len(buckets) < self.lookback_seconds + 1:
            return None

        # Patlama penceresi: son `window_seconds` saniyenin toplamı.
        window_volume = sum(b.base_volume for b in list(buckets)[-self.window_seconds:])
        window_span = min(self.window_seconds, len(buckets))
        history = list(buckets)[:-window_span]
        if len(history) < self.lookback_seconds:
            return None
        baseline_volume = sum(b.base_volume for b in history[-self.lookback_seconds:])
        baseline_per_second = baseline_volume / float(self.lookback_seconds)
        if baseline_per_second <= 0:
            return None

        per_second = window_volume / float(window_span)
        rvol = per_second / baseline_per_second
        if rvol < self.multiplier:
            return None
        last_spike_second = self._last_spike.get(symbol)
        if (
            last_spike_second is not None
            and second - last_spike_second < self.cooldown_seconds
        ):
            return None  # aynı patlama penceresi yeniden olay üretmez
        self._last_spike[symbol] = second

        # Yön: son `direction_seconds` saniyenin fiyat değişimi.
        direction_span = min(self.direction_seconds, len(buckets))
        first_price = list(buckets)[-direction_span].price
        change_pct = (price / first_price - 1.0) * 100.0 if first_price > 0 else 0.0
        direction = None
        if change_pct > 1e-9:
            direction = "LONG"
        elif change_pct < -1e-9:
            direction = "SHORT"

        # v1.9: önce likidite, sonra birim doğrulaması.
        # Taban hacmi çok küçükse (likiditesiz enstrüman) tek bir normal işlem
        # bile RVOL'u 100-10000x gösterir. Bu VERİ HATASI DEĞİLDİR.
        baseline_notional = baseline_per_second * price
        illiquid = (
            self.min_baseline_notional_per_second > 0
            and baseline_notional < self.min_baseline_notional_per_second
        )
        # Gerçek veri/birim şüphesi: taban likit olduğu hâlde absürt sapma.
        suspect = rvol > self.sanity_cap and not illiquid
        return SpikeEvent(
            base_volume=window_volume,
            window_seconds=float(window_span),
            base_volume_per_second=per_second,
            baseline_per_second=baseline_per_second,
            rvol=rvol,
            direction=direction,
            price_change_pct=change_pct,
            price=price,
            timestamp_ms=timestamp_ms,
            suspect=suspect,
            illiquid=illiquid,
            baseline_notional_per_second=baseline_notional,
        )


def candle_rvol(
    volumes: list[float],
    lookback: int = 20,
) -> float:
    """Mum ölçeğinde RVOL: son mum hacmi / önceki `lookback` mum ortalaması.

    Canlı 5m kapanışı ve backtest AYNI fonksiyonu kullanır; pay ve payda
    aynı mum periyodunda olduğu için birim hatası yapısal olarak imkânsızdır.
    """
    if not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback pozitif tam sayı olmalı")
    if len(volumes) < lookback + 1:
        return 0.0
    baseline = volumes[-lookback - 1:-1]
    avg = sum(baseline) / float(lookback)
    if avg <= 0:
        return 0.0
    return volumes[-1] / avg


def estimate_secondly_base_volume(
    quote_volume_24h_delta: float,
    price: float,
    contract_size: float = 1.0,
) -> float:
    """Borsa ticker hacim deltasını saniyelik BAZ hacme çevirir.

    Birim doğrulama katmanı (Yorum 2 operasyonel madde: "OKX kontrat birimi
    ile Binance baz hacmi aynı formüle girmemeli"):
      - Binance USDT-M: 1 kontrat = 1 baz varlık → çarpan 1.0
      - OKX: kontrat sayısı x sözleşme büyüklüğü (ör. 0.01) → çarpan o değer
    `quote_volume_24h_delta`: bir saniyedeki 24s gösterge hacim farkı (quote).
    """
    if not isfinite(quote_volume_24h_delta) or quote_volume_24h_delta < 0:
        raise ValueError("hacim deltası sonlu ve negatif olmalı")
    if not isfinite(price) or price <= 0:
        raise ValueError("fiyat pozitif ve sonlu olmalı")
    if not isfinite(contract_size) or contract_size <= 0:
        raise ValueError("kontrat büyüklüğü pozitif olmalı")
    return (quote_volume_24h_delta / price) * contract_size
