"""
portfolio/paper_futures.py — PAPER vadeli işlem muhasebesi.

Temel kurallar (spec ile birebir):
  * Kaldıraç yalnızca qty_base'yi belirler: notional = margin * leverage.
    Kaldıraç PnL'e İKİNCİ KEZ çarpılmaz.
  * Giriş komisyonu marjla BİRLİKTE, tek adımda düşülür:
        balance -= (margin + entry_fee)
  * Çıkışta marj geri eklenir, çıkış komisyonu düşülür.
  * Pozisyon limitleri AÇILIŞ SONRASI duruma göre kontrol edilir.
  * Bakiye tabanı (100 USDT) korunur; bakiye negatife düşmez.
  * Günlük zarar limiti aşılırsa yeni pozisyon açılmaz.
  * Durum (exchange, symbol) ile anahtarlanır; borsalar asla birleştirilmez.

Funding: # ASSUMPTION: funding not fetched; result is funding-EXCLUDED.
         Outputs labeled 'funding hariç / bilinmiyor'.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

LONG = "LONG"
SHORT = "SHORT"

# ASSUMPTION: funding not fetched; result is funding-EXCLUDED.
# Outputs labeled 'funding hariç / bilinmiyor'. Alan varsayılan 0.0'dır ama
# bu "gerçekleşen funding sıfırdır" anlamına GELMEZ.
FUNDING_LABEL = "funding hariç / bilinmiyor"


@dataclass
class Position:
    """Açık paper pozisyonu."""

    exchange: str
    symbol: str
    side: str
    entry_price: float
    qty_base: float
    margin: float
    leverage: float
    entry_fee: float
    opened_at: int
    stop_price: float | None = None
    take_profit_price: float | None = None
    funding_fee: float = 0.0  # placeholder — gerçek funding DEĞİL
    last_price: float | None = None
    last_price_ts: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return (self.exchange, self.symbol)

    @property
    def notional(self) -> float:
        return self.qty_base * self.entry_price

    def unrealised_pnl(self, price: float) -> float:
        """Gerçekleşmemiş brüt PnL (komisyon hariç)."""
        if self.side == LONG:
            return (price - self.entry_price) * self.qty_base
        return (self.entry_price - price) * self.qty_base


@dataclass
class TradeRecord:
    """Kapanmış işlem kaydı."""

    exchange: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    qty_base: float
    margin: float
    leverage: float
    entry_fee: float
    exit_fee: float
    gross_pnl: float
    realized_pnl: float
    opened_at: int
    closed_at: int
    reason: str
    funding_fee: float = 0.0
    funding_label: str = FUNDING_LABEL

    @property
    def net_return_on_margin(self) -> float:
        return self.realized_pnl / self.margin if self.margin else 0.0


@dataclass
class OpenResult:
    """open_position sonucu."""

    ok: bool
    reason: str = ""
    position: Position | None = None
    checks: dict[str, object] = field(default_factory=dict)


class PaperPortfolio:
    """(exchange, symbol) anahtarlı paper portföy."""

    def __init__(
        self,
        starting_balance: float = 1_000.0,
        *,
        fee_rate: float = 0.0005,
        max_open_positions: int = 6,
        max_same_direction: int = 4,
        max_utilisation: float = 0.45,
        balance_floor: float = 100.0,
        daily_loss_limit_pct: float = 0.05,
        max_leverage: float = 20.0,
    ) -> None:
        if starting_balance <= balance_floor:
            raise ValueError("başlangıç bakiyesi bakiye tabanından büyük olmalı")
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self.fee_rate = float(fee_rate)
        self.max_open_positions = int(max_open_positions)
        self.max_same_direction = int(max_same_direction)
        self.max_utilisation = float(max_utilisation)
        self.balance_floor = float(balance_floor)
        self.daily_loss_limit_pct = float(daily_loss_limit_pct)
        self.max_leverage = float(max_leverage)

        self.positions: dict[tuple[str, str], Position] = {}
        self.closed_trades: list[TradeRecord] = []
        self.day_start_balance = float(starting_balance)
        self.blocked_new_positions = False

    # -- durum -------------------------------------------------------------
    @property
    def used_margin(self) -> float:
        return sum(p.margin for p in self.positions.values())

    @property
    def equity(self) -> float:
        """
        Hesap özsermayesi = bakiye + kilitli marj + gerçekleşmemiş PnL.

        NOT: Kilitli marj zarar DEĞİLDİR. Bakiye, pozisyon açılışında marj
        kadar azalır; günlük zarar limiti bu yüzden bakiye değil ÖZSERMAYE
        üzerinden ölçülür.
        """
        total = self.balance + self.used_margin
        for p in self.positions.values():
            price = p.last_price if p.last_price is not None else p.entry_price
            total += p.unrealised_pnl(price)
        return total

    def open_count(self) -> int:
        return len(self.positions)

    def same_direction_count(self, side: str, exchange: str | None = None) -> int:
        """
        Aynı yöndeki açık pozisyon sayısı.

        exchange verilirse sayım YALNIZCA o borsa için yapılır: Binance
        pozisyonları OKX'in aynı-yön kotasına SAYILMAZ (borsalar birleştirilmez).
        """
        return sum(
            1
            for p in self.positions.values()
            if p.side == side and (exchange is None or p.exchange == exchange)
        )

    def daily_pnl(self) -> float:
        """Gün başından beri özsermaye değişimi (kilitli marj zarar sayılmaz)."""
        return self.equity - self.day_start_balance

    def daily_loss_limit_hit(self) -> bool:
        if self.day_start_balance <= 0:
            return True
        return (self.daily_pnl() / self.day_start_balance) <= -self.daily_loss_limit_pct

    def reset_day(self) -> None:
        """Günlük zarar sayacını sıfırlar (gün başında çağrılır)."""
        self.day_start_balance = self.equity
        self.blocked_new_positions = False

    # -- pozisyon açma -----------------------------------------------------
    def open_position(
        self,
        exchange: str,
        symbol: str,
        side: str,
        price: float,
        margin: float,
        *,
        leverage: float = 5.0,
        step_size: float = 0.001,
        min_qty: float = 0.0,
        now_ms: int = 0,
        price_ts: int | None = None,
        poll_interval_ms: int = 60_000,
        stale_factor: float = 2.0,
        stop_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> OpenResult:
        """
        Paper pozisyon açar. Tüm kontroller AÇILIŞ SONRASI duruma göre yapılır.

        Returns:
            OpenResult(ok, reason, position, checks)
        """
        checks: dict[str, object] = {}
        if side not in (LONG, SHORT):
            return OpenResult(False, "geçersiz yön", checks=checks)
        if not (price > 0) or not math.isfinite(price):
            return OpenResult(False, "geçersiz fiyat", checks=checks)
        if not (margin > 0) or not math.isfinite(margin):
            return OpenResult(False, "geçersiz marj", checks=checks)
        if leverage <= 0 or leverage > self.max_leverage:
            return OpenResult(False, f"kaldıraç limiti ({leverage}>{self.max_leverage})", checks)

        key = (exchange, symbol)
        if key in self.positions:
            return OpenResult(False, "aynı sembolde açık pozisyon var", checks=checks)

        # --- bayat fiyat koruması ---
        if price_ts is not None and now_ms and poll_interval_ms:
            age = now_ms - int(price_ts)
            if age > stale_factor * poll_interval_ms:
                checks["stale_age_ms"] = age
                return OpenResult(False, "bayat fiyat (stale price)", checks=checks)

        # --- günlük zarar limiti ---
        if self.blocked_new_positions or self.daily_loss_limit_hit():
            return OpenResult(False, "günlük zarar limiti", checks=checks)

        # --- miktar: kaldıraç YALNIZCA burada kullanılır ---
        notional = margin * leverage
        raw_qty = notional / price
        if step_size <= 0:
            step_size = 0.00000001
        qty = math.floor(raw_qty / step_size) * step_size
        qty = round(qty, 12)
        if qty <= 0 or qty < min_qty:
            return OpenResult(
                False, f"miktar adımı çok büyük (qty={qty}, min={min_qty})", checks=checks
            )

        actual_notional = qty * price
        entry_fee = actual_notional * self.fee_rate
        checks["qty_base"] = qty
        checks["notional"] = actual_notional
        checks["entry_fee"] = entry_fee

        # --- AÇILIŞ SONRASI limitler ---
        post_total = self.open_count() + 1
        post_same = self.same_direction_count(side, exchange) + 1
        checks["post_total"] = post_total
        checks["post_same_direction"] = post_same
        if post_total > self.max_open_positions:
            return OpenResult(
                False,
                f"toplam pozisyon limiti ({post_total}>{self.max_open_positions})",
                checks,
            )
        if post_same > self.max_same_direction:
            return OpenResult(False, f"aynı yön limiti ({post_same}>{self.max_same_direction})", checks)

        utilisation = (self.used_margin + margin + entry_fee) / self.starting_balance
        checks["utilisation"] = utilisation
        if utilisation > self.max_utilisation:
            return OpenResult(False, f"marj kullanım limiti ({utilisation:.3f}>{self.max_utilisation})", checks)

        post_balance = self.balance - (margin + entry_fee)
        checks["post_balance"] = post_balance
        if post_balance < self.balance_floor:
            return OpenResult(False, f"bakiye tabanı ({post_balance:.2f}<{self.balance_floor})", checks)
        if post_balance < 0:
            return OpenResult(False, "bakiye negatife düşerdi", checks)

        # --- tek adımda marj + komisyon düşümü ---
        self.balance -= (margin + entry_fee)

        pos = Position(
            exchange=exchange,
            symbol=symbol,
            side=side,
            entry_price=float(price),
            qty_base=qty,
            margin=float(margin),
            leverage=float(leverage),
            entry_fee=entry_fee,
            opened_at=int(now_ms),
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            last_price=float(price),
            last_price_ts=int(price_ts if price_ts is not None else now_ms),
        )
        self.positions[key] = pos
        return OpenResult(True, "", pos, checks)

    # -- fiyat güncelleme --------------------------------------------------
    def mark_price(self, exchange: str, symbol: str, price: float, ts: int) -> None:
        pos = self.positions.get((exchange, symbol))
        if pos is None or not (price > 0):
            return
        pos.last_price = float(price)
        pos.last_price_ts = int(ts)

    def is_stale(
        self,
        exchange: str,
        symbol: str,
        now_ms: int,
        poll_interval_ms: int = 60_000,
        factor: float = 2.0,
    ) -> bool:
        pos = self.positions.get((exchange, symbol))
        if pos is None or pos.last_price_ts == 0:
            return True
        return (now_ms - pos.last_price_ts) > factor * poll_interval_ms

    # -- pozisyon kapatma --------------------------------------------------
    def close_position(
        self, exchange: str, symbol: str, price: float, *, now_ms: int = 0, reason: str = "signal"
    ) -> TradeRecord | None:
        """
        Pozisyonu kapatır: marj geri eklenir, çıkış komisyonu düşülür.

        realized_pnl = gross_pnl - entry_fee - exit_fee  (raporlama metriği)
        Bakiye değişimi = gross_pnl - entry_fee - exit_fee (aynı sonuç).
        """
        key = (exchange, symbol)
        pos = self.positions.get(key)
        if pos is None:
            return None
        if not (price > 0) or not math.isfinite(price):
            return None

        gross = pos.unrealised_pnl(price)
        exit_fee = price * pos.qty_base * self.fee_rate

        # ASSUMPTION: izole marj — kayıp marjı aşarsa pozisyon LİKİDE sayılır.
        # Bu, bakiyenin negatife düşmesini yapısal olarak engeller.
        liquidated = False
        if pos.margin + gross - exit_fee < 0:
            gross = -(pos.margin - exit_fee)
            liquidated = True

        realized = gross - pos.entry_fee - exit_fee
        self.balance += pos.margin + gross - exit_fee
        if self.balance < 0:  # son savunma hattı
            self.balance = 0.0

        record = TradeRecord(
            exchange=pos.exchange,
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=float(price),
            qty_base=pos.qty_base,
            margin=pos.margin,
            leverage=pos.leverage,
            entry_fee=pos.entry_fee,
            exit_fee=exit_fee,
            gross_pnl=gross,
            realized_pnl=realized,
            opened_at=pos.opened_at,
            closed_at=int(now_ms),
            reason=(f"LIQUIDATION:{reason}" if liquidated else reason),
            funding_fee=pos.funding_fee,
            funding_label=FUNDING_LABEL,
        )
        self.closed_trades.append(record)
        del self.positions[key]
        return record

    def close_all(
        self,
        prices: dict[tuple[str, str], tuple[float, int]],
        *,
        reason: str = "session_end",
        stale_keys: set[tuple[str, str]] | None = None,
    ) -> list[TradeRecord]:
        """Tüm pozisyonları kapatır. Bayat fiyatlılar STALE_PRICE olarak işaretlenir."""
        stale_keys = stale_keys or set()
        records: list[TradeRecord] = []
        for key in list(self.positions.keys()):
            price, ts = prices.get(key, (None, 0))  # type: ignore[assignment]
            if price is None:
                # Fiyat yoksa son bilinen fiyatla kapat; kayıt bunu belgeler.
                pos = self.positions[key]
                price = pos.last_price or pos.entry_price
                ts = pos.last_price_ts
            r = reason if key not in stale_keys else f"STALE_PRICE:{reason}"
            rec = self.close_position(key[0], key[1], float(price), now_ms=ts, reason=r)
            if rec:
                records.append(rec)
        return records

    # -- aynı mumda SL+TP --------------------------------------------------
    @staticmethod
    def resolve_same_candle(
        *, high: float, low: float, stop: float, target: float, side: str
    ) -> str:
        """
        Aynı mumda hem stop hem hedef görüldüyse KONSERVATİF kabul:
        stop önce tetiklenmiş sayılır.

        # ASSUMPTION: mum içi sıralama bilinmiyor; kötü senaryo seçilir.
        """
        if side == LONG:
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target
        if stop_hit:
            return "STOP"
        if target_hit:
            return "TAKE_PROFIT"
        return "NONE"


# ---------------------------------------------------------------------------
# Formül doğrulaması — import sırasında değil, açık çağrıda çalışır.
# ---------------------------------------------------------------------------
def verify_pnl_formulas() -> None:
    """
    Spec'teki iki referans işlemi doğrular; başarısızsa AssertionError fırlatır.

    LONG  5 birim, giriş 100, çıkış 101, taker %0.05 -> net +4.4975
    SHORT 5 birim, giriş 100, çıkış  99, taker %0.05 -> net +4.5025
    """
    # LONG
    pf = PaperPortfolio(2_000.0, fee_rate=0.0005)
    res = pf.open_position(
        "t", "LONG", LONG, 100.0, 500.0, leverage=1.0, step_size=1.0, now_ms=1
    )
    assert res.ok, res.reason
    assert res.position is not None and res.position.qty_base == 5.0
    rec = pf.close_position("t", "LONG", 101.0, now_ms=2)
    assert rec is not None
    assert abs(rec.gross_pnl - 5.0) < 1e-10, rec.gross_pnl
    assert abs(rec.entry_fee - 0.25) < 1e-10, rec.entry_fee
    assert abs(rec.exit_fee - 0.2525) < 1e-10, rec.exit_fee
    assert abs(rec.realized_pnl - 4.4975) < 1e-10, rec.realized_pnl

    # SHORT
    pf2 = PaperPortfolio(2_000.0, fee_rate=0.0005)
    res2 = pf2.open_position(
        "t", "SHORT", SHORT, 100.0, 500.0, leverage=1.0, step_size=1.0, now_ms=1
    )
    assert res2.ok, res2.reason
    assert res2.position is not None and res2.position.qty_base == 5.0
    rec2 = pf2.close_position("t", "SHORT", 99.0, now_ms=2)
    assert rec2 is not None
    assert abs(rec2.gross_pnl - 5.0) < 1e-10, rec2.gross_pnl
    assert abs(rec2.entry_fee - 0.25) < 1e-10, rec2.entry_fee
    assert abs(rec2.exit_fee - 0.2475) < 1e-10, rec2.exit_fee
    assert abs(rec2.realized_pnl - 4.5025) < 1e-10, rec2.realized_pnl
