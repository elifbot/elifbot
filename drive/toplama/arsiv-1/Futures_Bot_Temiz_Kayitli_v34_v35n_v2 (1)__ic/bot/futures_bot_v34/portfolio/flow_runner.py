"""OKX + Binance gerçek taker akışıyla dinamik gölge pozisyon.

Ana stratejiden tamamen ayrıdır; emir göndermez. Aday giriş 15 sn CVD yönü,
60 sn akış VWAP'ı ve 1 sn süreklilik ister. Sabit TP yoktur. 2×ATR başlangıç
felaket stopu ve 3×ATR chandelier takip kullanılır.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import time
from typing import Callable

import aiohttp

from scanner.money_flow import AkisDefteri

OKX_CANDLES = "https://www.okx.com/api/v5/market/candles"
BINANCE_CANDLES = "https://www.binance.com/fapi/v1/klines"
MARJ = 25.0
KALDIRAC = 10.0
UCRET = 0.0005


async def okx_tamamlanmis_mumlar(oturum: aiohttp.ClientSession, sembol: str) -> list:
    async with oturum.get(OKX_CANDLES, params={"instId": sembol, "bar": "1m", "limit": 100},
                          timeout=aiohttp.ClientTimeout(total=20)) as r:
        govde = await r.json()
    if str(govde.get("code")) != "0":
        raise RuntimeError(f"OKX mum hatası: {govde.get('code')} {govde.get('msg')}")
    return govde.get("data", [])


async def binance_tamamlanmis_mumlar(oturum: aiohttp.ClientSession, sembol: str) -> list:
    async with oturum.get(BINANCE_CANDLES, params={"symbol": sembol, "interval": "1m", "limit": 100},
                          timeout=aiohttp.ClientTimeout(total=20)) as r:
        govde = await r.json()
    if not isinstance(govde, list):
        raise RuntimeError(f"Binance mum hatası: {str(govde)[:160]}")
    simdi = int(time.time() * 1000)
    # CanliTeknik ile aynı ortak OHLC biçimi; yalnız kapanmış mumlar.
    return [[str(x[0]), str(x[1]), str(x[2]), str(x[3]), str(x[4]),
             str(x[5]), str(x[5]), str(x[7] if len(x) > 7 else "0"), "1"]
            for x in govde if int(x[6]) < simdi]


async def tamamlanmis_mumlar(oturum: aiohttp.ClientSession, exchange: str, sembol: str) -> list:
    if exchange == "okx":
        return await okx_tamamlanmis_mumlar(oturum, sembol)
    if exchange == "binance":
        return await binance_tamamlanmis_mumlar(oturum, sembol)
    raise ValueError(f"desteklenmeyen borsa: {exchange}")


class CanliTeknik:
    """Tamamlanmış 1m OHLC + yeni tradelerden nedensel ATR/Supertrend."""

    def __init__(self, mumlar: list):
        self.bars = []
        for b in sorted(mumlar, key=lambda x: int(x[0])):
            if str(b[8]) != "1":
                continue
            self.bars.append((int(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4])))
        self.bars = self.bars[-150:]
        self.current = None
        self.atr = None
        self.supertrend = None
        self.bar_close_ms = 0
        self._hesapla()

    def _hesapla(self) -> None:
        if len(self.bars) < 15:
            self.atr = self.supertrend = None
            return
        trs = []
        for i, b in enumerate(self.bars):
            _, o, h, l, c = b
            pc = self.bars[i - 1][4] if i else c
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs[1:15]) / 14.0
        st = None
        prev_up = prev_lo = prev_st = prev_close = None
        for i in range(14, len(self.bars)):
            if i > 14:
                atr = (atr * 13 + trs[i]) / 14.0
            _, o, h, l, c = self.bars[i]
            mid = (h + l) / 2.0
            up, lo = mid + 3 * atr, mid - 3 * atr
            if prev_up is None:
                final_up, final_lo = up, lo
                st = final_up if c <= final_up else final_lo
            else:
                final_up = up if up < prev_up or prev_close > prev_up else prev_up
                final_lo = lo if lo > prev_lo or prev_close < prev_lo else prev_lo
                if prev_st == prev_up:
                    st = final_up if c <= final_up else final_lo
                else:
                    st = final_lo if c >= final_lo else final_up
            prev_up, prev_lo, prev_st, prev_close = final_up, final_lo, st, c
        self.atr = atr if math.isfinite(atr) and atr > 0 else None
        self.supertrend = st
        self.bar_close_ms = self.bars[-1][0] + 60_000

    def on_trade(self, ts: int, fiyat: float) -> None:
        dakika = int(ts) // 60_000 * 60_000
        if self.current is None:
            self.current = [dakika, fiyat, fiyat, fiyat, fiyat]
            return
        if dakika < self.current[0]:
            return
        if dakika == self.current[0]:
            self.current[2] = max(self.current[2], fiyat)
            self.current[3] = min(self.current[3], fiyat)
            self.current[4] = fiyat
            return
        kapanan = tuple(self.current)
        if not self.bars or kapanan[0] > self.bars[-1][0]:
            self.bars.append(kapanan)
        # İşlem olmayan dakikaları son kapanışla taşı; gelecek veri kullanılmaz.
        eksik = kapanan[0] + 60_000
        while eksik < dakika:
            c = self.bars[-1][4]
            self.bars.append((eksik, c, c, c, c))
            eksik += 60_000
        self.bars = self.bars[-150:]
        self.current = [dakika, fiyat, fiyat, fiyat, fiyat]
        self._hesapla()


@dataclass
class AkisAday:
    exchange: str
    symbol: str
    side: str
    signal_ts: int
    signal_price: float
    since: int | None = None


@dataclass
class AkisPozisyon:
    exchange: str
    symbol: str
    side: str
    signal_ts: int
    entry_ts: int
    entry: float
    qty: float
    entry_fee: float
    initial_stop: float
    stop: float
    highest: float
    lowest: float
    last_price: float
    mfe: float = 0.0
    mae: float = 0.0


class FlowShadowEngine:
    def __init__(self, akis: AkisDefteri,
                 on_event: Callable[[dict], None] | None = None,
                 on_close: Callable[[dict], None] | None = None):
        self.akis = akis
        self.on_event = on_event or (lambda row: None)
        self.on_close = on_close or (lambda row: None)
        self.teknik: dict[tuple[str, str], CanliTeknik] = {}
        self.adaylar: dict[tuple[str, str], AkisAday] = {}
        self.pozisyonlar: dict[tuple[str, str], AkisPozisyon] = {}
        self.kapanan = 0
        self.toplam_pnl = 0.0
        self.acilan = 0
        self.reddedilen = 0
        self.suresi_dolan = 0

    def _olay(self, tur: str, ts: int, exchange: str, symbol: str,
              side: str = "", fiyat: float | None = None, detay: str = "") -> None:
        self.on_event({"ts": int(ts), "tur": tur, "exchange": exchange,
                       "symbol": symbol, "side": side, "fiyat": fiyat or "",
                       "detay": detay})

    def teknik_hazirla(self, exchange: str, sembol: str, mumlar: list) -> None:
        self.teknik[(exchange, sembol)] = CanliTeknik(mumlar)

    @staticmethod
    def _base(symbol: str) -> str:
        t = symbol.upper()
        for ek in ("-USDT-SWAP", "-USDT", "USDT"):
            if t.endswith(ek):
                t = t[:-len(ek)]
                break
        if t.startswith("1000") and len(t) > 5:
            t = t[4:]
        return t

    def sinyal(self, exchange: str, symbol: str, side: str,
               signal_ts: int, signal_price: float) -> None:
        if exchange not in ("okx", "binance"):
            return
        key = (exchange, symbol)
        base = self._base(symbol)
        ayni_varlik = any(self._base(s) == base for _, s in
                          list(self.pozisyonlar) + list(self.adaylar))
        if key in self.pozisyonlar or key in self.adaylar or ayni_varlik:
            self.reddedilen += 1
            detay = ("çapraz-borsa aynı varlık koruması" if ayni_varlik and
                     key not in self.pozisyonlar and key not in self.adaylar
                     else "aynı sembolde gölge aday/pozisyon var")
            self._olay("sinyal_red", signal_ts, exchange, symbol, side,
                       signal_price, detay)
            return
        self.adaylar[key] = AkisAday(exchange, symbol, side, int(signal_ts), float(signal_price))
        self._olay("aday", signal_ts, exchange, symbol, side, signal_price,
                   "cvd15+vwap60; 1sn süreklilik; 60sn süre")

    def _kapat(self, key: tuple[str, str], ts: int, fiyat: float, sebep: str) -> None:
        p = self.pozisyonlar.pop(key, None)
        if p is None or not (fiyat > 0):
            return
        yon = 1 if p.side == "LONG" else -1
        gross = (fiyat - p.entry) * p.qty * yon
        exit_fee = abs(fiyat * p.qty) * UCRET
        net = gross - p.entry_fee - exit_fee
        close_ret = yon * (fiyat / p.entry - 1) * 100
        teknik = self.teknik.get(key)
        row = {"exchange": p.exchange, "symbol": p.symbol, "side": p.side,
               "signal_ts": p.signal_ts, "entry_ts": p.entry_ts, "exit_ts": int(ts),
               "entry_delay_s": (p.entry_ts - p.signal_ts) / 1000,
               "entry_price": p.entry, "exit_price": float(fiyat),
               "reason": sebep, "gross_pnl": gross, "fees": p.entry_fee + exit_fee,
               "realized_pnl": net, "mfe_pct": p.mfe, "mae_pct": p.mae,
               "close_ret_pct": close_ret, "giveback_pct": max(0.0, p.mfe - close_ret),
               "initial_stop": p.initial_stop, "stop_price": p.stop,
               "atr_at_exit": teknik.atr if teknik is not None else None,
               "hold_s": (int(ts) - p.entry_ts) / 1000}
        self.kapanan += 1
        self.toplam_pnl += net
        self.on_close(row)
        self._olay("kapandi", ts, p.exchange, p.symbol, p.side, fiyat,
                   f"{sebep};net={net:.8f}")

    def on_trade(self, exchange: str, symbol: str, ts: int, fiyat: float) -> None:
        if exchange not in ("okx", "binance") or not (fiyat > 0):
            return
        key = (exchange, symbol)
        teknik = self.teknik.get(key)
        if teknik is not None:
            teknik.on_trade(ts, fiyat)
        p = self.pozisyonlar.get(key)
        if p is not None:
            p.last_price = fiyat
            yon = 1 if p.side == "LONG" else -1
            ret = yon * (fiyat / p.entry - 1) * 100
            p.mfe = max(p.mfe, ret)
            p.mae = max(p.mae, -ret)
            p.highest = max(p.highest, fiyat)
            p.lowest = min(p.lowest, fiyat)
            initial_hit = ((p.side == "LONG" and fiyat <= p.initial_stop)
                           or (p.side == "SHORT" and fiyat >= p.initial_stop))
            if initial_hit:
                self._kapat(key, ts, fiyat, "disaster_2atr")
                return
            if teknik is not None and teknik.atr is not None:
                if p.side == "LONG":
                    p.stop = max(p.stop, p.highest - 3 * teknik.atr)
                    hit = fiyat <= p.stop
                else:
                    p.stop = min(p.stop, p.lowest + 3 * teknik.atr)
                    hit = fiyat >= p.stop
                if hit:
                    self._kapat(key, ts, fiyat, "chandelier_3atr")
                    return

        a = self.adaylar.get(key)
        if a is None:
            return
        if ts - a.signal_ts > 60_000:
            self.adaylar.pop(key, None)
            self.suresi_dolan += 1
            self._olay("aday_suresi_doldu", ts, exchange, symbol, a.side, fiyat)
            return
        if teknik is None or teknik.atr is None:
            return
        yon = 1 if a.side == "LONG" else -1
        c15 = self.akis.anlik(exchange, symbol, ts, 15)
        c60 = self.akis.anlik(exchange, symbol, ts, 60)
        onay = (c15.hazir and yon * c15.cvd_usd > 0
                and c60.vwap is not None and yon * (fiyat - c60.vwap) > 0)
        if not onay:
            a.since = None
            return
        if a.since is None:
            a.since = ts
            self._olay("onay_basladi", ts, exchange, symbol, a.side, fiyat,
                       f"cvd15={c15.cvd_usd:.4f};vwap60={c60.vwap:.10f}")
            return
        if ts - a.since < 1000:
            return
        qty = MARJ * KALDIRAC / fiyat
        entry_fee = MARJ * KALDIRAC * UCRET
        stop = fiyat - 2 * teknik.atr if a.side == "LONG" else fiyat + 2 * teknik.atr
        self.pozisyonlar[key] = AkisPozisyon(
            exchange, symbol, a.side, a.signal_ts, int(ts), fiyat, qty, entry_fee,
            stop, stop, fiyat, fiyat, fiyat)
        self.adaylar.pop(key, None)
        self.acilan += 1
        self._olay("acildi", ts, exchange, symbol, a.side, fiyat,
                   f"atr={teknik.atr:.10f};stop={stop:.10f};sabit_tp=yok")

    def adaylari_iptal_et(self, ts: int, sebep: str = "drain_start") -> None:
        for key, a in list(self.adaylar.items()):
            self.adaylar.pop(key, None)
            self._olay("aday_iptal", ts, a.exchange, a.symbol, a.side, a.signal_price, sebep)

    def session_end(self, ts: int, sebep: str = "session_end") -> None:
        for key, p in list(self.pozisyonlar.items()):
            self._kapat(key, ts, p.last_price or p.entry, sebep)
        self.adaylari_iptal_et(ts, sebep)
