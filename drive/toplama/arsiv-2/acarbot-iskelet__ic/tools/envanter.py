#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ACARBOT arşiv envanteri + sır (API anahtarı) taraması
------------------------------------------------------
Kullanım (Windows PowerShell / CMD):
    python envanter.py "C:\\bot-arsiv"

Ne yapar?
  1) Klasörü ve içindeki ZIP'leri (iç içe zip dahil) salt-okunur tarar.
  2) Her dosya için: boyut, tarih, SHA-256, satır sayısı, sürüm işaretleri,
     strateji/özellik anahtar kelimeleri çıkarır.
  3) Birebir aynı dosyaları (aynı hash) işaretler.
  4) Olası API anahtarı / token / şifre arar. Bulguları MASKELENMİŞ yazar
     (değerin tamamı hiçbir dosyaya yazılmaz).

Çıktılar (klasörün yanında "cikti" klasörüne yazılır):
    envanter.csv         -> tüm dosyalar (bunu bana yükleyebilirsiniz)
    gizli_bulgular.csv   -> maskelenmiş sır bulguları
    ozet.txt             -> kısa özet

Orijinal dosyalara DOKUNMAZ. Sadece standart Python kütüphanesi kullanır.
"""
import csv
import hashlib
import io
import os
import re
import sys
import zipfile
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

METIN_UZANTILAR = {
    ".html", ".htm", ".py", ".js", ".ts", ".json", ".txt", ".md", ".env",
    ".yml", ".yaml", ".ini", ".cfg", ".toml", ".ipynb", ".csv", ".sh", ".bat",
    ".ps1", ".mjs", ".jsx", ".tsx", ".conf", ".log", "",
}
ATLANAN_KLASORLER = {".git", "node_modules", "__pycache__", ".venv", "venv"}
MAKS_OKUMA = 60 * 1024 * 1024        # tek dosya için üst sınır (60 MB)
MAKS_ZIP_DERINLIK = 4

# ----------------------------- özellik anahtar kelimeleri -----------------------------
OZELLIKLER = {
    "binance": r"binance|fapi\.binance",
    "okx": r"\bokx\b|okx\.com",
    "bybit": r"bybit",
    "ccxt": r"\bccxt\b",
    "freqtrade": r"freqtrade",
    "websocket": r"websocket|wss://",
    "emir_gonderme": r"create_order|new_order|/order\b|placeOrder|futures_create_order",
    "api_anahtari_kullanimi": r"api[_-]?key|apiKey|secret[_-]?key",
    "testnet": r"testnet",
    "kill_switch": r"kill.?switch|killswitch",
    "gunluk_zarar_limiti": r"gunlukZarar|daily.?loss|günlük zarar",
    "drawdown_limiti": r"maxDd|max.?drawdown",
    "dca": r"\bdca\b|safety.?order",
    "atr_stop": r"\batr\b",
    "trailing": r"trailing",
    "breakeven": r"breakeven|başabaş|basabas",
    "funding": r"funding|fonlama",
    "backtest": r"backtest|geri.?test",
    "walk_forward": r"walk.?forward",
    "monte_carlo": r"monte.?carlo",
    "telegram": r"telegram",
    "haber_ajani": r"\bnews\b|haber",
    "open_interest": r"open.?interest|openInterest",
    "likidasyon_akisi": r"liquidation|likidasyon",
    "orderbook": r"order.?book|\bdepth\b",
    "maker_limit": r"post.?only|\bmaker\b|limit.?order",
    "korelasyon": r"correlation|korelasyon",
    "test_kodu": r"\bunittest\b|\bpytest\b|def test_",
}
STRATEJILER = {
    "trend": r"strateji\s*[:=]\s*['\"]trend",
    "rsirev": r"rsirev",
    "macd": r"['\"]macd['\"]",
    "bollkir": r"bollkir",
    "bolldon": r"bolldon",
    "confluence": r"confluence",
}
OZELLIK_RE = {k: re.compile(v, re.I) for k, v in OZELLIKLER.items()}
STRATEJI_RE = {k: re.compile(v, re.I) for k, v in STRATEJILER.items()}

SURUM_RE = re.compile(r"(?:\bSURUM\b|\bVERSION\b|\bversion\b)\s*[:=]\s*['\"]?([0-9][0-9A-Za-z._-]{0,12})", re.I)
BASLIK_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)

# ----------------------------- sır desenleri -----------------------------
SIR_DESENLERI = [
    ("PRIVATE_KEY_BLOKU", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS_ERISIM_ANAHTARI", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("TELEGRAM_BOT_TOKEN", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("OPENAI_ANTHROPIC_TIPI_ANAHTAR", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("BORSA_ANAHTARI_64", re.compile(
        r"(?i)(?:api[_-]?key|api[_-]?secret|secret[_-]?key|apikey|secret)\W{1,6}([A-Za-z0-9]{64})\b")),
    ("GENEL_ANAHTAR_ATAMASI", re.compile(
        r"(?i)\b(?:api[_-]?key|api[_-]?secret|secret(?:[_-]?key)?|passphrase|password|parola|sifre|token)\b"
        r"\s*[:=]\s*['\"]([A-Za-z0-9_\-/+=.]{16,})['\"]")),
]
# bariz yer tutucular (yanlış alarm azaltma)
YER_TUTUCU = re.compile(r"(?i)^(your|xxx|test|example|changeme|placeholder|<|\*+|\.{3}|api_?key|secret|token)")


def maskele(deger):
    d = str(deger)
    if len(d) <= 8:
        return "*" * len(d)
    return d[:4] + "…" + d[-2:] + f" (uzunluk {len(d)})"


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def metin_coz(b):
    for kodlama in ("utf-8", "cp1254", "latin-1"):
        try:
            return b.decode(kodlama)
        except Exception:
            continue
    return b.decode("utf-8", errors="ignore")


def analiz_et(yol, b, mtime, kayitlar, bulgular):
    uzanti = os.path.splitext(yol.split("::")[-1])[1].lower()
    h = sha256(b)
    kayit = {
        "yol": yol, "ad": os.path.basename(yol.split("::")[-1]),
        "uzanti": uzanti, "boyut_kb": round(len(b) / 1024, 1),
        "degisim_tarihi": mtime, "sha256": h[:16],
        "satir": "", "surum_isaretleri": "", "baslik": "",
        "stratejiler": "", "ozellikler": "", "ozellik_sayisi": "",
        "ayni_dosya": "", "gizli_bulgu_sayisi": 0,
    }
    if uzanti in METIN_UZANTILAR and len(b) <= MAKS_OKUMA:
        t = metin_coz(b)
        kayit["satir"] = t.count("\n") + 1
        kayit["surum_isaretleri"] = ",".join(sorted(set(SURUM_RE.findall(t)))[:6])
        m = BASLIK_RE.search(t)
        if m:
            kayit["baslik"] = re.sub(r"\s+", " ", m.group(1)).strip()[:90]
        kayit["stratejiler"] = ",".join(k for k, r in STRATEJI_RE.items() if r.search(t))
        oz = [k for k, r in OZELLIK_RE.items() if r.search(t)]
        kayit["ozellikler"] = ",".join(oz)
        kayit["ozellik_sayisi"] = len(oz)

        sayac = 0
        for tur, desen in SIR_DESENLERI:
            for m in desen.finditer(t):
                deger = m.group(1) if m.groups() else m.group(0)
                if YER_TUTUCU.match(deger):
                    continue
                satir_no = t.count("\n", 0, m.start()) + 1
                bulgular.append({
                    "yol": yol, "satir_no": satir_no, "tur": tur,
                    "maskeli_deger": maskele(deger),
                })
                sayac += 1
                if sayac >= 25:
                    break
            if sayac >= 25:
                break
        kayit["gizli_bulgu_sayisi"] = sayac
    kayitlar.append(kayit)


def zip_tara(veri, on_ek, mtime, kayitlar, bulgular, derinlik):
    if derinlik > MAKS_ZIP_DERINLIK:
        return
    try:
        z = zipfile.ZipFile(io.BytesIO(veri))
    except Exception:
        return
    with z:
        for bilgi in z.infolist():
            if bilgi.is_dir():
                continue
            if bilgi.file_size > MAKS_OKUMA:
                continue
            try:
                b = z.read(bilgi)
            except Exception:
                continue
            yol = on_ek + "::" + bilgi.filename
            try:
                dt = datetime(*bilgi.date_time).strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt = mtime
            if bilgi.filename.lower().endswith(".zip"):
                zip_tara(b, yol, dt, kayitlar, bulgular, derinlik + 1)
            else:
                analiz_et(yol, b, dt, kayitlar, bulgular)


def main():
    if len(sys.argv) < 2:
        print('Kullanım: python envanter.py "C:\\bot-arsiv"')
        sys.exit(1)
    kok = os.path.abspath(sys.argv[1])
    if not os.path.isdir(kok):
        print("Klasör bulunamadı:", kok)
        sys.exit(1)

    kayitlar, bulgular = [], []
    sayi = 0
    for dizin, altlar, dosyalar in os.walk(kok):
        altlar[:] = [a for a in altlar if a not in ATLANAN_KLASORLER]
        for ad in dosyalar:
            tam = os.path.join(dizin, ad)
            goreli = os.path.relpath(tam, kok)
            try:
                mt = datetime.fromtimestamp(os.path.getmtime(tam)).strftime("%Y-%m-%d %H:%M")
                boyut = os.path.getsize(tam)
                if boyut > 400 * 1024 * 1024:
                    continue
                with open(tam, "rb") as f:
                    b = f.read()
            except Exception as e:
                print("Okunamadı:", goreli, e)
                continue
            sayi += 1
            if ad.lower().endswith(".zip"):
                zip_tara(b, goreli, mt, kayitlar, bulgular, 1)
            else:
                analiz_et(goreli, b, mt, kayitlar, bulgular)
            if sayi % 50 == 0:
                print(f"... {sayi} dosya tarandı")

    # birebir aynı dosyalar
    ilk = {}
    for k in kayitlar:
        h = k["sha256"]
        if h in ilk and h:
            k["ayni_dosya"] = "KOPYA -> " + ilk[h]
        else:
            ilk[h] = k["yol"]

    cikti = os.path.join(os.path.dirname(kok) or ".", "cikti")
    os.makedirs(cikti, exist_ok=True)

    alanlar = ["yol", "ad", "uzanti", "boyut_kb", "degisim_tarihi", "sha256", "satir",
               "baslik", "surum_isaretleri", "stratejiler", "ozellik_sayisi", "ozellikler",
               "gizli_bulgu_sayisi", "ayni_dosya"]
    kayitlar.sort(key=lambda k: (k["degisim_tarihi"], k["yol"]))
    with open(os.path.join(cikti, "envanter.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=alanlar, extrasaction="ignore")
        w.writeheader()
        w.writerows(kayitlar)

    with open(os.path.join(cikti, "gizli_bulgular.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["yol", "satir_no", "tur", "maskeli_deger"])
        w.writeheader()
        w.writerows(bulgular)

    benzersiz = len({k["sha256"] for k in kayitlar})
    gizli_dosya = len({b["yol"] for b in bulgular})
    ozet = [
        f"Taranan klasör         : {kok}",
        f"Toplam kayıt (zip içi dahil): {len(kayitlar)}",
        f"Benzersiz içerik       : {benzersiz}",
        f"Birebir kopya          : {len(kayitlar) - benzersiz}",
        f"Olası sır bulunan dosya: {gizli_dosya}  (toplam bulgu: {len(bulgular)})",
        "",
        "SONRAKİ ADIM: gizli_bulgular.csv içindeki anahtarları borsadan İPTAL EDİP yenileyin,",
        "sonra GitHub'a yüklemeden önce o dosyalardaki anahtarları silin.",
    ]
    with open(os.path.join(cikti, "ozet.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(ozet))
    print("\n".join(ozet))
    print("\nÇıktılar:", cikti)


if __name__ == "__main__":
    main()
