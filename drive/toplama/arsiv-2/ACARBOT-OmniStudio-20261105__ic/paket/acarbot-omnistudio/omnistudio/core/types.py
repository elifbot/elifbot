"""AI OmniStudio — çekirdek veri tipleri.

Tasarım ilkesi: finansal büyüklükler float değil Decimal'a yakın dikkat ister;
burada fiyat/miktar float taşınır ama muhasebe `ledger.py` içinde yuvarlama
kuralına bağlanır. Her kayıt `ts_ms` (borsa/veri zamanı) ve `mono` (süreç
monotonic) ayrımını korur; ikisi birbirinin yerine kullanılamaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def sign(self) -> float:
        return 1.0 if self is Side.LONG else -1.0

    @property
    def opposite(self) -> "Side":
        return Side.SHORT if self is Side.LONG else Side.LONG


class OrderState(str, Enum):
    INTENT = "INTENT"          # karar verildi, henüz borsaya/deftere yazılmadı
    PENDING = "PENDING"        # emir gönderildi, terminal durum bilinmiyor
    OPEN = "OPEN"              # defterde çalışıyor (resting)
    PARTIAL = "PARTIAL"        # kısmi dolum
    FILLED = "FILLED"          # tam dolum
    CANCELLED = "CANCELLED"    # iptal edildi (dolmayan miktar)
    EXPIRED = "EXPIRED"        # süre doldu, dolmadı
    REJECTED = "REJECTED"      # baştan reddedildi
    RECONCILED = "RECONCILED"  # mutabakatla terminal duruma bağlandı


#: Terminal durumlar: bir daha değişmez.
TERMINAL_ORDER_STATES = frozenset({
    OrderState.FILLED, OrderState.CANCELLED,
    OrderState.EXPIRED, OrderState.REJECTED,
})


class RunState(str, Enum):
    STARTING = "STARTING"
    WARMUP = "WARMUP"
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    COMPLETED = "COMPLETED"
    DISCONTINUOUS = "DISCONTINUOUS"  # süreklilik boşluğu; COMPLETED sayılmaz
    FAILED = "FAILED"                # görev ölümü / kritik hata
    STOPPED = "STOPPED"              # kullanıcı isteği


class Mode(str, Enum):
    #: Gerçek piyasa verisi + sanal defter. Emir borsaya GİTMEZ.
    PAPER = "PAPER"
    #: Yalnız veri topla, karar üret, hiç pozisyon açma.
    OBSERVE = "OBSERVE"
    #: Kod yolu bu sürümde KİLİTLİ. Bkz. execution/live_guard.py
    LIVE = "LIVE"


@dataclass(frozen=True, slots=True)
class Tick:
    """Tek bir gerçekleşen işlem (aggTrade/trades)."""
    exchange: str
    symbol: str
    price: float
    qty: float
    ts_ms: int
    is_buyer_maker: bool = False  # True => satıcı agresif (satış baskısı)

    @property
    def quote(self) -> float:
        return self.price * self.qty

    @property
    def signed_quote(self) -> float:
        """CVD katkısı: agresif alış +, agresif satış -."""
        return -self.quote if self.is_buyer_maker else self.quote


@dataclass(frozen=True, slots=True)
class Quote:
    """En iyi alış/satış — makas ve maker gerçekleşebilirliği için."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    ts_ms: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        m = self.mid
        return ((self.ask - self.bid) / m * 10_000.0) if m > 0 else float("inf")


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    exchange: str
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    quote_volume: float
    closed: bool = True


@dataclass(frozen=True, slots=True)
class Signal:
    """Dedektör çıktısı.

    SÖZLEŞME (v9 hattından korunur): `side` PİYASANIN gittiği yönü söyler.
    Fade stratejisi bunun tersini alır; çevirme strateji katmanında yapılır.
    """
    exchange: str
    symbol: str
    side: Side
    price: float
    ts_ms: int
    ret_pct: float
    rvol: float
    volume_usd: float
    window_ms: int
    ctx_ret: float = 0.0
    ctx_vratio: float = 0.0
    ctx_vratio3: float = 0.0
    breadth_ratio: float = 0.0
    flow_score: float = 0.0
    tag: str = ""
    signal_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        return d


@dataclass(slots=True)
class Order:
    order_id: str
    intent_id: str
    exchange: str
    symbol: str
    side: Side
    qty: float
    limit_price: float | None
    is_maker: bool
    state: OrderState
    created_ms: int
    updated_ms: int
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    fee_paid: float = 0.0
    reason: str = ""
    closed_bar_key: str = ""
    #: İcra katmanı iç metadata'sı (plan, signal_id, pozisyon bağı).
    #: slots=True olduğu için setattr yerine bu açık alan kullanılır.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining(self) -> float:
        return max(0.0, self.qty - self.filled_qty)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_ORDER_STATES

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        d["state"] = self.state.value
        return d


@dataclass(slots=True)
class Position:
    position_id: str
    exchange: str
    symbol: str
    side: Side
    qty: float
    entry_price: float
    entry_ms: int
    entry_fee: float
    stop_price: float
    take_profit_price: float
    signal_id: str = ""
    closed_ms: int | None = None
    exit_price: float | None = None
    exit_fee: float = 0.0
    realized_net: float | None = None
    exit_reason: str = ""
    # Yol boyunca gözlenen ekstrem excursionlar (MFE/MAE) — gerçekleşmiş kâr DEĞİL.
    mfe: float = 0.0
    mae: float = 0.0
    peak_price: float = 0.0
    trail_active: bool = False
    funding_paid: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.closed_ms is None

    def unrealized(self, mark: float) -> float:
        """Açık brüt PnL. Çıkış ücreti ve funding DÜŞÜLMEMİŞTİR."""
        return (mark - self.entry_price) * self.qty * self.side.sign

    def net_if_closed(self, mark: float, exit_fee: float) -> float:
        return (self.unrealized(mark) - self.entry_fee - exit_fee - self.funding_paid)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        return d


@dataclass(frozen=True, slots=True)
class GateResult:
    """Bir kapının kararı. `passed=False` ise `code` makine okunur ret nedenidir."""
    name: str
    passed: bool
    code: str = ""
    detail: str = ""
    value: float | None = None
    threshold: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Decision:
    """Bir sembol-mum için tam karar kaydı — geçse de geçmese de yazılır."""
    decision_id: str
    ts_ms: int
    exchange: str
    symbol: str
    closed_bar_key: str
    candidate_side: str = ""
    accepted: bool = False
    gates: list[GateResult] = field(default_factory=list)
    reject_code: str = ""
    order_id: str = ""
    ai_council: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0

    @property
    def first_reject(self) -> str:
        if self.accepted:
            return ""
        for g in self.gates:
            if not g.passed:
                return g.code or g.name
        return self.reject_code or "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["gates"] = [g.to_dict() for g in self.gates]
        return d