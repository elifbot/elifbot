"""ACARBOT v11 testleri — yazılım doğruluğu. Performans iddiası içermez."""
import math

from bot.v11 import indikator as ind
from bot.v11.kurallar import (GIDIS_DONUS_KOMISYON_USD, NOTIONAL_USD, STOP_FIYAT_ORANI, Kurallar)
from bot.v11.motor import hazirla, simule
from bot.v11.strateji import STRATEJILER, kanit_esik, ema_kesisim
from bot.v11.veri import Bar, Seri, yeniden_ornekle
from bot.v8.config import KasaKurallari


def test_kurallar_v8_ile_ayni():
    k = KasaKurallari()
    assert NOTIONAL_USD == k.notional_per_pozisyon_usd == 500.0
    assert abs(GIDIS_DONUS_KOMISYON_USD - k.gidis_donus_komisyon_usd) < 1e-12
    assert abs(STOP_FIYAT_ORANI - k.stop_fiyat_mesafesi) < 1e-12
    Kurallar().dogrula()


def test_kural_ihlali_reddedilir():
    import pytest
    with pytest.raises(ValueError):
        Kurallar(kaldirac=20).dogrula()


def test_ema_sabit_seri():
    e = ind.ema([5.0] * 30, 9)
    assert all(abs(x - 5.0) < 1e-12 for x in e[8:])


def test_rsi_yukselen_seri_100():
    r = ind.rsi([float(i) for i in range(1, 40)], 14)
    assert r[-1] == 100.0


def test_bb_genislik_sabit_sifir():
    assert ind.bb_genislik([10.0] * 25, 20)[-1] == 0.0


def test_yeniden_ornekle_15dk():
    bars = [Bar(ts=1_700_000_000 + 60 * i, o=1, h=2, l=0.5, c=1.5, v=1) for i in range(30)]
    s = yeniden_ornekle(Seri("X", bars), 15)
    assert len(s.bars) == 2


def _seri(fiyatlar, sem="T"):
    bars = []
    prev = fiyatlar[0]
    for i, p in enumerate(fiyatlar):
        o = prev
        h = max(o, p) * 1.0001
        l = min(o, p) * 0.9999
        bars.append(Bar(ts=1_700_000_000 + 60 * i, o=o, h=h, l=l, c=p, v=1))
        prev = p
    return Seri(sem, bars)


def test_stop_net_minus_10():
    """Sinyal yok; tek işlem, açılıştan sonra fiyat stop'u deler → net ≈ −10 $."""
    base = [100.0] * 80
    s = _seri(base)
    fs = hazirla(s)

    def tek(f, i):
        return 1 if i == 70 else 0

    # giriş bar 71 açılışı = 100; stop = 100·(1−0.019) = 98.1; bar 72 düşük 98.0
    b = s.bars
    b[72].l = 98.0
    b[72].o = 99.0
    sonuc = simule([s], tek)
    assert len(sonuc.islemler) == 1
    t = sonuc.islemler[0]
    assert t.neden == "stop"
    assert abs(t.net - (-10.0)) < 0.02, t.net


def test_sinyal_geleceğe_bakmaz():
    import random
    rnd = random.Random(3)
    p = [100.0]
    for _ in range(200):
        p.append(p[-1] * (1 + rnd.gauss(0, 0.003)))
    s1 = _seri(p)
    f1 = hazirla(s1)
    sig1 = [kanit_esik(f1, i) for i in range(len(p))]
    k = 120
    p2 = p[:k + 1] + [x * 1.5 for x in p[k + 1:]]
    s2 = _seri(p2)
    f2 = hazirla(s2)
    sig2 = [kanit_esik(f2, i) for i in range(len(p2))]
    assert sig1[:k + 1] == sig2[:k + 1]
    s3a = [ema_kesisim(f1, i) for i in range(k + 1)]
    s3b = [ema_kesisim(f2, i) for i in range(k + 1)]
    assert s3a == s3b


def test_strateji_kayitlari():
    assert set(STRATEJILER) == {"ema", "kanit", "fon"}
    assert not math.isnan(STOP_FIYAT_ORANI)
