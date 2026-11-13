"""Binance 451 (restricted location) bobinaryantsi icin public rota duzeltmesi.

Sorun
-----
Bazi bulut/veri-merkezi IP'lerinde (GitHub Actions, Colab, bu sandbox dahil)
Binance'in API alan adlari HTTP 451 doner:

    https://api.binance.com/api/v3/exchangeInfo     -> 451
    https://fapi.binance.com/fapi/v1/exchangeInfo   -> 451

Ayni IP'den Binance'in **www** alan adindaki resmi USDⓈ-M public rotasi
200 donebiliyor (bu sandbox'ta dogrulandi):

    https://www.binance.com/fapi/v1/exchangeInfo    -> 200
    https://www.binance.com/fapi/v1/ticker/24hr     -> 200
    https://www.binance.com/fapi/v1/fundingRate     -> 200
    https://www.binance.com/fapi/v1/openInterest    -> 200
    https://www.binance.com/fapi/v1/depth           -> 200
    https://www.binance.com/fapi/v1/klines          -> 200

Cozum
-----
1) Sadece **imzasiz public** USDⓈ-M (fapi) rotalarini www alan adina cevir.
   Private / emir / WS uclari aynen kalir -> imzali islemler etkilenmez.
2) ccxt `binance` sinifi `load_markets()` icinde spot katalogunu da ceker;
   restricted bir IP'de spot istegi 451 oldugu icin **tum katalog yuklemesi**
   duser. `options['fetchMarkets'] = {'types': ['linear']}` ile sadece
   USDT-M (linear) katalogu yuklenir.

Kullanim
--------
    from binance_www_route import apply_binance_www_route
    import ccxt
    c = ccxt.binance({...})
    apply_binance_www_route(c)      # daha sonra load_markets()/islemler

ACARBOT V22: adapter baslangicina dogrudan baglidir (phoenix.live.CCXTAdapter).

Bu dosya PHOENIX paketinin orijinal kodunu degistirmez; disardan yamar.
"""
from __future__ import annotations

import os

FAPI_OLD = "https://fapi.binance.com"
FAPI_NEW = "https://www.binance.com"

# Sadece public (imzasiz) rotlar. private/emir rotlari listede YOK.
PUBLIC_KEYS = (
    "fapiPublic",
    "fapiPublicV2",
    "fapiPublicV3",
    "fapiData",
)


def restrict_to_linear(client) -> None:
    """Load only the USDT-M (linear) catalogue: never touch spot (451-prone, and not traded here)."""
    client.options = client.options or {}
    client.options.setdefault("defaultType", "swap")
    client.options["fetchMarkets"] = {"types": ["linear"]}


def apply_binance_www_route(client, *, force: bool = False) -> dict[str, str]:
    """ccxt binance istemcisinin public fapi rotalarini www alan adina cevirir.

    `force=False` ise yalnizca PHOENIX_BINANCE_PUBLIC_WWW=1 (veya
    BINANCE_PUBLIC_WWW=1) ortam degiskeniyle etkinlesir.
    Degisiklikler {key: yeni_url} olarak dondurulur.
    """
    if not force and os.getenv("PHOENIX_BINANCE_PUBLIC_WWW", os.getenv("BINANCE_PUBLIC_WWW", "0")) != "1":
        return {}

    api = client.urls.get("api") or {}
    changed: dict[str, str] = {}
    for key in PUBLIC_KEYS:
        current = api.get(key)
        if isinstance(current, str) and current.startswith(FAPI_OLD):
            api[key] = current.replace(FAPI_OLD, FAPI_NEW, 1)
            changed[key] = api[key]

    # Spot katalogu 451 dondugunde tum load_markets() duser: sadece linear yukle.
    restrict_to_linear(client)
    return changed


def patch_phoenix() -> int:
    """phoenix.live.CCXTAdapter'i yamar; BINANCE adapter'i icin rotayi uygular.

    Donus: yamalanan adapter sayisi (genelde 1).
    """
    from phoenix.live import CCXTAdapter

    original_init = CCXTAdapter.__init__

    def patched_init(self, exchange_id, *args, **kwargs):
        original_init(self, exchange_id, *args, **kwargs)
        if str(exchange_id).lower().startswith("binance"):
            changed = apply_binance_www_route(self.client)
            if changed:
                print(f"[binance-www-route] public rota degisti: {changed}", flush=True)

    if getattr(CCXTAdapter.__init__, "_www_patched", False):
        return 0
    patched_init._www_patched = True
    CCXTAdapter.__init__ = patched_init
    return 1
