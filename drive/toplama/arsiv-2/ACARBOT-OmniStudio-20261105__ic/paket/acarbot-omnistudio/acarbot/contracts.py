"""Gerçek borsa sözleşme metaverisi → doğrulanmış `ContractSpec`.

AMAÇ
  Maildeki V10 paketinde `contract_math.py` (Decimal PnL) ile gerçek
  metaveri arasında KÖPRÜ YOKTU: `futures_contract_audit.py` kendi
  uydurduğu face/lot_step/tick_size değerlerini "kanıt" diye deniyordu ve
  motor 614 sözleşmeyi bu yüzden dışlıyordu. Bu modül borsanın KENDİ
  alanlarından spec üretir; uydurma yok, eksik alan varsa sözleşme
  `reject_reason` ile reddedilir.

KAYNAK ALANLARI (5 Kasım 2026, canlı yanıtlarla doğrulandı)
  Binance USD-M : contractType, marginAsset, liquidationFee,
                  filters[LOT_SIZE].stepSize/minQty, filters[PRICE_FILTER].tickSize,
                  filters[MIN_NOTIONAL].notional
  Binance COIN-M: contractType, marginAsset, contractSize(USD), liquidationFee,
                  filters[LOT_SIZE] (kontrat adedi), filters[PRICE_FILTER].tickSize
  OKX           : ctType(linear/inverse), ctVal, ctValCcy, settleCcy,
                  lotSz, minSz, tickSz, expTime, state
  Gate.io       : quanto_multiplier, order_size_min/max, order_price_round,
                  maintenance_rate, leverage_max, funding_interval

KAPSAM
  `executable=True`  → PAPER motoru bu sözleşmede işlem açabilir.
  `executable=False` → yalnız gözlem; nedeni açıkça yazılır (X-PERP, endeks,
                       hisse/emtia altın, USDC marjlı, vadeli/teslimat, ters).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from .contract_math import ContractSpec, D

#: Riskli/özel ürün aileleri — otomatik PAPER dışında tutulur.
NON_CRYPTO_UNDERLYINGS = frozenset({
    "XAU", "XAG", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
    "ADBE", "AAOI", "ALAB", "CRCL", "SPY", "QQQ",
})


@dataclass(frozen=True)
class Instrument:
    """Bir vadeli sözleşmenin tam, doğrulanmış tanımı."""
    venue: str                 # binance | okx | gateio
    market: str                # binance_usdm | binance_coinm | okx_swap | okx_futures | gateio_usdt | gateio_btc
    symbol: str                # borsa sembolü (BTCUSDT / BTC-USDT-SWAP / BTC_USDT)
    settlement: str            # USDT | USDC | USD | BTC ...
    kind: str                  # linear | inverse
    product: str               # perpetual | xperp | dated | tradifi
    face: Decimal              # linear: 1 birimdeki BASE; inverse: kontrat başına QUOTE
    lot_step: Decimal          # miktar adımı (kontrat/baz adet)
    min_qty: Decimal
    max_qty: Decimal | None
    tick_size: Decimal
    min_notional: Decimal | None
    liq_fee_rate: Decimal | None      # borsanın bildirdiği tasfiye ücreti oranı
    maintenance_rate: Decimal | None
    max_leverage: Decimal | None
    funding_interval_h: Decimal | None
    expires_ms: int | None
    raw_status: str
    executable: bool
    reject_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.market}:{self.symbol}"

    @property
    def display(self) -> str:
        return f"{self.market}:{self.symbol}"

    def spec(self) -> ContractSpec:
        if not self.executable:
            raise ValueError(f"sözleşme PAPER dışı: {self.reject_reason}")
        return ContractSpec(
            market=self.market, symbol=self.symbol, kind=self.kind,
            settlement=self.settlement, face=self.face,
            lot_step=self.lot_step, min_qty=self.min_qty,
            tick_size=self.tick_size, expires_ms=self.expires_ms,
        )


def _dec(v: Any, default: str = "0") -> Decimal:
    try:
        if v is None or v == "":
            return D(default)
        return D(v)
    except Exception:
        return D(default)


def _status_ok(v: str) -> bool:
    return str(v or "").upper() in {"TRADING", "LIVE", "OPEN", "1", "TRUE"}


# --------------------------------------------------------------------------
# Binance
# --------------------------------------------------------------------------
def parse_binance(payload: dict[str, Any], market: str) -> list[Instrument]:
    """`/fapi/v1/exchangeInfo` veya `/dapi/v1/exchangeInfo` yanıtı."""
    if not isinstance(payload.get("symbols"), list):
        raise ValueError("Binance exchangeInfo: symbols eksik")
    coinm = market == "binance_coinm"
    status_field = "contractStatus" if coinm else "status"
    out: list[Instrument] = []
    for r in payload["symbols"]:
        sym = r.get("symbol")
        if not sym:
            continue
        ctype = str(r.get("contractType") or "")
        status = str(r.get(status_field) or "")
        filt = {f.get("filterType"): f for f in r.get("filters", []) or []}
        lot = filt.get("LOT_SIZE", {})
        price = filt.get("PRICE_FILTER", {})
        notional = filt.get("MIN_NOTIONAL", {})
        settlement = str(r.get("marginAsset") or "")
        face = _dec(r.get("contractSize"), "1") if coinm else D("1")
        product = ("tradifi" if ctype.startswith("TRADIFI") else
                   "perpetual" if ctype == "PERPETUAL" else
                   "dated" if ctype else "unknown")
        reasons: list[str] = []
        if not _status_ok(status):
            reasons.append(f"durum={status or 'yok'}")
        if product not in {"perpetual", "tradifi"}:
            reasons.append(f"vadeli/teslimat ({ctype or 'bilinmeyen'})")
        # USDC marjlı sözleşme PAPER dışı: USDC/USDT 1:1 varsayılmaz.
        if settlement != "USDT":
            reasons.append(f"settlement={settlement or 'yok'} (yalnız USDT)")
        if coinm:
            reasons.append("inverse (coin-margined) PAPER hesabı henüz bağlı değil")
        if product == "tradifi":
            reasons.append("TRADIFI (tokenize hisse/emtia) risk modeli yok")
        out.append(Instrument(
            venue="binance", market=market, symbol=sym,
            settlement=settlement, kind="inverse" if coinm else "linear",
            product=product,
            face=face,
            lot_step=_dec(lot.get("stepSize"), "1"),
            min_qty=_dec(lot.get("minQty"), "1"),
            max_qty=_dec(lot.get("maxQty"), "0") or None,
            tick_size=_dec(price.get("tickSize"), "0.00000001"),
            min_notional=_dec(notional.get("notional"), "0") or None,
            liq_fee_rate=_dec(r.get("liquidationFee"), "0") or None,
            maintenance_rate=_dec(r.get("requiredMarginPercent"), "0") or None,
            max_leverage=None,
            funding_interval_h=None,
            expires_ms=None,
            raw_status=status,
            executable=not reasons,
            reject_reason="; ".join(reasons),
            extra={"contractType": ctype, "pair": r.get("pair")},
        ))
    return out


# --------------------------------------------------------------------------
# OKX
# --------------------------------------------------------------------------
def parse_okx(payload: dict[str, Any], market: str) -> list[Instrument]:
    if str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise ValueError(f"OKX instruments hatası: {payload.get('msg')!r}")
    out: list[Instrument] = []
    for r in payload["data"]:
        sym = r.get("instId")
        if not sym:
            continue
        ct_type = str(r.get("ctType") or "")
        state = str(r.get("state") or "")
        settle = str(r.get("settleCcy") or "")
        exp = r.get("expTime") or ""
        expires_ms = int(exp) if str(exp).isdigit() and int(exp) > 0 else None
        product = ("xperp" if "XPERP" in sym else
                   "dated" if expires_ms else "perpetual")
        underlying = str(r.get("ctValCcy") or "")
        reasons: list[str] = []
        if state != "live":
            reasons.append(f"durum={state or 'yok'}")
        if ct_type not in {"linear", "inverse"}:
            reasons.append(f"ctType={ct_type or 'yok'}")
        if settle not in {"USDT", "USDC", "USD"}:
            reasons.append(f"settlement={settle or 'yok'}")
        if product == "xperp":
            reasons.append("X-PERP (özel vade/takas kuralı; funding & uzlaşma doğrulanmadı)")
        if product == "dated":
            reasons.append("vadeli/teslimat sözleşmesi (vade uzlaşısı modellenmedi)")
        if settle == "USD":
            reasons.append("USD settlement (USDT ile 1:1 varsayılmaz)")
        if ct_type == "inverse":
            reasons.append("inverse (coin-margined) PAPER hesabı henüz bağlı değil")
        if underlying in NON_CRYPTO_UNDERLYINGS:
            reasons.append(f"kripto dışı dayanak ({underlying})")
        out.append(Instrument(
            venue="okx", market=market, symbol=sym,
            settlement=settle, kind=ct_type or "unknown", product=product,
            face=_dec(r.get("ctVal"), "1"),
            lot_step=_dec(r.get("lotSz"), "1"),
            min_qty=_dec(r.get("minSz"), "1"),
            max_qty=_dec(r.get("maxMktSz"), "0") or None,
            tick_size=_dec(r.get("tickSz"), "0.00000001"),
            min_notional=None,
            liq_fee_rate=None,
            maintenance_rate=None,
            max_leverage=_dec(r.get("lever"), "0") or None,
            funding_interval_h=None,
            expires_ms=expires_ms,
            raw_status=state,
            executable=not reasons,
            reject_reason="; ".join(reasons),
            extra={"ctValCcy": underlying, "instFamily": r.get("instFamily")},
        ))
    return out


# --------------------------------------------------------------------------
# Gate.io (maildeki V10 çekirdeğinin kullandığı borsa)
# --------------------------------------------------------------------------
def parse_gateio(contract: dict[str, Any], market: str) -> Instrument:
    sym = str(contract.get("name") or "")
    if not sym:
        raise ValueError("Gate.io sözleşme adı yok")
    inverse = market == "gateio_btc"
    status = str(contract.get("status") or "")
    reasons: list[str] = []
    if status != "trading":
        reasons.append(f"durum={status or 'yok'}")
    if contract.get("in_delisting"):
        reasons.append("delist ediliyor")
    if inverse:
        reasons.append("inverse (BTC-marjlı) PAPER hesabı bağlı değil")
    if sym.endswith("_USDC"):
        reasons.append("USDC marjlı")
    interval = contract.get("funding_interval")
    return Instrument(
        venue="gateio", market=market, symbol=sym,
        settlement="BTC" if inverse else "USDT",
        kind="inverse" if inverse else "linear",
        product="perpetual",
        face=_dec(contract.get("quanto_multiplier"), "1"),
        lot_step=D("1"),                       # Gate miktarı kontrat adedi
        min_qty=_dec(contract.get("order_size_min"), "1"),
        max_qty=_dec(contract.get("order_size_max"), "0") or None,
        tick_size=_dec(contract.get("order_price_round"), "0.00000001"),
        min_notional=None,
        liq_fee_rate=None,
        maintenance_rate=_dec(contract.get("maintenance_rate"), "0") or None,
        max_leverage=_dec(contract.get("leverage_max"), "0") or None,
        funding_interval_h=(D(str(interval)) / D("3600")) if interval else None,
        expires_ms=None,
        raw_status=status,
        executable=not reasons,
        reject_reason="; ".join(reasons),
        extra={"raw": {k: contract.get(k) for k in
                       ("funding_rate", "funding_next_apply", "order_size_max")}},
    )


def summarize(items: Iterable[Instrument]) -> dict[str, Any]:
    """Kapsam raporu: hangi pazarda kaç sözleşme, kaçı PAPER'a uygun."""
    out: dict[str, Any] = {}
    for i in items:
        d = out.setdefault(i.market, {"total": 0, "executable": 0, "rejected": 0,
                                      "reasons": {}})
        d["total"] += 1
        if i.executable:
            d["executable"] += 1
        else:
            d["rejected"] += 1
            key = i.reject_reason.split(";")[0].split("(")[0].strip()
            d["reasons"][key] = d["reasons"].get(key, 0) + 1
    for d in out.values():
        d["reasons"] = dict(sorted(d["reasons"].items(), key=lambda kv: -kv[1]))
    total = sum(d["total"] for d in out.values())
    ex = sum(d["executable"] for d in out.values())
    out["_totals"] = {"total": total, "executable": ex,
                      "rejected": total - ex,
                      "coverage_pct": round(ex / total * 100, 2) if total else 0.0}
    return out
