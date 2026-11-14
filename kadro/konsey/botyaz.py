# -*- coding: utf-8 -*-
"""botyaz.py — botu sıfırdan AJANLAR yazar.

Konsey tartışması (roller) tasarımı verir; bu modül tasarımı **dosya dosya**
koda çevirir. Her dosya tek çağrıda yazılır, `ast.parse` ile doğrulanır,
hata varsa hata metniyle birlikte onarım turu yapılır. En sonda gerçek bir
`paper` koşusu çalıştırılır; çalışmıyorsa son hata tekrar onarıma gider.

Küçük yerel modellerle çalışacak şekilde tasarlandı: istemler kısa, şema dar,
her adımda sadece o dosya ve önceki dosyaların *arayüzü* verilir.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import saglayici as sg

KOK = Path(__file__).resolve().parents[2]
PAKET = "bot/konsey_bot"

KURALLAR = (
    "DEĞİŞMEZ KURALLAR: kasa 1.000 $ · pozisyon başına teminat 50 $ · kaldıraç 10x "
    "(500 $ notional) · CROSS teminat · pozisyon limiti YOK · pozisyon başına net −10 $ stop."
)

DOSYALAR: list[tuple[str, str]] = [
    (f"{PAKET}/ayarlar.py",
     "Ayarlar dataclass'ı. Alanlar: kasa_usd=1000.0, teminat_usd=50.0, kaldiraç=10.0, "
     "stop_net_usd=-10.0, komisyon_oran=0.0005, evren_sayisi=6. "
     "Ayrıca `notional_usd` özelliği (teminat*kaldıraç) ve `stop_yuzde` özelliği "
     "(stop_net_usd'in notional'a oranı, yüzde olarak) olsun."),
    (f"{PAKET}/strateji.py",
     "Saf fonksiyonlar: `ema(degerler: list[float], periyot: int) -> float`, "
     "`sinyal(fiyatlar: list[float], hacimler: list[float]) -> int` "
     "(1 al, -1 sat, 0 bekle). Kural: kısa EMA uzun EMA'yı yukarı keserse ve son hacim "
     "ortalamanın üstündeyse 1; tersi -1; yoksa 0. Docstring'li, tip ipuçlu, saf Python."),
    (f"{PAKET}/risk.py",
     "Saf fonksiyonlar: `boyut(ayar, fiyat) -> float` (notinal/fiyat = miktar), "
     "`stop_fiyati(ayar, giris, yon) -> float` (net -10$ kaybı aşmayacak stop; yon +1 long, -1 short), "
     "`pnl(ayar, giris, cikis, yon, miktar) -> float` (komisyon düşülmüş net kâr/zarar)."),
    (f"{PAKET}/motor.py",
     "Sınıf `Motor`: `__init__(ayar)`, `tick(sembol, fiyat, hacim, ts)` ve `ozet()`. "
     "İçinde açık pozisyonlar sözlüğü tut. Girişte sinyal +1/-1 ise pozisyon aç (tek yön, "
     "sembol başına tek pozisyon). Her tick'te açık pozisyonun stop ve pnl kontrolünü yap; "
     "stop tetiklenirse kapat. `ozet()` şunu döndürsün: kapanan işlem sayısı, kazanma oranı, "
     "realize kâr/zarar, komisyon toplamı."),
    (f"{PAKET}/cli.py",
     "`argparse` ile `paper` alt komutu: --dakika (float, varsayılan 5), --sembol (int, 5), "
     "--etiket (str, 'paper'). Sentetik fiyat üret (rastgele yürüyüş, sabit tohum 42), "
     "Motor'u besle, sonuçları `runs/<etiket>/ozet.json` dosyasına yaz ve konsola özet bas. "
     "`if __name__ == '__main__': main()` olsun."),
]


# her dosyada bulunması zorunlu üst düzey adlar (yüzeysel yazımı yakalar)
BEKLENEN: dict[str, tuple[str, ...]] = {
    "ayarlar.py": ("Ayarlar",),
    "strateji.py": ("ema", "sinyal"),
    "risk.py": ("boyut", "stop_fiyati", "pnl"),
    "motor.py": ("Motor",),
    "cli.py": ("main",),
}


def _eksik(dosya: str, kod: str) -> list[str]:
    ad = Path(dosya).name
    beklenen = BEKLENEN.get(ad, ())
    if not beklenen:
        return []
    try:
        agac = ast.parse(kod)
    except SyntaxError:
        return []
    var = {d.name for d in agac.body if isinstance(d, (ast.FunctionDef, ast.ClassDef))}
    return [x for x in beklenen if x not in var]


def _istem(dosya: str, aciklama: str, arayuz: str, hata: str = "") -> list[dict]:
    ek = (f"\nÖNCEKİ DENEME ŞU HATAYI VERDİ, DÜZELT:\n{hata[:600]}\n" if hata else "")
    return [
        {"role": "system", "content":
            "Sen kıdemli bir Python mühendisisin ve sıfırdan bir kripto vadeli işlem botu yazıyorsun. "
            "Yalnızca JSON döndür: {\"kod\": \"<dosyanın tamamı>\"}. Açıklama yazma. " + KURALLAR},
        {"role": "user", "content":
            f"YAZILACAK DOSYA: {dosya}\nGÖREVİ: {aciklama}\n\n"
            f"PROJEDEKİ DİĞER DOSYALARIN ARAYÜZÜ (bunları kullan, yeniden tanımlama):\n{arayuz}\n"
            f"{ek}\n"
            "Kurallar: sadece standart kütüphane kullan; dosya kendi başına import edilebilir olmalı; "
            "içe aktarmalar yalnız standart kütüphane veya yukarıdaki MEVCUT DOSYALAR'dan olsun "
            "(olmayan modül import etme, `version` diye bir modül yok); "
            "Türkçe yorum kısa olsun; `...` ile kısaltma yapma, dosya eksiksiz olsun."},
    ]


def _json(metin: str) -> dict:
    if not metin:
        return {}
    for ham in sorted(re.findall(r"\{.*\}", metin, flags=re.S), key=len, reverse=True):
        for aday in (ham, re.sub(r",(\s*[}\]])", r"\1", ham)):
            try:
                v = json.loads(aday)
                if isinstance(v, dict):
                    return v
            except json.JSONDecodeError:
                continue
    return {}


def _kod(metin: str) -> str:
    """JSON içindeki kodu, JSON yoksa ```python bloğunu alır."""
    v = _json(metin)
    if isinstance(v, dict) and isinstance(v.get("kod"), str) and v["kod"].strip():
        return v["kod"]
    m = re.search(r"```(?:python)?\n(.*?)```", metin or "", flags=re.S)
    return m.group(1) if m else ""


def _arayuz(butce: sg.Butce) -> str:
    """Yazılmış dosyaların üst düzey imzaları (istemde kısa tutulur)."""
    satirlar = []
    for yol, _ in DOSYALAR:
        p = KOK / yol
        if not p.exists():
            continue
        try:
            agac = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        imzalar = []
        for d in agac.body:
            if isinstance(d, ast.FunctionDef):
                imzalar.append(f"def {d.name}(...)")
            elif isinstance(d, ast.ClassDef):
                metotlar = [m.name for m in d.body if isinstance(m, ast.FunctionDef)]
                imzalar.append(f"class {d.name}: {', '.join(metotlar)}")
            elif isinstance(d, ast.AnnAssign) and isinstance(d.target, ast.Name):
                imzalar.append(d.target.id)
        if imzalar:
            satirlar.append(f"{yol}: " + "; ".join(imzalar[:12]))
    var = sorted(p.stem for p in (KOK / PAKET).glob("*.py"))
    satirlar.append(f"MEVCUT DOSYALAR (yalnız bunlardan import edilebilir): {', '.join(var)}")
    return "\n".join(satirlar)



TEK_DOSYA = f"{PAKET}/bot.py"

TEK_SPEC = """Tek dosyalık kripto vadeli işlem botu. Dosya kendi başına `python3 -m bot.konsey_bot.bot paper --dakika 5 --sembol 10 --etiket test` ile çalışmalı.

İçinde SIRASIYLA şunlar olacak:
1) `Ayarlar` dataclass: kasa_usd=1000.0, teminat_usd=50.0, kaldirac=10.0, stop_net_usd=-10.0,
   komisyon_oran=0.0005; `notional_usd` özelliği (teminat*kaldirac), `stop_yuzde` özelliği.
2) `ema(degerler, periyot) -> float` ve `sinyal(fiyatlar, hacimler) -> int` (EMA kesişimi + hacim onayı; 1 al, -1 sat, 0 bekle).
3) `boyut(ayar, fiyat)`, `stop_fiyati(ayar, giris, yon)`, `pnl(ayar, giris, cikis, yon, miktar)`.
4) `class Motor`: `__init__(ayar)`, `tick(sembol, fiyat, hacim, ts)`, `ozet()`.
   Sembol başına tek pozisyon; stop tetiklenince kapat; `ozet()` -> dict:
   {"islem": int, "kazanma_orani": float, "realize_usd": float, "komisyon_usd": float}.
5) `main(argv=None)`: argparse (`paper` alt komutu + --dakika --sembol --etiket), sentetik
   rastgele yürüyüş (tohum 42), Motor'u besle, `runs/<etiket>/ozet.json` yaz, konsola özet bas.
6) `if __name__ == "__main__": main()`

KISITLAR: yalnız standart kütüphane (argparse, json, math, pathlib, random, dataclasses, typing).
Başka proje dosyası import etme. `...` ile kısaltma yapma. Yorumlar kısa ve Türkçe olsun. Kod eksiksiz olsun.
""" + KURALLAR


def tek_yaz(butce: sg.Butce, saglayici: str, model: str, kuru: bool) -> dict:
    """Tüm botu tek dosyada, tek çağrıyla yazdırır; ast doğrular."""
    istem = [
        {"role": "system", "content":
            "Sen kıdemli bir Python mühendisisin. Yalnızca JSON döndür: {\"kod\": \"<tam dosya>\"}. "
            "Açıklama, markdown, ``` yok."},
        {"role": "user", "content": TEK_SPEC},
    ]
    metin = sg.cagir(saglayici, istem, model=model or None, butce=butce, rol="yaz:bot",
                     tur=1, sicaklik=0.2, kuru_kosu=kuru)
    kod = _kod(metin)
    hata = ""
    if not kod.strip():
        hata = "kod boş"
    else:
        try:
            ast.parse(kod)
            eksik = _eksik_adlar(kod)
            if eksik:
                hata = f"eksik adlar: {', '.join(eksik)}"
        except SyntaxError as e:
            hata = f"sözdizimi hatası {e.lineno}. satır: {e.msg}"
    if hata:
        return {"ok": False, "hata": hata, "kod": kod}
    (KOK / TEK_DOSYA).parent.mkdir(parents=True, exist_ok=True)
    (KOK / TEK_DOSYA).write_text(kod if kod.endswith("\n") else kod + "\n", encoding="utf-8")
    return {"ok": True, "kod": kod}


