from binance_www_route import apply_binance_www_route


def test_binance_www_route_rewrites_only_public_fapi_and_linear_markets():
    class C:
        def __init__(self):
            self.urls = {"api": {
                "fapiPublic": "https://fapi.binance.com/fapi/v1",
                "fapiPublicV2": "https://fapi.binance.com/fapi/v2",
                "fapiPublicV3": "https://fapi.binance.com/fapi/v3",
                "fapiData": "https://fapi.binance.com/futures/data",
                "private": "https://fapi.binance.com/private",
            }}
            self.options = {}
    c = C()
    changed = apply_binance_www_route(c, force=True)
    assert len(changed) == 4
    assert all(v.startswith("https://www.binance.com/") for v in changed.values())
    assert c.urls["api"]["private"].startswith("https://fapi.binance.com/")
    assert c.options["fetchMarkets"]["types"] == ["linear"]
