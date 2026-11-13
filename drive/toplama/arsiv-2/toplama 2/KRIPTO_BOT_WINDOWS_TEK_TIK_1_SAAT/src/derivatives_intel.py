"""Borsa Ücretsiz Türev İstihbaratı & Harici Veri Bağdaştırıcıları (PDF v3 Hazırlık).

Üç PDF'in 4., 6., 8. ve 9. bölümlerinde geçen ancak mevcut akışta henüz yer almayan
türev/opsiyon/makro göstergeleri için izole, API-anahtarsız (public) ve önbellekli
(TTL cache) bağdaştırıcı katmanı:

  • Basis / Mark–Index Premium (%) (Binance + OKX)
  • Cross-Exchange Funding Farkı (bps) ve Mark Fiyat Farkı (%)
  • Global Long/Short Hesap Oranı & Top Trader Long/Short Pozisyon Oranı
  • Borsa Taker Buy/Sell Oranı (Periyodik Türev İstatistiği)
  • Perp vs. Quarterly (Teslimatlı Vadeli) Takvim Spread'i (%)
  • Deribit DVOL (Beklenen Volatilite) & Put/Call Açık Pozisyon Oranı (BTC / ETH)
  • On-Chain / Kurumsal Makro Şema Sözleşmesi (Sağlayıcı yoksa dürüstçe available=False)
"""
from __future__ import annotations

import asyncio
import math
import os
import time
from typing import Any, Callable


def _finite_or_none(val: Any) -> float | None:
    try:
        if val is None or val == "":
            return None
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _base_coin(symbol: str) -> str:
    return str(symbol or "BTC/USDT").split(":")[0].split("/")[0].upper()


def _binance_pair(symbol: str) -> str:
    clean = str(symbol or "BTC/USDT").split(":")[0].replace("/", "").upper()
    return clean


def _okx_swap_inst(symbol: str) -> str:
    base = _base_coin(symbol)
    return f"{base}-USDT-SWAP"


def _binance_fapi_root() -> str:
    if os.environ.get("BINANCE_PUBLIC_WWW") == "1":
        return "https://www.binance.com"
    return "https://fapi.binance.com"


def compute_crowding_verdict(
    *,
    funding_rate: float | None = None,
    basis_pct: float | None = None,
    global_ls_ratio: float | None = None,
    top_trader_ls_ratio: float | None = None,
    taker_buy_sell_ratio: float | None = None,
) -> dict[str, Any]:
    """PDF Bölüm 6 'Kalabalık hangi tarafta?' birleşik türev teşhisi."""
    signals: list[str] = []
    crowd_score = 0.0  # + = aşırı long kalabalığı, - = aşırı short kalabalığı

    if funding_rate is not None:
        if funding_rate >= 0.0005:  # >= %0.05 (PDF #1 kritik eşik)
            crowd_score += 2.0
            signals.append("ASIRI_POZITIF_FUNDING")
        elif funding_rate <= -0.0005:
            crowd_score -= 2.0
            signals.append("ASIRI_NEGATIF_FUNDING")

    if basis_pct is not None:
        if basis_pct >= 0.15:
            crowd_score += 1.0
            signals.append("YUKSEK_FUTURES_PRIMI")
        elif basis_pct <= -0.15:
            crowd_score -= 1.0
            signals.append("DERIN_FUTURES_ISKONTOSU")

    if global_ls_ratio is not None:
        if global_ls_ratio >= 2.2:
            crowd_score += 1.5
            signals.append("PERAKENDE_ASIRI_LONG")
        elif global_ls_ratio <= 0.65:
            crowd_score -= 1.5
            signals.append("PERAKENDE_ASIRI_SHORT")

    smart_money_divergence = "YOK"
    if global_ls_ratio is not None and top_trader_ls_ratio is not None:
        if global_ls_ratio >= 1.8 and top_trader_ls_ratio < 1.0:
            smart_money_divergence = "TOP_TRADER_SHORT_PERAKENDE_LONG"
        elif global_ls_ratio <= 0.8 and top_trader_ls_ratio > 1.2:
            smart_money_divergence = "TOP_TRADER_LONG_PERAKENDE_SHORT"

    if taker_buy_sell_ratio is not None:
        if taker_buy_sell_ratio >= 1.25:
            signals.append("TAKER_ALIS_BASKIN")
        elif taker_buy_sell_ratio <= 0.80:
            signals.append("TAKER_SATIS_BASKIN")

    state = (
        "LONG_KALABALIK"
        if crowd_score >= 2.0
        else ("SHORT_KALABALIK" if crowd_score <= -2.0 else "DENGELI")
    )
    return {
        "crowding_state": state,
        "crowding_score": round(crowd_score, 2),
        "smart_money_divergence": smart_money_divergence,
        "flags": signals,
    }