def _eksik_adlar(kod: str) -> list[str]:
    try:
        agac = ast.parse(kod)
    except SyntaxError:
        return []
    var = {d.name for d in agac.body if isinstance(d, (ast.FunctionDef, ast.ClassDef))}
    return [x for x in ("Ayarlar", "ema", "sinyal", "boyut", "stop_fiyati", "pnl", "Motor", "main")
            if x not in var]


def tek_dene(etiket: str = "tek", dakika: float = 2.0, sembol: int = 10) -> dict:
    try:
        r = subprocess.run([sys.executable, "-m", "bot.konsey_bot.bot", "paper",
                            "--dakika", str(dakika), "--sembol", str(sembol), "--etiket", etiket],
                           cwd=KOK, capture_output=True, text=True, timeout=300)
    except Exception as e:                            # noqa: BLE001
        return {"ok": False, "etiket": etiket, "hata": f"{type(e).__name__}: {e}"}
    if r.returncode != 0:
        return {"ok": False, "etiket": etiket, "hata": (r.stderr or r.stdout)[-1500:]}
    ozet = KOK / "runs" / etiket / "ozet.json"
    return {"ok": True, "etiket": etiket, "cikti": r.stdout[-1000:],
            "ozet": json.loads(ozet.read_text()) if ozet.exists() else None}


