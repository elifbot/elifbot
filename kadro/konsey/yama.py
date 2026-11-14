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
            for m in d.body:                      # metotlar da hedef olabilir
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    adlar.append(f"def {m.name}():{m.lineno}")
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


# --- Anlamsal yama: model "tam fonksiyon" yazar, konumu AST bulur ---------------- #

def _dugum_araligi(dosya: str, ad: str) -> tuple[int, int, str] | None:
    """Fonksiyon/metot/sınıf düğümünün (ilk satır, son satır, tür) bilgisi."""
    yol = KOK / dosya
    if not yol.exists():
        return None
    kaynak = yol.read_text(encoding="utf-8")
    try:
        agac = ast.parse(kaynak)
    except SyntaxError:
        return None
    for d in ast.walk(agac):
        if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and d.name == ad:
            ilk = min([d.lineno] + [x.lineno for x in getattr(d, "decorator_list", [])])
            tur = "class" if isinstance(d, ast.ClassDef) else "def"
            return ilk, d.end_lineno or d.lineno, tur
    return None


def yama_uret_fonksiyon(dosya: str, ad: str, yeni_kod: str) -> tuple[str, str]:
    """Modelin yazdığı TAM fonksiyon/sınıf gövdesini yerine koyar.

    Birebir `eski_kod` eşleşmesi istemez: model fonksiyonu bütün yazar, biz
    AST ile kaç satırı kapladığını bulup değiştiririz. Sözdizimi doğrulaması
    yine dosyanın tamamı üzerinde yapılır.
    """
    yol = (KOK / dosya).resolve()
    if not str(yol).startswith(str(KOK)) or not yol.exists():
        return "", f"dosya yok: {dosya}"
    aralik = _dugum_araligi(dosya, ad)
    if not aralik:
        return "", f"düğüm bulunamadı: {ad}"
    ilk, son, _ = aralik
    satirlar = yol.read_text(encoding="utf-8").splitlines(keepends=True)
    yeni = yeni_kod.replace("\r\n", "\n").rstrip("\n").split("\n")
    # modelin ortak sol girintisini at, hedef düğümün girintisini uygula (göreli girinti korunur)
    anlamli = [x for x in yeni if x.strip()]
    ortak = min((len(x) - len(x.lstrip()) for x in anlamli), default=0)
    girinti = satirlar[ilk - 1][: len(satirlar[ilk - 1]) - len(satirlar[ilk - 1].lstrip())]
    yeni_satirlar = [(girinti + x[ortak:] if x.strip() else "\n").rstrip() + "\n" for x in yeni]
    metin = "".join(satirlar[: ilk - 1] + yeni_satirlar + satirlar[son:])
    try:
        ast.parse(metin)
    except SyntaxError as e:
        return "", f"yama sonrası sözdizimi hatası: {e.lineno}. satır {e.msg}"
    diff = "".join(difflib.unified_diff(
        "".join(satirlar).splitlines(keepends=True), metin.splitlines(keepends=True),
        fromfile=f"a/{dosya}", tofile=f"b/{dosya}", n=3, lineterm="\n"))
    return diff, ""


