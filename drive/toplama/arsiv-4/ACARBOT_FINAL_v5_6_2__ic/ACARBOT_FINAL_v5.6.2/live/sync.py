"""ACARBOT v3.0 — Emir idempotency, pozisyon mutabakatı, restart kurtarma.

Şartname madde 9 gereksinimleri:
  - Emir gönderiminde idempotency: aynı sinyal için aynı clientOrderId →
    borsa ikinci emri reddeder/tekilleştirir; yerel kayıt da tekrar gönderimi
    engeller.
  - Gerçek pozisyonları borsayla karşılaştırma: sembol/yön/miktar sapması
    raporlanır; `adopt_exchange_on_drift` açıksa uyarı ile birlikte borsa
    doğrusu kabul edilir (varsayılan: yalnızca rapor + alert).
  - Restart sonrası kurtarma: borsadaki açık emirler taranır, bayat giriş
    emirleri (max_order_age_s) İPTAL edilir; koruyucu stopu olmayan her
    pozisyon için sunucu tarafı stop kurulur.

v3.0 düzeltmeleri (dış inceleme bulguları):
  - LiveMirror artık Binance VE OKX ile çalışır (OKX'te tam emir eşlemesi;
    conditional algo stop dahil). Eski "OKX eşleme uygulanmadı" kısıtı
    kaldırıldı.
  - Giriş dolup koruyucu stop kurulamazsa: 3 deneme → başarısızsa pozisyon
    reduce-only market ile KAPATILIR. Korumasız pozisyon bırakılmaz.
  - mirror_stop_update: paper tarafındaki break-even/trailing/TP1 stop
    değişimleri borsadaki stop emrine YANSITILIR (eski stop iptal + yeni
    stop; yeni kurulamazsa eski stop geri konur).
  - Stop/kapanış sonrası kalan koruyucu stoplar iptal edilir.
  - Mirror durumu (gönderilen anahtarlar + stop fiyatları) isteğe bağlı
    state_saver/state_loader ile SQLite'a yazılır → restart sonrası çift
    emir ve kayıp stop olmaz.
  - EmergencyController: OKX çıkış yönü düzeltildi (LONG → sell) ve
    pozisyon başına hata izolasyonu geldi (tek hata tüm akışı kesmez).
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from live.broker_clients import (
    BinanceFuturesTestnet,
    ExchangeOrder,
    ExchangePosition,
    OkxDemoTrading,
)

logger = logging.getLogger(__name__)


class ExchangeAdapter(Protocol):
    """BinanceFuturesTestnet / OkxDemoTrading ortak yüzeyi (mutabakat için)."""

    def fetch_positions(self) -> list[ExchangePosition]: ...

    def fetch_open_orders(self) -> list[ExchangeOrder]: ...


# ---------------------------------------------------------------------------
# Idempotent emir kimlikleri
# ---------------------------------------------------------------------------

class IdempotentOrderIdFactory:
    """Deterministik clientOrderId üretir ve tekrar gönderimi engeller.

    id = ACB2-<sha1(symbol|side|signal_key)[:10]>
    Aynı (symbol, side, signal_key) tekrar üretilirse aynı id döner →
    borsa tarafında tekillik + yerel kayıtta mükerrer gönderim engeli.
    """

    def __init__(self) -> None:
        self._issued: set[str] = set()

    def order_id(self, symbol: str, side: str, signal_key: str) -> str:
        raw = f"{symbol}|{side}|{signal_key}"
        digest = hashlib.sha1(raw.encode()).hexdigest()[:10].upper()
        client_id = f"ACB2-{digest}"
        self._issued.add(client_id)
        return client_id

    def was_issued(self, client_id: str) -> bool:
        return client_id in self._issued


# ---------------------------------------------------------------------------
# Pozisyon mutabakatı
# ---------------------------------------------------------------------------

@dataclass
class DriftReport:
    matched: list[str] = field(default_factory=list)
    local_only: list[str] = field(default_factory=list)
    exchange_only: list[str] = field(default_factory=list)
    quantity_drift: list[dict] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.local_only or self.exchange_only or self.quantity_drift)

    def as_dict(self) -> dict:
        return {
            "matched": self.matched,
            "local_only": self.local_only,
            "exchange_only": self.exchange_only,
            "quantity_drift": self.quantity_drift,
            "has_drift": self.has_drift,
        }


class PositionReconciler:
    """Yerel paper/pozisyon tablosu ↔ borsa pozisyonları karşılaştırması."""

    def __init__(self, tolerance_qty: float = 1e-6) -> None:
        self.tolerance_qty = tolerance_qty

    def reconcile(
        self,
        local_positions: dict[str, tuple[str, float]],  # symbol → (side, qty)
        exchange_positions: list[ExchangePosition],
    ) -> DriftReport:
        report = DriftReport()
        exchange_by_symbol: dict[str, ExchangePosition] = {
            p.symbol: p for p in exchange_positions
        }
        for symbol, (side, qty) in local_positions.items():
            exchange = exchange_by_symbol.get(symbol)
            if exchange is None:
                report.local_only.append(symbol)
                continue
            if exchange.side != side:
                report.quantity_drift.append({
                    "symbol": symbol, "kind": "side_mismatch",
                    "local": side, "exchange": exchange.side,
                })
            elif abs(exchange.quantity - qty) > self.tolerance_qty:
                report.quantity_drift.append({
                    "symbol": symbol, "kind": "qty_mismatch",
                    "local": round(qty, 8),
                    "exchange": round(exchange.quantity, 8),
                })
            else:
                report.matched.append(symbol)
        for symbol in exchange_by_symbol:
            if symbol not in local_positions:
                report.exchange_only.append(symbol)
        return report


# ---------------------------------------------------------------------------
# Restart sonrası kurtarma
# ---------------------------------------------------------------------------

@dataclass
class RecoveryReport:
    canceled_stale_orders: list[str] = field(default_factory=list)
    stops_restored: list[str] = field(default_factory=list)
    stops_already_present: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "canceled_stale_orders": self.canceled_stale_orders,
            "stops_restored": self.stops_restored,
            "stops_already_present": self.stops_already_present,
            "notes": self.notes,
        }


class RestartRecovery:
    """Yeniden başlatmada borsa tarafını güvenli duruma getirir.

    1. Bayat giriş emirleri iptal edilir (reduce-only olmayan ve yaşı
       max_order_age_s'yi aşan her emir).
    2. Koruyucu stopu olmayan pozisyonlara sunucu tarafı stop kurulur
       (Binance: STOP_MARKET closePosition=true; OKX: conditional algo
       closeFraction=1 — v3.0).
    """

    def __init__(
        self,
        binance: "BinanceFuturesTestnet | None" = None,
        okx: "OkxDemoTrading | None" = None,
        max_order_age_s: float = 120.0,
        clock=None,
    ) -> None:
        self.binance = binance
        self.okx = okx
        self.max_order_age_s = max_order_age_s
        self.clock = clock or (lambda: int(time.time() * 1000))

    def recover_binance(self, stop_prices: dict[str, float]) -> RecoveryReport:
        report = RecoveryReport()
        if self.binance is None:
            report.notes.append("binance istemcisi yok")
            return report
        now_ms = self.clock()
        for order in self.binance.fetch_open_orders():
            age_s = (now_ms - order.updated_ms) / 1000.0
            if not order.reduce_only and age_s > self.max_order_age_s:
                try:
                    self.binance.cancel_all_orders(order.symbol)
                    report.canceled_stale_orders.append(order.symbol)
                except Exception as exc:  # noqa: BLE001
                    report.notes.append(f"iptal hatası {order.symbol}: {exc}")
        protected_symbols = {
            o.symbol for o in self.binance.fetch_open_orders() if o.reduce_only
        }
        for position in self.binance.fetch_positions():
            if position.symbol in protected_symbols:
                report.stops_already_present.append(position.symbol)
                continue
            stop_price = stop_prices.get(position.symbol)
            if stop_price is None:
                report.notes.append(
                    f"koruyucu stop kurulamadı ({position.symbol}): stop fiyatı yok"
                )
                continue
            try:
                self.binance.place_protective_stop(
                    position.symbol, position.side, stop_price,
                    f"ACB2-RST-{hashlib.sha1(position.symbol.encode()).hexdigest()[:8]}",
                )
                report.stops_restored.append(position.symbol)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"stop kurma hatası {position.symbol}: {exc}")
        return report

    def recover_okx(self, stop_prices: dict[str, float]) -> RecoveryReport:
        """v3.0: OKX demo kurtarma (bayat emir iptali + conditional stop)."""
        report = RecoveryReport()
        if self.okx is None:
            report.notes.append("okx istemcisi yok")
            return report
        now_ms = self.clock()
        for order in self.okx.fetch_open_orders():
            age_s = (now_ms - order.updated_ms) / 1000.0
            if not order.reduce_only and age_s > self.max_order_age_s:
                try:
                    self.okx.cancel_all_orders(order.symbol)
                    report.canceled_stale_orders.append(order.symbol)
                except Exception as exc:  # noqa: BLE001
                    report.notes.append(f"iptal hatası {order.symbol}: {exc}")
        protected_symbols = {
            o.symbol for o in self.okx.fetch_open_orders() if o.reduce_only
        }
        for position in self.okx.fetch_positions():
            if position.symbol in protected_symbols:
                report.stops_already_present.append(position.symbol)
                continue
            stop_price = stop_prices.get(position.symbol)
            if stop_price is None:
                report.notes.append(
                    f"koruyucu stop kurulamadı ({position.symbol}): stop fiyatı yok"
                )
                continue
            try:
                self.okx.place_protective_stop(
                    position.symbol, position.side, stop_price,
                    f"ACB2RST{hashlib.sha1(position.symbol.encode()).hexdigest()[:8]}",
                )
                report.stops_restored.append(position.symbol)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"stop kurma hatası {position.symbol}: {exc}")
        return report


# ---------------------------------------------------------------------------
# Canlı eşleme (paper kararlarının testnet/demo'ya yansıtılması)
# ---------------------------------------------------------------------------

_STOP_RETRY_LIMIT = 3


class LiveMirror:
    """Paper kararı → testnet/demo emri eşlemesi (gözetimli yarı-canlı).

    v3.0:
      - Binance VE OKX (tam eşleme: giriş + koruyucu stop + stop güncelleme
        + reduce-only çıkış).
      - Stop kurulamazsa pozisyon KORUMASIZ KALMAZ: 3 deneme sonrası
        pozisyon reduce-only kapatılır ve CRITICAL loglanır.
      - Durum kalıcılığı: state_saver/state_loader verilirse gönderilen
        anahtarlar ve stop fiyatları SQLite'a yazılır.
    v4.0:
      - Post-only maker giriş (varsayılan): post-only LIMIT doldurulmaya
        çalışılır (Binance GTX / OKX ordType=post_only); TTL'de dolmadıysa
        veya borsa reddederse "post_only_market_fallback" modunda MARKET
        yedek gönderilir (yüksek sesle loglanır). "post_only" saf modda
        eşleme ATLANIR (borsada pozisyon oluşmaz — mutabakat local_only
        raporlar; paper pozisyonu etkilenmez). "market" = v3.0 davranışı.
      - mirror_dca: DCA güvenlik emri borsaya market ek giriş olarak
        yansıtılır; koruyucu stop (closePosition) tüm pozisyonu kapsar.
    """

    def __init__(
        self,
        binance: "BinanceFuturesTestnet | None" = None,
        okx: "OkxDemoTrading | None" = None,
        state_saver: "Callable[[dict], None] | None" = None,
        state_loader: "Callable[[], dict] | None" = None,
        margin_mode: str = "isolated",
        leverage: int = 10,
        entry_style: str = "post_only_market_fallback",
        entry_fill_timeout_s: float = 60.0,
        poll_interval_s: float = 1.0,
        clock=None,
        sleeper=time.sleep,
        entry_timeframe: str = "",
        live_cfg=None,
    ) -> None:
        # v5.6: kenar kanıtı olmayan zaman diliminde canlı giriş YASAK.
        # live_cfg verilmezse kapı KAPALI davranır (güvenli varsayılan).
        self.entry_timeframe = entry_timeframe
        self.live_cfg = live_cfg
        if binance is None and okx is None:
            raise ValueError("LiveMirror: binance veya okx istemcisi gerekli")
        self.binance = binance
        self.okx = okx
        self.margin_mode = margin_mode
        self.leverage = leverage
        if entry_style not in (
            "post_only", "post_only_market_fallback", "market",
        ):
            raise ValueError(f"bilinmeyen entry_style: {entry_style}")
        self.entry_style = entry_style
        self.entry_fill_timeout_s = max(float(entry_fill_timeout_s), 1.0)
        self.poll_interval_s = max(float(poll_interval_s), 0.05)
        self.clock = clock or (lambda: int(time.time() * 1000))
        self._sleeper = sleeper
        self.ids = IdempotentOrderIdFactory()
        self.sent_entry_keys: set[str] = set()
        self.sent_exit_keys: set[str] = set()
        self.stop_prices: dict[str, float] = {}
        self.stop_client_ids: dict[str, str] = {}
        self._setup_done: set[str] = set()
        self.errors: list[str] = []
        self.unprotected_flattened: list[str] = []
        self.entry_skipped: list[str] = []   # v4.0: saf post-only eşleme atlananlar
        self.entry_fallbacks: list[str] = []  # v4.0: post-only → MARKET yedekler
        self._state_saver = state_saver
        if state_loader is not None:
            try:
                saved = state_loader() or {}
                self.sent_entry_keys |= set(saved.get("sent_entry_keys", []))
                self.sent_exit_keys |= set(saved.get("sent_exit_keys", []))
                self.stop_prices.update(saved.get("stop_prices", {}))
                self.stop_client_ids.update(saved.get("stop_client_ids", {}))
            except Exception as exc:  # noqa: BLE001
                logger.warning("mirror durumu yüklenemedi: %s", exc)

    # -- Durum kalıcılığı ----------------------------------------------------

    def snapshot_state(self) -> dict:
        return {
            "sent_entry_keys": sorted(self.sent_entry_keys),
            "sent_exit_keys": sorted(self.sent_exit_keys),
            "stop_prices": dict(self.stop_prices),
            "stop_client_ids": dict(self.stop_client_ids),
        }

    def _save(self) -> None:
        if self._state_saver is None:
            return
        try:
            self._state_saver(self.snapshot_state())
        except Exception as exc:  # noqa: BLE001
            logger.warning("mirror durumu kaydedilemedi: %s", exc)

    # -- Yardımcılar -----------------------------------------------------------

    def _place_stop(
        self, symbol: str, side: str, stop_loss: float, client_id: str,
    ) -> None:
        if self.binance is not None:
            self.binance.place_protective_stop(symbol, side, stop_loss, client_id)
        else:
            self.okx.place_protective_stop(symbol, side, stop_loss, client_id)

    def _cancel_stop(self, symbol: str) -> None:
        """Mevcut koruyucu stopu iptal eder (best effort)."""
        client_id = self.stop_client_ids.get(symbol)
        if not client_id:
            return
        try:
            if self.binance is not None:
                self.binance.cancel_order_by_client_id(symbol, client_id)
            else:
                for order in self.okx.fetch_open_orders(symbol):
                    if order.client_order_id == client_id and order.order_id:
                        self.okx.cancel_algo_stop(symbol, order.order_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("eski stop iptal edilemedi (%s): %s", symbol, exc)

    def _flatten(self, symbol: str, side: str, quantity: float, why: str) -> None:
        """Koruyucu stop kurulamayan pozisyonu reduce-only kapatır."""
        client_id = self.ids.order_id(symbol, side, f"flatten:{why}")
        try:
            if self.binance is not None:
                self.binance.place_reduce_only_exit(
                    symbol, side, quantity, client_id,
                )
            else:
                self.okx.place_reduce_only_exit(
                    symbol, side, quantity, client_id,
                )
            self.unprotected_flattened.append(symbol)
            logger.error(
                "KRİTİK: %s pozisyonu için koruyucu stop kurulamadı (%s) — "
                "pozisyon reduce-only KAPATILDI (korumasız bırakılmadı)",
                symbol, why,
            )
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"flatten {symbol}: {exc}")
            logger.critical(
                "KRİTİK: %s stop kurulamadı VE kapatılamadı: %s — ELLE MÜDAHALE!",
                symbol, exc,
            )

    # -- Eşleme ---------------------------------------------------------------

    def _ensure_setup(self, symbol: str) -> None:
        """v3.0: sembol başına tek seferlik kaldıraç/marj ayarı (best effort).

        Zaten bu modda olma hatası (-4046) transport gövde okuması sayesinde
        sessizce geçilir; diğer hatalar kayda geçer ama girişi engellemez
        (borsa varsayılanıyla çalışır).
        """
        if symbol in self._setup_done or self.binance is None:
            return
        try:
            self.binance.set_leverage(symbol, int(self.leverage))
            self.binance.set_margin_type(symbol, self.margin_mode)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"setup {symbol}: {exc}")
        finally:
            self._setup_done.add(symbol)

    # -- v4.0: giriş yürütücüleri --------------------------------------------

    def _market_entry(self, symbol: str, side: str, quantity: float,
                      client_id: str) -> ExchangeOrder:
        if self.binance is not None:
            return self.binance.place_entry(symbol, side, quantity, client_id)
        return self.okx.place_market(symbol, side, quantity, client_id)

    def _post_only_entry(self, symbol: str, side: str, quantity: float,
                         client_id: str, limit_price: float) -> ExchangeOrder:
        if self.binance is not None:
            return self.binance.place_entry(
                symbol, side, quantity, client_id,
                market=False, price=limit_price,
            )
        return self.okx.place_post_only(
            symbol, side, quantity, limit_price, client_id,
        )

    def _fetch_open_orders(self, symbol: str) -> list[ExchangeOrder]:
        try:
            if self.binance is not None:
                return self.binance.fetch_open_orders(symbol)
            return self.okx.fetch_open_orders(symbol)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"open-orders {symbol}: {exc}")
            return []

    def _cancel_entry_order(self, symbol: str, client_id: str) -> None:
        if self.binance is not None:
            self.binance.cancel_order_by_client_id(symbol, client_id)
        else:
            self.okx.cancel_order(symbol, client_id)

    def _wait_for_fill(self, symbol: str, client_id: str) -> bool:
        """Post-only emri dolumunu yoklar (açık emir listesinden düşene dek)."""
        deadline = self.clock() + int(self.entry_fill_timeout_s * 1000)
        while self.clock() < deadline:
            open_orders = self._fetch_open_orders(symbol)
            if not any(o.client_order_id == client_id for o in open_orders):
                return True  # listeden düştü → doldu (GTX reddi zaten istisna)
            self._sleeper(self.poll_interval_s)
        return False

    def _execute_entry(
        self, symbol: str, side: str, quantity: float, client_id: str,
        limit_price: float | None,
    ) -> ExchangeOrder | None:
        """Giriş emrini entry_style'a göre yürütür; None = eşleme atlandı."""
        if self.entry_style == "market" or limit_price is None or limit_price <= 0:
            if self.entry_style != "market":
                logger.warning(
                    "EŞLEME: post-only için limit fiyatı yok (%s) → MARKET",
                    symbol,
                )
            return self._market_entry(symbol, side, quantity, client_id)
        try:
            order = self._post_only_entry(
                symbol, side, quantity, client_id, limit_price,
            )
        except Exception as exc:  # noqa: BLE001
            if self.entry_style == "post_only_market_fallback":
                self.entry_fallbacks.append(symbol)
                logger.warning(
                    "EŞLEME: post-only reddedildi (%s: %s) → MARKET yedek",
                    symbol, exc,
                )
                return self._market_entry(
                    symbol, side, quantity, client_id + "M",
                )
            self.errors.append(f"post-only {symbol}: {exc}")
            self.entry_skipped.append(symbol)
            logger.warning(
                "EŞLEME: post-only reddedildi (%s: %s) — saf maker modunda "
                "eşleme atlandı (borsada pozisyon oluşmadı)", symbol, exc,
            )
            return None
        if self._wait_for_fill(symbol, client_id):
            return order
        # TTL doldu: emri iptal et; kalan miktar için karar ver
        executed = 0.0
        if self.binance is not None:
            state = self.binance.fetch_order_by_client_id(symbol, client_id)
            if state is not None:
                executed = state.executed_quantity
        try:
            self._cancel_entry_order(symbol, client_id)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"post-only iptal {symbol}: {exc}")
        remaining = quantity - max(executed, 0.0)
        if remaining <= max(quantity * 1e-6, 1e-12):
            return order  # fiilen tam dolum
        if self.entry_style == "post_only_market_fallback":
            self.entry_fallbacks.append(symbol)
            logger.warning(
                "EŞLEME: post-only %.0f sn'de dolmadı (%s; dolan %.6g) → "
                "kalan %.6g MARKET yedek",
                self.entry_fill_timeout_s, symbol, executed, remaining,
            )
            return self._market_entry(
                symbol, side, remaining, client_id + "M",
            )
        self.entry_skipped.append(symbol)
        logger.warning(
            "EŞLEME: post-only dolmadı ve saf maker modunda yedek YOK "
            "(%s; dolan %.6g) — borsa tarafı eşleme atlandı; paper pozisyonu "
            "etkilenmez, mutabakat local_only raporlar",
            symbol, executed,
        )
        return None

    def mirror_open(
        self, symbol: str, side: str, quantity: float,
        stop_loss: float, signal_key: str,
        limit_price: float | None = None,
    ) -> list[str]:
        actions: list[str] = []
        key = f"open:{symbol}:{side}:{signal_key}"
        if key in self.sent_entry_keys:
            return actions
        # v5.6: canlı giriş zaman dilimi kapısı
        from core.gates import canli_giris_izinli
        if self.live_cfg is not None:
            izinli, neden = canli_giris_izinli(self.entry_timeframe, self.live_cfg)
            if not izinli:
                self.entry_skipped.append(symbol)
                logger.error("EŞLEME REDDEDİLDİ (%s): %s", symbol, neden)
                return actions
        self._ensure_setup(symbol)
        client_id = self.ids.order_id(symbol, side, signal_key)
        try:
            order = self._execute_entry(
                symbol, side, quantity, client_id, limit_price,
            )
            if order is None:
                # v4.0: eşleme atlandı → stop da kurulmaz; paper sürer.
                self._save()
                return actions
            self.sent_entry_keys.add(key)
            actions.append(f"entry:{client_id}")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"entry {symbol}: {exc}")
            return actions
        stop_id = self.ids.order_id(symbol, side, f"stop:{signal_key}")
        placed = False
        for attempt in range(1, _STOP_RETRY_LIMIT + 1):
            try:
                self._place_stop(symbol, side, stop_loss, stop_id)
                self.stop_prices[symbol] = stop_loss
                self.stop_client_ids[symbol] = stop_id
                placed = True
                actions.append(f"stop:{stop_id}" + (f":deneme{attempt}" if attempt > 1 else ""))
                break
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"stop {symbol} deneme {attempt}: {exc}")
        if not placed:
            # v3.0: korumasız pozisyon YOK — girişi geri al.
            self._flatten(symbol, side, quantity, "stop_kurulamadi")
        self._save()
        return actions

    def mirror_dca(
        self, symbol: str, side: str, quantity: float, signal_key: str,
    ) -> list[str]:
        """v4.0: DCA güvenlik emrini borsaya yansıtır (market ek giriş).

        Koruyucu stop closePosition=true / closeFraction=1 olduğu için
        tüm pozisyonu kapsar — yeni stop GEREKMEZ. signal_key = paper DCA
        kaydının order_id'si (dca-<anahtar>-<n>) → idempotent.
        """
        actions: list[str] = []
        key = f"dca:{symbol}:{side}:{signal_key}"
        if key in self.sent_entry_keys:
            return actions
        self._ensure_setup(symbol)
        client_id = self.ids.order_id(symbol, side, f"dca:{signal_key}")
        try:
            self._market_entry(symbol, side, quantity, client_id)
            self.sent_entry_keys.add(key)
            actions.append(f"dca-entry:{client_id}")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"dca {symbol}: {exc}")
        self._save()
        return actions

    def mirror_stop_update(
        self, symbol: str, side: str, new_stop: float, signal_key: str,
    ) -> list[str]:
        """Paper stop değişimini (break-even/trailing/TP1) borsaya yansıtır.

        Eski stop iptal → yeni stop kurulur. Yeni stop kurulamazsa ESKİ
        stop geri konmaya çalışılır; o da başarısızsa pozisyon kapatılır.
        """
        actions: list[str] = []
        old_stop = self.stop_prices.get(symbol)
        if old_stop is not None and abs(old_stop - new_stop) < 1e-12:
            return actions  # değişiklik yok
        self._cancel_stop(symbol)
        stop_id = self.ids.order_id(symbol, side, f"stopu:{signal_key}")
        try:
            self._place_stop(symbol, side, new_stop, stop_id)
            self.stop_prices[symbol] = new_stop
            self.stop_client_ids[symbol] = stop_id
            actions.append(f"stop-update:{stop_id}")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"stop-update {symbol}: {exc}")
            restored = False
            if old_stop is not None:
                try:
                    self._place_stop(symbol, side, old_stop, stop_id)
                    restored = True
                    actions.append(f"stop-geri-alindi:{stop_id}")
                except Exception as exc2:  # noqa: BLE001
                    self.errors.append(f"stop-geri-alma {symbol}: {exc2}")
            if not restored:
                self._flatten(symbol, side, 0.0, "stop_guncellenemedi")
        self._save()
        return actions

    def mirror_close(
        self, symbol: str, side: str, quantity: float, signal_key: str,
    ) -> list[str]:
        actions: list[str] = []
        key = f"close:{symbol}:{side}:{signal_key}"
        if key in self.sent_exit_keys:
            return actions
        client_id = self.ids.order_id(symbol, side, f"exit:{signal_key}")
        try:
            if self.binance is not None:
                self.binance.place_reduce_only_exit(
                    symbol, side, quantity, client_id,
                )
            else:
                self.okx.place_reduce_only_exit(
                    symbol, side, quantity, client_id,
                )
            self.sent_exit_keys.add(key)
            actions.append(f"exit:{client_id}")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"exit {symbol}: {exc}")
            return actions
        # v3.0: kapanış sonrası kalan koruyucu stopu temizle.
        self._cancel_stop(symbol)
        self.stop_prices.pop(symbol, None)
        self.stop_client_ids.pop(symbol, None)
        self._save()
        return actions