def tek_bot(butce: sg.Butce, saglayici: str, model: str, tur: int = 5, kuru: bool = False) -> dict:
    """Yaz → çalıştır → hatayı geri besle; tur kadar tekrar."""
    kayit = {"turlar": []}
    sonuc = tek_yaz(butce, saglayici, model, kuru)
    kayit["turlar"].append({"tur": 0, "yazildi": sonuc["ok"], "hata": sonuc.get("hata", "")[:400]})
    if not sonuc["ok"]:
        return kayit
    for i in range(1, tur + 1):
        kosu = tek_dene(f"tek{tur}{i}")
        kayit["turlar"].append({"tur": i, "ok": kosu.get("ok"),
                                "hata": str(kosu.get("hata", ""))[:500]})
        if kosu.get("ok"):
            kayit["son"] = kosu
            return kayit
        istem = [
            {"role": "system", "content":
                "Sen kıdemli bir Python mühendisisin. Aşağıdaki kod çalışırken hata verdi. "
                "Hatayı düzelt ve dosyanın TAMAMINI JSON olarak döndür: {\"kod\": \"<tam dosya>\"}. "
                "Açıklama yazma."},
            {"role": "user", "content":
                f"HATA:\n{kosu.get('hata', '')[:1200]}\n\nKOD:\n{(KOK / TEK_DOSYA).read_text()[:6000]}"},
        ]
        metin = sg.cagir(saglayici, istem, model=model or None, butce=butce, rol=f"onar:{i}",
                         tur=i, sicaklik=0.1, kuru_kosu=kuru)
        kod = _kod(metin)
        try:
            ast.parse(kod)
        except SyntaxError:
            kayit["turlar"].append({"tur": i, "not": "onarım kodu geçersiz, atlandı"})
            continue
        (KOK / TEK_DOSYA).write_text(kod if kod.endswith("\n") else kod + "\n", encoding="utf-8")
    kayit["son"] = {"ok": False}
    return kayit


