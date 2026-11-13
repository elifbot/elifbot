# -*- coding: utf-8 -*-
"""Konsey testleri — kural vetosu, JSON ayrıştırma, kuru koşu boru hattı."""
from __future__ import annotations

import json

from kadro.konsey import saglayici as sg
from kadro.konsey.tartisma import KURAL_IHLALI, Oturum, kos, _json_ayikla


def test_kural_ihlali_yakalanir():
    for metin in ("teminatı 100 $ yapalım", "kaldıracı 20x'e çıkar", "stopu -30 $ yap",
                  "kasa 2000 olsun", "pozisyon sınırı koy"):
        assert KURAL_IHLALI.search(metin), metin


def test_mesru_oneri_gecER():
    for metin in ("stop bütçesini koruyarak trailing eşiğini 6 $ yap", "rejim eşiğini göreli yap"):
        assert not KURAL_IHLALI.search(metin), metin


def test_json_ayikla_kirli_metin():
    ham = 'İşte karar:\n```json\n{"kararlar":[{"baslik":"x"}]}\n```\nson'
    assert _json_ayikla(ham)["kararlar"][0]["baslik"] == "x"


def test_kuru_kosu_boru_hatti(tmp_path, monkeypatch):
    o = Oturum(gorev="test", saglayicilar=["github"], modeller={"github": [None]},
               butce=sg.Butce(azami_cagri=20))
    kos(o, kuru=True, turlar=3)
    assert o.oneriler and o.itirazlar
    assert len(o.kararlar) >= 1
    assert o.butce.kullanilan <= 20


def test_butce_siniri():
    b = sg.Butce(azami_cagri=2)
    for _ in range(5):
        sg.cagir("github", [{"role": "user", "content": "x"}], butce=b, kuru_kosu=False)
    assert b.kullanilan <= 2


def test_anahtar_yoksa_cagri_yapilmaz(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    b = sg.Butce()
    assert sg.cagir("nvidia", [{"role": "user", "content": "x"}], butce=b) == ""
    assert b.kayitlar[-1].hata == "NVIDIA_API_KEY yok"
