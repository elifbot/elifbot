# -*- coding: utf-8 -*-
"""yama.py — kararların makine doğrulaması."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kadro.konsey import yama as ym


def test_gecerli_yama_diff_uretir():
    diff, hata = ym.yama_uret("bot/v9/rejim.py", "class Hafiza:", "class Hafiza:  # doğrulama")
    assert not hata, hata
    assert diff.startswith("--- a/bot/v9/rejim.py")
    assert "class Hafiza:  # doğrulama" in diff
    assert ym.diff_uygula_denemesi(diff)[0]


def test_olmayan_dosya_reddedilir():
    diff, hata = ym.yama_uret("app/executor.py", "x = 1", "x = 2")
    assert not diff and "dosya yok" in hata


def test_eski_kod_bulunamazsa_reddedilir():
    diff, hata = ym.yama_uret("bot/v9/rejim.py", "asla_var_olmayan_satir()", "y = 2")
    assert not diff and "kez geçiyor" in hata


def test_sozdizimi_bozuk_yama_reddedilir():
    diff, hata = ym.yama_uret("bot/v9/rejim.py", "class Hafiza:", "def (, bozuk")
    assert not diff and "sözdizimi" in hata


def test_indeks_gercek_dosyalari_listeler():
    metin = ym.indeks_metni()
    assert "bot/v9/motor.py" in metin
    assert "class MotorV9" in metin