def yaz(botce: sg.Butce, saglayici: str = "ollama", model: str = "", kuru: bool = False) -> dict:
    """Tüm dosyaları sırayla yazdırır; (rapor) döndürür."""
    rapor = {"yazilan": [], "hatali": [], "kosu": None}
    (KOK / PAKET).mkdir(parents=True, exist_ok=True)
    (KOK / PAKET / "__init__.py").write_text(
        '"""Konsey botu — dosyalar ajanlar tarafından yazıldı."""\n__version__ = "1.0.0"\n',
        encoding="utf-8")
    rapor["yazilan"].append(f"{PAKET}/__init__.py")
    for dosya, aciklama in DOSYALAR:
        istem = _istem(dosya, aciklama, _arayuz(botce))
        metin = sg.cagir(saglayici, istem, model=model or None, butce=botce,
                         rol=f"yaz:{Path(dosya).stem}", tur=1, sicaklik=0.2, kuru_kosu=kuru)
        kod = _kod(metin)
        hata = ""
        if not kod.strip():
            hata = "kod boş döndü"
        else:
            try:
                ast.parse(kod)
            except SyntaxError as e:
                hata = f"sözdizimi: {e.lineno}. satır {e.msg}"
        eksik = _eksik(dosya, kod) if not hata else []
        if eksik:
            hata = f"şu adlar eksik: {', '.join(eksik)}"
        deneme = 1
        while hata and deneme < 3:                   # en fazla 3 deneme
            metin = sg.cagir(saglayici, _istem(dosya, aciklama, _arayuz(botce), hata),
                             model=model or None, butce=botce, rol=f"yaz:{Path(dosya).stem}",
                             tur=2, sicaklik=0.1, kuru_kosu=kuru)
            kod = _kod(metin)
            try:
                ast.parse(kod)
                eksik2 = _eksik(dosya, kod)
                hata = f"şu adlar eksik: {', '.join(eksik2)}" if eksik2 else ""
            except SyntaxError as e:
                hata = f"syntax: {e.lineno}. satır {e.msg}" if kod.strip() else "kod boş"
            deneme += 1
        if hata:
            rapor["hatali"].append({"dosya": dosya, "hata": hata})
            continue
        hedef = KOK / dosya
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_text(kod if kod.endswith("\n") else kod + "\n", encoding="utf-8")
        rapor["yazilan"].append(dosya)
    return rapor


