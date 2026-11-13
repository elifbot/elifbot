# -*- coding: utf-8 -*-
"""v9 motor testleri — kural ve muhasebe."""
from __future__ import annotations

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOK / "bot" / "tools"))

from bot.v8.broker import SimuleBorsa
from bot.v8.cli import sentetik_evren
from bot.v8.config import KasaKurallari
from bot.v8.feed import SentetikBesleme
from bot.v9.motor import MotorV9, V9Ayarlari


def _kos(dakika=10, sembol=30, seed=7):
    k = KasaKurallari()
    isimler = [f"S{i}-USDT-SWAP" for i in range(sembol)]
    sim = SimuleBorsa(ad="okx", kurallar=k, kasa_usd=k.baslangic_kasa_usd)
    b = SentetikBesleme(isimler, seed=seed, bucket_sn=0.5, baslangic_ts=1_791_000_000.0)
    sim.enstrumanlar = sentetik_evren(isimler, b.fiyatlar())
    m = MotorV9(borsa=sim, kurallar=k, ayar=V9Ayarlari())
    asiri = 0.0
    for _ in range(int(dakika * 60 / 0.5)):
        for t in b.sonraki():
            m.tick(t)
        asiri = max(asiri, sim.kullanilan_teminat() - (sim.kasa_usd + sim.acik_pnl()))
    return sim, m, asiri


def test_kural_siniri_asilmaz():
    """Kullanılan teminat hiçbir an özkaynağı aşmaz; tasfiye olmaz."""
    sim, m, asiri = _kos()
    assert asiri <= 0.01, f"teminat özkaynağı aştı: {asiri:.2f}"
    assert sim.tasfiye_sayisi == 0


def test_en_kotu_islem_butce_icinde():
    sim, m, _ = _kos()
    if not m.kapananlar:
        return
    kotu = min(k.net_usd for k in m.kapananlar)
    assert kotu >= -11.0, f"en kötü işlem {kotu:.2f} $ — stop bütçesi aşıldı"


def test_net_muhasebesi_fiyatla_uyumlu():
    """Kaydedilen net, giriş/çıkış fiyatından hesaplananla aynı olmalı (eski hata)."""
    sim, m, _ = _kos()
    for k in m.kapananlar:
        brut = k.yon.value * (k.cikis / k.giris - 1.0) * 500.0
        assert abs(k.net_usd - (brut - 0.5)) < 1.0, f"{k.sembol}: {k.net_usd} vs {brut - 0.5}"


def test_her_pozisyonun_stopu_var():
    """Açık her pozisyonun borsada duran reduceOnly stop emri olmalı."""
    sim, m, _ = _kos()
    for sembol, poz in m.pozlar.items():
        assert poz.stop_emir_id, f"{sembol} stopsuz açılmış"
        assert poz.stop_emir_id in sim.duran
