# -*- coding: utf-8 -*-
"""v9 rejim katmanı testleri — eşik bucket boyundan bağımsız olmalı."""
from __future__ import annotations

from bot.v8.types import Tick
from bot.v9.rejim import Hafiza, Rejim, rejim_sinifla


def _besle(h: Hafiza, fiyatlar, hacim=1000.0, alis_orani=0.6, ts0=1_791_000_000.0):
    for i, p in enumerate(fiyatlar):
        h.ekle(Tick("okx", f"{h.baz}-USDT-SWAP", h.baz, p, hacim, hacim * alis_orani, ts0 + i * 0.5))


def test_trend_yukari():
    h = Hafiza("AAA")
    _besle(h, [100 * (1.0015 ** i) for i in range(200)])   # istikrarlı yükseliş
    r = rejim_sinifla(h)
    assert r.rejim is Rejim.TREND_YUKARI
    assert r.guc >= 1.0


def test_trend_asagi():
    h = Hafiza("BBB")
    _besle(h, [100 * (0.9985 ** i) for i in range(200)])
    assert rejim_sinifla(h).rejim is Rejim.TREND_ASAGI


def test_sikisma_goreli_esik():
    """Oynaklık çökünce sıkışma; eşik göreli olduğu için ölçek değişse de sınıf aynı."""
    for olcek in (1.0, 0.01):
        h = Hafiza("CCC")
        fiyat = 100.0
        seri = []
        for i in range(220):
            # ilk 160 tick: canlı piyasa (±%0.2), sonra: oynaklık çöker (±%0.002)
            genlik = 0.002 if i < 160 else 0.00002
            fiyat *= 1 + genlik * olcek * (1 if i % 2 else -1)
            seri.append(fiyat)
        _besle(h, seri)
        assert rejim_sinifla(h).rejim is Rejim.SIKISMA, f"ölçek {olcek}"


def test_hazir_degilse_sikisma():
    h = Hafiza("DDD")
    _besle(h, [100.0] * 10)
    assert rejim_sinifla(h).rejim is Rejim.SIKISMA
    assert not h.hazir