def onar(butce: sg.Butce, kosu: dict, saglayici: str, model: str, kuru: bool,
         onarilacak: list[str] | None = None, tur_sayisi: int = 3) -> dict:
    """Koşu hatasını dosyaya çevirip o dosyayı yeniden yazdırır (en fazla N tur)."""
    kayit = {"turlar": [], "son": kosu}
    for tur in range(1, tur_sayisi + 1):
        if kosu.get("ok") or butce.bitti():
            break
        hata = str(kosu.get("hata", ""))
        adlar = []
        for m in re.finditer(r"konsey_bot/(\w+)\.py", hata + " " + str(kosu.get("iz"))):
            if m.group(1) not in adlar:
                adlar.append(m.group(1))
        if not adlar:                        # iz yoksa cli'yi düzelt
            adlar = ["cli"]
        if onarilacak:                       # yazılamamış dosyalar öncelikli
            adlar = onarilacak + [x for x in adlar if x not in onarilacak]
        for ad in adlar[:3]:
            dosya = f"{PAKET}/{ad}.py"
            aciklama = dict(DOSYALAR).get(dosya, "dosyayı düzelt")
            metin = sg.cagir(saglayici, _istem(dosya, aciklama, _arayuz(butce),
                                               f"KOSU HATASI:\n{hata}"),
                             model=model or None, butce=butce, rol=f"onar:{ad}", tur=tur,
                             sicaklik=0.1, kuru_kosu=kuru)
            kod = _kod(metin)
            try:
                ast.parse(kod)
            except SyntaxError:
                continue
            (KOK / dosya).write_text(kod if kod.endswith("\n") else kod + "\n",
                                     encoding="utf-8")
        kosu = dene(kosu.get("etiket", "botyaz_test"))
        kayit["turlar"].append({"tur": tur, "ok": kosu.get("ok"), "hata": str(kosu.get("hata"))[:400]})
        kayit["son"] = kosu
    return kayit


def dene(etiket: str = "botyaz_test", dakika: float = 1.0, sembol: int = 5) -> dict:
    """Yazılan botu gerçekten çalıştırır.

    Ajanlar `paper` alt komutunu yazmayı unutabiliyor; iki çağrı biçimi denenir.
    """
    for komut in (["paper"], []):
        try:
            r = subprocess.run([sys.executable, "-m", "bot.konsey_bot.cli", *komut,
                                "--dakika", str(dakika), "--sembol", str(sembol),
                                "--etiket", etiket],
                               cwd=KOK, capture_output=True, text=True, timeout=300)
        except Exception as e:                        # noqa: BLE001
            return {"ok": False, "etiket": etiket, "hata": f"{type(e).__name__}: {e}",
                    "iz": ""}
        if r.returncode == 0:
            ozet = KOK / "runs" / etiket / "ozet.json"
            return {"ok": True, "etiket": etiket, "cikti": r.stdout[-800:],
                    "ozet": json.loads(ozet.read_text()) if ozet.exists() else None}
        hata = (r.stderr or r.stdout)[-1500:]
        if "unrecognized arguments" not in hata and "invalid choice" not in hata:
            return {"ok": False, "etiket": etiket, "hata": hata, "cikti": r.stdout[-500:],
                    "iz": hata}
    return {"ok": False, "etiket": etiket, "hata": hata, "cikti": "", "iz": hata}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="botu sıfırdan ajanlara yazdır")
    ap.add_argument("--saglayici", default="ollama")
    ap.add_argument("--model", default=os.environ.get("ACARBOT_MODEL", ""))
    ap.add_argument("--butce", type=int, default=30)
    ap.add_argument("--kuru-kosu", action="store_true")
    ap.add_argument("--etiket", default="botyaz")
    ap.add_argument("--tek", action="store_true", help="tek dosya modu")
    ap.add_argument("--tur", type=int, default=5)
    a = ap.parse_args(argv)

    if a.tek:
        butce = sg.Butce(azami_cagri=a.butce)
        rapor = tek_bot(butce, a.saglayici, a.model, a.tur, a.kuru_kosu)
        d = KOK / "konsey" / a.etiket
        d.mkdir(parents=True, exist_ok=True)
        (d / "botyaz.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        print(json.dumps(rapor, ensure_ascii=False)[:1200])
        return 0 if (rapor.get("son") or {}).get("ok") else 1

    butce = sg.Butce(azami_cagri=a.butce)
    rapor = yaz(butce, a.saglayici, a.model, a.kuru_kosu)
    if not a.kuru_kosu and rapor["yazilan"]:
        kosu = dene(a.etiket)
        rapor["kosu"] = kosu
        if not kosu.get("ok"):
            eksikler = [Path(x["dosya"]).stem for x in rapor["hatali"]]
            rapor["onarim"] = onar(butce, kosu, a.saglayici, a.model, a.kuru_kosu, eksikler)
            rapor["kosu"] = rapor["onarim"]["son"]
    d = KOK / "konsey" / a.etiket
    d.mkdir(parents=True, exist_ok=True)
    (d / "botyaz.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    print(json.dumps({k: (v if k != "hatali" else v) for k, v in rapor.items()},
                     ensure_ascii=False)[:1500])
    return 0 if rapor["yazilan"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
