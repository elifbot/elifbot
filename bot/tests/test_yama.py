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


def test_coklu_degisiklik_sirali_uygulanir():
    p = ym.KOK / "bot/v9/sinyaller.py"
    m = p.read_text(encoding="utf-8")
    i = m.index("def komite(")
    assert i > 0
    diff, hata = ym.yama_uret_coklu("bot/v9/sinyaller.py", [
        {"eski_kod": "class Aday:", "yeni_kod": "class Aday:  # test1"},
        {"eski_kod": "class Aday:  # test1", "yeni_kod": "class Aday:  # test2"},
    ])
    assert not hata, hata
    assert "+class Aday:  # test2" in diff


def test_coklu_degisiklik_bulunamayan_parca_reddedilir():
    diff, hata = ym.yama_uret_coklu("bot/v9/sinyaller.py", [
        {"eski_kod": "yok_boyle_satir()", "yeni_kod": "x = 1"}])
    assert not diff and "kez geçiyor" in hata


def test_kanitten_dosya_cikarimi():
    import re
    kanit = "bot/v9/motor.py:140-144"
    m = re.search(r"(bot/[\w/]+\.py)", kanit)
    assert m and m.group(1) == "bot/v9/motor.py"
    diff, hata = ym.yama_uret(m.group(1), "class Poz:", "class Poz:  # x")
    assert not hata, hata
    assert "+class Poz:  # x" in diff


def test_alternatif_sema_kabul_edilir():
    from kadro.konsey.tartisma import _karar_listesi, _karar_normalize
    veri = {"karar": "ONAYLANDI", "uygulanabilir_yama": [
        {"dosya": "bot/v9/motor.py", "hedef": "class Poz", "islem": "ekle",
         "kod": "ters_rejim_sayaci: int = 0"}]}
    liste = _karar_listesi(veri)
    assert len(liste) == 1
    k = _karar_normalize(liste[0])
    assert k["dosya"] == "bot/v9/motor.py"
    assert k["yeni_kod"] == "ters_rejim_sayaci: int = 0"
    assert k["kanit"].startswith("bot/v9/motor.py")


def test_ic_ice_sema_cozulur():
    from kadro.konsey.tartisma import _karar_listesi, _karar_normalize
    veri = {"karar": {"durum": "UYGULANABİLİR", "dosya": "bot/v9/motor.py",
                      "degisiklikler": [
                          {"hedef": "Poz dataclass", "islem": "EKLE",
                           "kod": "ters_rejim_sayaci: int = 0"},
                          {"hedef": "_izle", "islem": "MANTIK_EKLE",
                           "kod": "if ters:\n    pos.ters_rejim_sayaci += 1"}]}}
    liste = _karar_listesi(veri)
    assert len(liste) == 2
    k = _karar_normalize(liste[1])
    assert k["dosya"] == "bot/v9/motor.py"
    assert "ters_rejim_sayaci" in k["yeni_kod"]
    # ikinci biçim: {"yama": {...}}
    assert len(_karar_listesi({"yama": {"degisiklikler": liste}})) == 2