class DerivativesIntelEngine:
    """Binance + OKX + Deribit ücretsiz public türev/opsiyon verisi toplayıcısı.

    Ağ hatalarında veya bölge kısıtlarında istisna fırlatmaz; erişilemeyen alanları
    ``None`` ve ``available=False`` olarak döndürür (asla sahte sıfır uydurmaz).
    Testlerde ``http_get_json`` enjekte edilerek tamamen çevrimdışı doğrulanabilir.
    """

    def __init__(
        self,
        ttl_sec: float = 120.0,
        http_get_json: Callable[[str, dict[str, Any] | None], Any] | None = None,
    ):
        self.ttl_sec = max(10.0, float(ttl_sec))
        self._http_get_json = http_get_json
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._session: Any = None

    async def close(self) -> None:
        if self._session is not None and not getattr(self._session, "closed", True):
            await self._session.close()
        self._session = None

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if self._http_get_json is not None:
            try:
                res = self._http_get_json(url, params)
                if hasattr(res, "__await__"):
                    return await res
                return res
            except Exception:
                return None
        try:
            import aiohttp

            if self._session is None or getattr(self._session, "closed", True):
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=6)
                )
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                return await resp.json(content_type=None)
        except Exception:
            return None

    async def fetch_symbol_intel(self, symbol: str, period: str = "5m") -> dict[str, Any]:
        """Tek sembol için Basis, Cross-Funding, Long/Short ve Taker oranlarını toplar."""
        now = time.time()
        cache_key = f"sym:{symbol}:{period}"
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < self.ttl_sec:
            return cached[1]

        b_root = _binance_fapi_root()
        pair = _binance_pair(symbol)
        base = _base_coin(symbol)
        okx_inst = _okx_swap_inst(symbol)

        (
            prem,
            g_ls_raw,
            t_ls_raw,
            taker_raw,
            okx_mark_raw,
            okx_fund_raw,
            okx_ls_raw,
        ) = await asyncio.gather(
            self._get_json(f"{b_root}/fapi/v1/premiumIndex", {"symbol": pair}),
            self._get_json(
                f"{b_root}/futures/data/globalLongShortAccountRatio",
                {"symbol": pair, "period": period, "limit": 1},
            ),
            self._get_json(
                f"{b_root}/futures/data/topLongShortPositionRatio",
                {"symbol": pair, "period": period, "limit": 1},
            ),
            self._get_json(
                f"{b_root}/futures/data/takerlongshortRatio",
                {"symbol": pair, "period": period, "limit": 1},
            ),
            self._get_json(
                "https://www.okx.com/api/v5/public/mark-price",
                {"instType": "SWAP", "instId": okx_inst},
            ),
            self._get_json(
                "https://www.okx.com/api/v5/public/funding-rate",
                {"instId": okx_inst},
            ),
            self._get_json(
                "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio",
                {"ccy": base, "period": "5m"},
            ),
        )
        b_mark = _finite_or_none((prem or {}).get("markPrice")) if isinstance(prem, dict) else None
        b_index = _finite_or_none((prem or {}).get("indexPrice")) if isinstance(prem, dict) else None
        b_fund = _finite_or_none((prem or {}).get("lastFundingRate")) if isinstance(prem, dict) else None
        b_basis_pct = (
            ((b_mark - b_index) / b_index * 100.0)
            if (b_mark is not None and b_index is not None and b_index > 0)
            else None
        )
        g_ls = (
            _finite_or_none(g_ls_raw[-1].get("longShortRatio"))
            if isinstance(g_ls_raw, list) and g_ls_raw
            else None
        )
        top_ls = (
            _finite_or_none(t_ls_raw[-1].get("longShortRatio"))
            if isinstance(t_ls_raw, list) and t_ls_raw
            else None
        )
        taker_bs = (
            _finite_or_none(taker_raw[-1].get("buySellRatio"))
            if isinstance(taker_raw, list) and taker_raw
            else None
        )
        okx_mark = None
        if isinstance(okx_mark_raw, dict) and okx_mark_raw.get("data"):
            okx_mark = _finite_or_none(okx_mark_raw["data"][0].get("markPx"))
        okx_fund = None
        if isinstance(okx_fund_raw, dict) and okx_fund_raw.get("data"):
            okx_fund = _finite_or_none(okx_fund_raw["data"][0].get("fundingRate"))
        okx_ls = None
        if isinstance(okx_ls_raw, dict) and okx_ls_raw.get("data"):
            first_row = okx_ls_raw["data"][0]
            if isinstance(first_row, list) and len(first_row) >= 2:
                okx_ls = _finite_or_none(first_row[1])

        cross_funding_bps = (
            round((b_fund - okx_fund) * 10_000.0, 4)
            if (b_fund is not None and okx_fund is not None)
            else None
        )
        cross_mark_spread_pct = (
            round((b_mark - okx_mark) / okx_mark * 100.0, 5)
            if (b_mark is not None and okx_mark is not None and okx_mark > 0)
            else None
        )

        eff_ls = g_ls if g_ls is not None else okx_ls
        eff_fund = b_fund if b_fund is not None else okx_fund
        crowding = compute_crowding_verdict(
            funding_rate=eff_fund,
            basis_pct=b_basis_pct,
            global_ls_ratio=eff_ls,
            top_trader_ls_ratio=top_ls,
            taker_buy_sell_ratio=taker_bs,
        )

        payload = {
            "symbol": symbol,
            "available": any(
                v is not None
                for v in (b_basis_pct, g_ls, top_ls, taker_bs, cross_funding_bps, okx_ls)
            ),
            "binance_mark_price": b_mark,
            "binance_index_price": b_index,
            "basis_pct": round(b_basis_pct, 5) if b_basis_pct is not None else None,
            "binance_funding_rate": b_fund,
            "okx_mark_price": okx_mark,
            "okx_funding_rate": okx_fund,
            "cross_funding_bps": cross_funding_bps,
            "cross_mark_spread_pct": cross_mark_spread_pct,
            "global_long_short_ratio": eff_ls,
            "top_trader_long_short_ratio": top_ls,
            "taker_buy_sell_ratio": taker_bs,
            "crowding": crowding,
        }
        self._cache[cache_key] = (now, payload)
        return payload

    async def fetch_deribit_options_overview(self, currency: str = "BTC") -> dict[str, Any]:
        """Deribit ücretsiz public API'den DVOL ve Put/Call OI oranını okur (BTC / ETH)."""
        ccy = str(currency or "BTC").upper()
        if ccy not in ("BTC", "ETH"):
            return {"currency": ccy, "available": False, "dvol": None, "put_call_oi_ratio": None}
        now = time.time()
        cache_key = f"deribit:{ccy}"
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < self.ttl_sec:
            return cached[1]

        now_ms = int(now * 1000)
        dvol_raw = await self._get_json(
            "https://www.deribit.com/api/v2/public/get_volatility_index_data",
            {
                "currency": ccy,
                "start_timestamp": now_ms - 3600_000,
                "end_timestamp": now_ms,
                "resolution": "3600",
            },
        )
        dvol_val = None
        if isinstance(dvol_raw, dict):
            rows = (dvol_raw.get("result") or {}).get("data") or []
            if rows and isinstance(rows[-1], list) and len(rows[-1]) >= 5:
                dvol_val = _finite_or_none(rows[-1][4])

        book_raw = await self._get_json(
            "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
            {"currency": ccy, "kind": "option"},
        )
        put_oi = 0.0
        call_oi = 0.0
        has_opt = False
        if isinstance(book_raw, dict):
            for item in book_raw.get("result") or []:
                inst = str(item.get("instrument_name") or "")
                oi = _finite_or_none(item.get("open_interest")) or 0.0
                if inst.endswith("-P"):
                    put_oi += oi
                    has_opt = True
                elif inst.endswith("-C"):
                    call_oi += oi
                    has_opt = True
        pc_ratio = round(put_oi / call_oi, 4) if has_opt and call_oi > 1e-9 else None
        payload = {
            "currency": ccy,
            "available": (dvol_val is not None) or (pc_ratio is not None),
            "dvol": dvol_val,
            "put_call_oi_ratio": pc_ratio,
        }
        self._cache[cache_key] = (now, payload)
        return payload