def alan_ekle(dosya: str, sinif: str, alan: str) -> tuple[str, str]:
    """Sınıf gövdesine (metotlardan önce) tek satırlık alan ekler."""
    aralik = _dugum_araligi(dosya, sinif)
    if not aralik:
        return "", f"sınıf bulunamadı: {sinif}"
    ilk, son, tur = aralik
    if tur != "class":
        return "", f"{sinif} sınıf değil"
    yol = KOK / dosya
    satirlar = yol.read_text(encoding="utf-8").splitlines(keepends=True)
    # sınıf gövdesindeki ilk metot/çıkış noktasını bul
    ekle = son
    for i in range(ilk, son):
        s = satirlar[i].strip()
        if s.startswith(("def ", "async def ", "@")):
            ekle = i
            break
    alan_satir = "    " + alan.strip() + "\n"
    metin = "".join(satirlar[:ekle] + [alan_satir] + satirlar[ekle:])
    try:
        agac = ast.parse(metin)
    except SyntaxError as e:
        return "", f"alan eklenemedi: {e.lineno}. satır {e.msg}"
    # alan gerçekten sınıfa mı girdi
    for d in ast.walk(agac):
        if isinstance(d, ast.ClassDef) and d.name == sinif:
            adlar = {t.target.id for t in d.body
                     if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
            beklenen = alan.split(":")[0].strip()
            if beklenen not in adlar:
                return "", f"alan sınıfa girmedi: {beklenen}"
    diff = "".join(difflib.unified_diff(
        "".join(satirlar).splitlines(keepends=True), metin.splitlines(keepends=True),
        fromfile=f"a/{dosya}", tofile=f"b/{dosya}", n=3, lineterm="\n"))
    return diff, ""


def uygula_coklu(dosya: str, islemler: list[dict]) -> tuple[str, str]:
    """Anlamsal işlem listesini (alan_ekle / fonksiyon) sırayla uygular.

    İşlem şemaları:
      {"tur":"alan_ekle","sinif":"Poz","alan":"ters_rejim_sayaci: int = 0"}
      {"tur":"fonksiyon","ad":"_izle","kod":"<tam fonksiyon, def satırından itibaren>"}
    Her adımdan sonra sözdizimi doğrulanır; ilk hata tüm yamayı düşürür.
    """
    yol = (KOK / dosya).resolve()
    if not str(yol).startswith(str(KOK)) or not yol.exists():
        return "", f"dosya yok: {dosya}"
    ozgun = yol.read_text(encoding="utf-8")
    metin = ozgun
    for i, islem in enumerate(islemler, 1):
        tur = str(islem.get("tur", "")).lower()
        try:
            agac = ast.parse(metin)
        except SyntaxError as e:
            return "", f"{i}. işlem öncesi dosya bozuk: {e}"
        satirlar = metin.splitlines(keepends=True)
        if tur in ("alan_ekle", "alan", "field"):
            sinif = str(islem.get("sinif", ""))
            alan = str(islem.get("alan", ""))
            if not sinif or not alan:
                return "", f"{i}. işlem: sınıf/alan boş"
            dugum = next((d for d in ast.walk(agac)
                          if isinstance(d, ast.ClassDef) and d.name == sinif), None)
            if dugum is None:
                return "", f"{i}. işlem: sınıf bulunamadı: {sinif}"
            ekle = dugum.end_lineno
            for j in range(dugum.lineno, dugum.end_lineno):
                if satirlar[j].strip().startswith(("def ", "async def ", "@")):
                    ekle = j
                    break
            metin = "".join(satirlar[:ekle] + ["    " + alan.strip() + "\n"] + satirlar[ekle:])
        elif tur in ("fonksiyon", "metot", "def"):
            ad = str(islem.get("ad", ""))
            kod = str(islem.get("kod", ""))
            if not ad or not kod.strip():
                return "", f"{i}. işlem: ad/kod boş"
            dugum = next((d for d in ast.walk(agac)
                          if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and d.name == ad), None)
            if dugum is None:
                return "", f"{i}. işlem: fonksiyon bulunamadı: {ad}"
            ilk = min([dugum.lineno] + [x.lineno for x in dugum.decorator_list])
            satir_listesi = kod.replace("\r\n", "\n").rstrip("\n").split("\n")
            anlamli = [x for x in satir_listesi if x.strip()]
            ortak = min((len(x) - len(x.lstrip()) for x in anlamli), default=0)
            girinti = satirlar[ilk - 1][: len(satirlar[ilk - 1]) - len(satirlar[ilk - 1].lstrip())]
            yeni = [(girinti + x[ortak:] if x.strip() else "").rstrip() + "\n"
                    for x in satir_listesi]
            metin = "".join(satirlar[: ilk - 1] + yeni + satirlar[dugum.end_lineno:])
        elif tur == "metin":
            eski_kod = str(islem.get("eski_kod", "")).strip("\n")
            yeni_kod = str(islem.get("yeni_kod", "")).strip("\n")
            if metin.count(eski_kod) != 1:
                return "", f"{i}. işlem: eski_kod {metin.count(eski_kod)} kez geçiyor"
            metin = metin.replace(eski_kod, yeni_kod, 1)
        else:
            return "", f"{i}. işlem: bilinmeyen tür: {tur or '(boş)'}"
        try:
            ast.parse(metin)
        except SyntaxError as e:
            return "", f"{i}. işlem sonrası sözdizimi hatası: {e.lineno}. satır {e.msg}"
    diff = "".join(difflib.unified_diff(
        ozgun.splitlines(keepends=True), metin.splitlines(keepends=True),
        fromfile=f"a/{dosya}", tofile=f"b/{dosya}", n=3, lineterm="\n"))
    return diff, ""
