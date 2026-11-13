"""Paper aggTrade hacim kaynağı; stale olaylar düşürülür, geçmiş korunur.

Bir stale/out-of-order paket tek başına önceki geçerli geçmişi geçersiz kılmaz:
paket yok sayılır ve ölçülür. Gerçek bağlantı/ID boşluğunda yalnız canlı hacim
penceresi ve tamamlanmamış dakika atılır; 60 dakikalık kapanmış gösterge mumları
korunur. Eksik/taze olmayan hacim pencerelerinde sinyal fail-closed kalır.
"""
import asyncio
import math
import time
from collections import Counter

from scanner.ind_aktif import aggtrade_ekle


class BinanceAggTradeInput:
    def __init__(self, detector, on_signal):
        self.detector = detector
        self.on_signal = on_signal
        self.connected = set()
        self.ever = set()
        self.acc = {}
        self.last_sample = {}
        self.last_ts = {}
        self.last_arrival = {}
        self.invalid = 0
        self.stale = 0
        self.resets = 0
        self.accepted = 0
        self.signal_errors = 0
        self.tasks = set()
        self.sessizlik_sayisi = 0
        self.sessizlik_max_ms = 0
        self.stale_reasons = Counter()
        self.stale_by_symbol = Counter()
        self.stale_age_buckets = Counter()
        self.stale_age_max_ms = 0
        self.stale_future_max_ms = 0
        self.reset_reasons = Counter()
        self.partial_resets = 0
        self.partial_reset_reasons = Counter()

    def reset(self, symbol, clear_history=False, reason="explicit"):
        """Tam reset; stale paket ve taşıma timeout'u bu yolu kullanmaz."""
        d = self.detector.durum("binance", symbol)
        d.kaynak = "aggtrade"
        d.hacimler.clear()
        d.hiz_kisa = d.hiz_uzun = d.rvol = 0.0
        d.son_hacim_ts = 0
        d.dakika_id = -1
        d.dakika_qv = 0.0
        d.tamamlanan_qv = 0.0
        d._volume_full_warmup_ms = 120_000
        for name in ("_kum_onceki", "_kum_dk", "_kum_birikim"):
            if hasattr(d, name):
                delattr(d, name)
        if clear_history:
            d.dakika_kapanis.clear()
            d.dakika_hacim.clear()
            d.baglam_hazir = False
            if hasattr(d, "ind_mum"):
                d.ind_mum.clear()
                d.ind_acik_mum = None
            d.baglam_ret = d.baglam_vratio = d.baglam_vratio3 = 0.0
        for dic in (self.acc, self.last_sample, self.last_ts, self.last_arrival):
            dic.pop(symbol, None)
        self.resets += 1
        self.reset_reasons[reason] += 1

    def _partial_gap(self, symbol, reason):
        """Akış boşluğunda yalnız canlı pencereleri yeniden ısıt; kapalı mumları tut."""
        d = self.detector.durum("binance", symbol)
        d.kaynak = "aggtrade"
        d.hacimler.clear()
        d.hiz_kisa = d.hiz_uzun = d.rvol = 0.0
        d.son_hacim_ts = 0
        d.dakika_id = -1
        d.dakika_qv = 0.0
        d.tamamlanan_qv = 0.0
        d._volume_full_warmup_ms = 120_000
        # Geçmiş dakika bağlamı ve ind_mum korunur. Yarım canlı mum ise bağlantı
        # boşluğunu kapsayabileceği için kapatılmaz/ind_mum'a eklenmez.
        if hasattr(d, "ind_acik_mum"):
            d.ind_acik_mum = None
        d.baglam_hazir = False
        for name in ("_kum_onceki", "_kum_dk", "_kum_birikim"):
            if hasattr(d, name):
                delattr(d, name)
        for dic in (self.acc, self.last_sample, self.last_ts, self.last_arrival):
            dic.pop(symbol, None)
        self.partial_resets += 1
        self.partial_reset_reasons[reason] += 1

    def connection(self, symbols, up):
        for symbol in symbols:
            if up:
                if symbol not in self.ever:
                    # İlk bağlantı: REST ön-dolgulu tamamlanmış gösterge mumları
                    # korunur; yalnız canlı hacim penceresi başlatılır.
                    self._partial_gap(symbol, "initial_connect")
                    self.ever.add(symbol)
                self.connected.add(symbol)
            else:
                if symbol in self.connected:
                    self.connected.discard(symbol)
                    self._partial_gap(symbol, "connection_down")

    def connection_gap(self, symbol, reason="aggregate_id_gap"):
        """ID boşluğu gibi taşınan veri kopukluğunu bağlantıyı düşürmeden işle."""
        if symbol in self.connected:
            self._partial_gap(symbol, reason)

    @staticmethod
    def _age_bucket(age_ms):
        if age_ms < -2_000:
            return "gelecek_2sn_ustu"
        if age_ms < 0:
            return "gelecek_0_2sn"
        if age_ms <= 5_000:
            return "siradisi_0_5sn"
        if age_ms <= 10_000:
            return "bayat_5_10sn"
        if age_ms <= 30_000:
            return "bayat_10_30sn"
        if age_ms <= 60_000:
            return "bayat_30_60sn"
        return "bayat_60sn_ustu"

    def _record_stale(self, symbol, ts, now, last_ts):
        age_ms = now - ts
        if ts > now + 2_000:
            reason = "future_2sn_ustu"
            self.stale_future_max_ms = max(self.stale_future_max_ms, ts - now)
        elif age_ms > 5_000:
            reason = "gecikmis_5sn_ustu"
            self.stale_age_max_ms = max(self.stale_age_max_ms, age_ms)
        else:
            reason = "sira_disi"
        self.stale += 1
        self.stale_reasons[reason] += 1
        self.stale_by_symbol[symbol] += 1
        self.stale_age_buckets[self._age_bucket(age_ms)] += 1

    def stale_summary(self, limit=10):
        return {
            "neden": dict(self.stale_reasons),
            "yas_dagilimi": dict(self.stale_age_buckets),
            "azami_gecikme_ms": self.stale_age_max_ms,
            "azami_gelecek_ms": self.stale_future_max_ms,
            "sembol_ilkleri": [
                {"symbol": symbol, "count": count}
                for symbol, count in self.stale_by_symbol.most_common(limit)
            ],
        }

    def partial_reset_summary(self):
        return {
            "adet": self.partial_resets,
            "neden": dict(self.partial_reset_reasons),
        }

    def reset_summary(self):
        return dict(self.reset_reasons)

    def trade(self, exchange, symbol, price, base, side, ts):
        if exchange != "binance" or symbol not in self.connected:
            return
        try:
            price = float(price)
            base = float(base)
            ts = int(ts)
        except (ValueError, TypeError, OverflowError):
            self.invalid += 1
            self.reset(symbol, clear_history=True, reason="invalid_parse")
            return
        now = int(time.time() * 1000)
        if not all(math.isfinite(x) and x > 0 for x in (price, base, price * base)) or side not in ("buy", "sell"):
            self.invalid += 1
            self.reset(symbol, clear_history=True, reason="invalid_value")
            return
        last_ts = self.last_ts.get(symbol, 0)
        if ts > now + 2_000 or now - ts > 5_000 or ts < last_ts:
            # Hatalı tek paketi yoksay: geçerli rolling geçmişe dokunma.
            self._record_stale(symbol, ts, now, last_ts)
            return

        # Sessizlik ayrı bir telemetri olayıdır; tek başına kopma kanıtı değildir.
        last = self.last_arrival.get(symbol)
        if last is not None and now - last > self.detector.tazelik_ms:
            self.sessizlik_sayisi += 1
            gap_ms = now - last
            if gap_ms > self.sessizlik_max_ms:
                self.sessizlik_max_ms = gap_ms
        self.last_ts[symbol] = ts
        self.last_arrival[symbol] = now
        self.acc[symbol] = self.acc.get(symbol, 0.0) + price * base
        self.accepted += 1
        if getattr(self.detector, "ind_aktif", False):
            aggtrade_ekle(self.detector.durum("binance", symbol), ts, price, base)
        if now // 1000 == self.last_sample.get(symbol):
            return
        self.last_sample[symbol] = now // 1000
        sig = self.detector.besle_hacim_kumulatif("binance", symbol, self.acc[symbol], now)
        if sig:
            task = asyncio.create_task(self.on_signal(sig))
            self.tasks.add(task)

            def finished(done):
                self.tasks.discard(done)
                if done.cancelled():
                    return
                if done.exception() is not None:
                    self.signal_errors += 1
                    self.connected.discard(symbol)
                    self.reset(symbol, clear_history=True, reason="signal_callback_error")

            task.add_done_callback(finished)
