# -*- coding: utf-8 -*-
"""v9 sinyal komitesi testleri."""
from __future__ import annotations

from bot.v8.types import Tick, Yon
from bot.v9.rejim import Hafiza, Rejim, RejimSonucu, rejim_sinifla
from bot.v9.sinyaller import komite, hacim_kirilim


def _hafiza(baz="AAA", taban=100.0, adet=120, artis=0.0, son_hacim=None):
    h = Hafiza(baz)
    ts = 1_791_000_000.0
    for i in range(adet):
        p = taban * (1 + artis) ** i
        h.ekle(Tick("okx", f"{baz}-USDT-SWAP", baz, p, 1000.0, 600.0, ts + i * 0.5))
    if son_hacim is not None:
        p = taban * (1 + artis) ** adet * 1.01
        h.ekle(Tick("okx", f"{baz}-USDT-SWAP", baz, p, son_hacim, son_hacim * 0.8, ts + adet * 0.5))
    return h


def test_hacim_kirilimi_long():
    h = _hafiza(artis=0.0005, son_hacim=20_000.0)      # hacim 20x, fiyat yukarı kırdı
    r = RejimSonucu(Rejim.TREND_YUKARI, 1.5, h.oynaklik)
    a = hacim_kirilim(h, r, 1_791_000_100.0)
    assert a is not None and a.yon is Yon.LONG and a.skor >= 0.5


def test_zayif_hacim_sinyal_vermez():
    h = _hafiza(artis=0.0005, son_hacim=1_000.0)        # hacim artmadı
    r = RejimSonucu(Rejim.TREND_YUKARI, 1.5, h.oynaklik)
    assert hacim_kirilim(h, r, 1_791_000_100.0) is None


def test_rejim_kapisi():
    """Sıkışmada parabolik dönüş dedektörü konuşamaz."""
    h = _hafiza(artis=0.0005, son_hacim=20_000.0)
    k = komite(h, RejimSonucu(Rejim.SIKISMA, 0.0, h.oynaklik), 1_791_000_100.0)
    assert all("parabolik" not in m for m in k.oylar)


def test_celiski_ise_islem_yok():
    """Aynı anda iki zıt sinyal varsa komite boş döner."""
    h = Hafiza("ZZZ")
    ts = 1_791_000_000.0
    # testere: tepe ve dip arasında, delta aşırı alım
    for i in range(150):
        p = 100.0 + (0.3 if i % 2 else -0.3)
        h.ekle(Tick("okx", "ZZZ-USDT-SWAP", "ZZZ", p, 1000.0, 900.0, ts + i * 0.5))
    r = rejim_sinifla(h)
    k = komite(h, r, ts + 100)
    if k.celiski:
        assert k.aday is None
    else:                                   # çelişki yoksa da karar tutarlı olmalı
        assert k.aday is None or k.aday.skor >= 0.55
