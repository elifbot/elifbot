# -*- coding: utf-8 -*-
"""yama.py — konsey kararlarını *doğrulanabilir* yamaya çevirir.

Model serbest metin diff üretince yama bozuk çıkıyordu (2026-11-13 koşusu:
karar dosyaları repoda yok, yama.diff içine başka rolün düz metni karıştı).
Bu modül kararları (dosya, eski_kod, yeni_kod) üçlüsü olarak alır ve:

1. dosya gerçekten repoda mı,
2. eski_kod dosyada **tam olarak bir kez** geçiyor mu,
3. sonuç derlenebilir mi (ast.parse)

kontrollerini yapar; geçen karardan `difflib` ile gerçek unified diff üretir.
Geçmeyen karar `uygulanabilir: false` olarak işaretlenir ve yamaya girmez.
"""
from __future__ import annotations

import ast
import difflib
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
# yamanın dokunabileceği kaynak ağacı
KOKLER = ("bot/v9", "bot/acarbot_6bot")
AZAMI_DOSYA = 60


def kaynak_dosyalar() -> list[str]:
    yollar: list[str] = []
    for kok in KOKLER:
        p = KOK / kok
        if not p.exists():
            continue
        for f in sorted(p.rglob("*.py")):
            if "__pycache__" in f.parts or f.name.startswith("test_"):
                continue
            yollar.append(str(f.relative_to(KOK)))
    return yollar[:AZAMI_DOSYA]


def _api(yol: Path) -> list[str]:
    """Dosyanın üst düzey sınıf/fonksiyon adları (satır numarasıyla)."""
    try:
        agac = ast.parse(yol.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    adlar = []
    for d in agac.body:
        if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef)):
            adlar.append(f"def {d.name}():{d.lineno}")
        elif isinstance(d, ast.ClassDef):
            adlar.append(f"class {d.name}:{d.lineno}")
    return adlar


def indeks() -> dict[str, list[str]]:
    return {y: _api(KOK / y) for y in kaynak_dosyalar()}


def indeks_metni(azami_karakter: int = 6000) -> str:
    """Sekretere verilecek 'gerçek dosya + üst düzey API' listesi."""
    satirlar: list[str] = []
    for yol, adlar in indeks().items():
        satirlar.append(f"{yol}: {', '.join(adlar[:14])}")
    metin = "\n".join(satirlar)
    return metin[:azami_karakter]


def yama_uret(dosya: str, eski: str, yeni: str) -> tuple[str, str]:
    """(diff, hata) döndürür; hata boşsa diff uygulanabilir."""
    if not dosya or not eski:
        return "", "dosya/eski_kod boş"
    yol = (KOK / dosya).resolve()
    if not str(yol).startswith(str(KOK)) or not yol.exists():
        return "", f"dosya yok: {dosya}"
    if not yol.suffix == ".py":
        return "", f"kaynak değil: {dosya}"
    metin = yol.read_text(encoding="utf-8")
    eski_n = eski.replace("\r\n", "\n").strip("\n")
    if metin.count(eski_n) != 1:
        return "", f"eski_kod {metin.count(eski_n)} kez geçiyor (tam 1 olmalı)"
    yeni_n = yeni.replace("\r\n", "\n").strip("\n")
    yeni_metin = metin.replace(eski_n, yeni_n, 1)
    try:
        ast.parse(yeni_metin)
    except SyntaxError as e:
        return "", f"yama sonrası sözdizimi hatası: {e.lineno}. satır {e.msg}"
    diff = "".join(difflib.unified_diff(
        metin.splitlines(keepends=True), yeni_metin.splitlines(keepends=True),
        fromfile=f"a/{dosya}", tofile=f"b/{dosya}",
        n=3, lineterm="\n"))
    return diff, ""


def yama_uret_coklu(dosya: str, degisiklikler: list[dict]) -> tuple[str, str]:
    """Aynı dosyada sıralı çoklu değişiklikten tek bir diff üretir."""
    yol = (KOK / dosya).resolve()
    if not dosya or not str(yol).startswith(str(KOK)) or not yol.exists():
        return "", f"dosya yok: {dosya}"
    metin = yol.read_text(encoding="utf-8")
    for i, d in enumerate(degisiklikler, 1):
        eski = str(d.get("eski_kod", "")).replace("\r\n", "\n").strip("\n")
        yeni = str(d.get("yeni_kod", "")).replace("\r\n", "\n").strip("\n")
        if not eski:
            return "", f"{i}. değişiklikte eski_kod boş"
        if metin.count(eski) != 1:
            return "", f"{i}. değişiklik: eski_kod {metin.count(eski)} kez geçiyor"
        metin = metin.replace(eski, yeni, 1)
    try:
        ast.parse(metin)
    except SyntaxError as e:
        return "", f"yama sonrası sözdizimi hatası: {e.lineno}. satır {e.msg}"
    diff = "".join(difflib.unified_diff(
        yol.read_text(encoding="utf-8").splitlines(keepends=True),
        metin.splitlines(keepends=True),
        fromfile=f"a/{dosya}", tofile=f"b/{dosya}", n=3, lineterm="\n"))
    return diff, ""


def diff_uygula_denemesi(diff: str) -> tuple[bool, str]:
    """Üretilen diff'i (kuru) uygulanabilirlik açısından doğrular."""
    if not diff.strip():
        return False, "boş diff"
    if "--- " not in diff or "+++ " not in diff or "@@" not in diff:
        return False, "unified diff biçimi değil"
    return True, ""