# ---------------------------------------------------------------------------
# Acil durum
# ---------------------------------------------------------------------------

class EmergencyController:
    """Acil durum: TÜM emirleri iptal + TÜM pozisyonları reduce-only kapat.

    v3.0: pozisyon başına hata izolasyonu (tek sembol hatası diğerlerinin
    kapatılmasını engellemez) + OKX çıkış yönü düzeltmesi
    (place_reduce_only_exit: LONG → sell). Hem Binance testnet hem OKX demo
    için çalışır; sonrasında yerel HARD_HALT callback'i çağrılır.
    """

    def __init__(
        self,
        binance: "BinanceFuturesTestnet | None" = None,
        okx: "OkxDemoTrading | None" = None,
        on_halt=None,
    ) -> None:
        self.binance = binance
        self.okx = okx
        self.on_halt = on_halt
        self.triggered = False

    def trigger(self, reason: str = "manual") -> dict:
        self.triggered = True
        result: dict[str, object] = {"reason": reason, "actions": [], "errors": []}
        if self.binance is not None:
            positions = []
            try:
                positions = self.binance.fetch_positions()
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"pozisyon sorgusu: {exc}")
            for position in positions:
                tag = hashlib.sha1(
                    (position.symbol + reason).encode()
                ).hexdigest()[:8]
                try:
                    self.binance.cancel_all_orders(position.symbol)
                    result["actions"].append(f"cancel:{position.symbol}")
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"cancel {position.symbol}: {exc}")
                try:
                    self.binance.place_reduce_only_exit(
                        position.symbol, position.side, position.quantity,
                        f"ACB2-EMG-{tag}",
                    )
                    result["actions"].append(f"flatten:{position.symbol}")
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"flatten {position.symbol}: {exc}")
        if self.okx is not None:
            positions = []
            try:
                positions = self.okx.fetch_positions()
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"pozisyon sorgusu: {exc}")
            for position in positions:
                tag = hashlib.sha1(
                    (position.symbol + reason).encode()
                ).hexdigest()[:8]
                try:
                    self.okx.cancel_all_orders(position.symbol)
                    result["actions"].append(f"cancel:{position.symbol}")
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"cancel {position.symbol}: {exc}")
                try:
                    # v3.0: doğru ters yön (LONG → sell, SHORT → buy)
                    self.okx.place_reduce_only_exit(
                        position.symbol, position.side, position.quantity,
                        f"ACB2EMG{tag}",
                    )
                    result["actions"].append(f"flatten:{position.symbol}")
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"flatten {position.symbol}: {exc}")
        if callable(self.on_halt):
            try:
                self.on_halt(reason)
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"halt_cb: {exc}")
        logger.error("ACİL DURUM: %s | %s", reason, result)
        return result