def normalize_external_alpha(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """On-chain & kurumsal makro sağlayıcı şeması (Glassnode/CryptoQuant/FRED vb. bağlandığında).

    Sağlayıcı verisi verilmemişse hiçbir alan sıfırla taklit edilmez; ``available=False`` döner.
    """
    if not raw or not isinstance(raw, dict):
        return {
            "available": False,
            "onchain": {
                "exchange_netflow_usd": None,
                "stablecoin_reserve_change_pct": None,
                "mvrv_z": None,
                "sopr": None,
                "nupl": None,
            },
            "macro": {
                "dxy_change_pct": None,
                "us10y_yield": None,
                "nasdaq_corr": None,
                "spot_etf_netflow_musd": None,
            },
        }
    return {
        "available": True,
        "onchain": {
            "exchange_netflow_usd": _finite_or_none(raw.get("exchange_netflow_usd")),
            "stablecoin_reserve_change_pct": _finite_or_none(raw.get("stablecoin_reserve_change_pct")),
            "mvrv_z": _finite_or_none(raw.get("mvrv_z")),
            "sopr": _finite_or_none(raw.get("sopr")),
            "nupl": _finite_or_none(raw.get("nupl")),
        },
        "macro": {
            "dxy_change_pct": _finite_or_none(raw.get("dxy_change_pct")),
            "us10y_yield": _finite_or_none(raw.get("us10y_yield")),
            "nasdaq_corr": _finite_or_none(raw.get("nasdaq_corr")),
            "spot_etf_netflow_musd": _finite_or_none(raw.get("spot_etf_netflow_musd")),
        },
    }
