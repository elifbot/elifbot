# -*- coding: utf-8 -*-
"""saglayici.py — OpenAI-uyumlu tek istemci, üç sağlayıcı.

Tasarım kararları:
  * Yalnızca standart kütüphane (urllib) — CI'da ek bağımlılık yok.
  * 429/5xx: üstel geri çekilme (Retry-After'a saygı).
  * Girdi token sınırı 8K: mesajlar `esik_karakter` ile kırpılır (~28.000 karakter).
  * Çağrı bütçesi: günlük kotayı (150/gün) yakmamak için sert sayaç.
  * Anahtar loglanmaz; yalnızca varlığı raporlanır.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

ESIK_KARAKTER = int(os.environ.get("ACARBOT_ESIK") or 26_000)          # ~7.4K token; 8K girdi sınırının altında güvenli


@dataclass(frozen=True)
class Saglayici:
    ad: str
    taban: str
    anahtar_env: str | None
    varsayilan_model: str
    yedek_model: str = ""

    def anahtar(self) -> str:
        return os.environ.get(self.anahtar_env, "") if self.anahtar_env else ""


SAGLAYICILAR: dict[str, Saglayici] = {
    "github": Saglayici("github", "https://models.github.ai/inference", "GITHUB_TOKEN",
                        "openai/gpt-4.1-mini", "openai/gpt-4o-mini"),
    "nvidia": Saglayici("nvidia", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY",
                        (os.environ.get("ACARBOT_MODEL") or "google/gemma-4-31b-it"), "meta/llama-3.3-70b-instruct"),
    "ollama": Saglayici("ollama", "http://localhost:11434/v1", None, "llama3.1", ""),
}


@dataclass
class Cagri:
    saglayici: str
    model: str
    rol: str
    tur: int
    istem_karakter: int
    yanit: str
    saniye: float
    hata: str = ""


@dataclass
class Butce:
    azami_cagri: int = 24
    azami_saniye: float = float(os.environ.get("ACARBOT_SURE") or 3300)
    kullanilan: int = 0
    denemeler: int = 0
    baslangic: float = field(default_factory=time.time)
    kayitlar: list[Cagri] = field(default_factory=list)

    kilit: object = field(default_factory=threading.Lock, repr=False)

    def bitti(self) -> bool:
        return (self.kullanilan >= self.azami_cagri
                or self.denemeler >= self.azami_cagri * 6      # başarısız denemeler de sayılır
                or (time.time() - self.baslangic) > self.azami_saniye)


def _kirp(mesajlar: list[dict], esik: int = ESIK_KARAKTER) -> list[dict]:
    """Toplam karakteri sınıra indirir: en uzun kullanıcı mesajından kırpar."""
    toplam = sum(len(m["content"]) for m in mesajlar)
    if toplam <= esik:
        return mesajlar
    fazla = toplam - esik
    cikti = []
    for m in mesajlar:
        c = m["content"]
        if fazla > 0 and len(c) > 2000:
            kes = min(fazla, len(c) - 2000)
            c = c[: len(c) - kes] + "\n…[kırpıldı]"
            fazla -= kes
        cikti.append({"role": m["role"], "content": c})
    return cikti


def cagir(saglayici: str, mesajlar: list[dict], model: str | None = None,
          butce: Butce | None = None, rol: str = "", tur: int = 1,
          sicaklik: float = 0.3, azami_token: int = int(os.environ.get("ACARBOT_TOKEN") or 1200),
          kuru_kosu: bool = False, otomatik_model: bool = True) -> str:
    """Tek chat-completions çağrısı.

    Model kimliği koda gömülmez: `/models` ucundan keşfedilir, sonra istenen model,
    keşfedilen model, varsayılan ve yedek sırayla denenir. Sağlayıcılar modelleri
    emekliye ayırdığı için (NVIDIA 410 Gone) bu şart.
    """
    s = SAGLAYICILAR[saglayici]
    butce = butce or Butce()
    mesajlar = _kirp(mesajlar)
    istem_karakter = sum(len(m["content"]) for m in mesajlar)

    if kuru_kosu:
        yanit = _kuru_yanit(rol, tur, istem_karakter)
        butce.kayitlar.append(Cagri(saglayici, model or s.varsayilan_model, rol, tur,
                                    istem_karakter, yanit, 0.0))
        butce.kullanilan += 1
        return yanit

    if butce.bitti():
        butce.kayitlar.append(Cagri(saglayici, model or _CALISAN.get(saglayici, "?"), rol, tur,
                                    istem_karakter, "", 0.0, "bütçe/süre doldu — çağrı yapılmadı"))
        return ""
    if s.anahtar_env and not s.anahtar():
        butce.kayitlar.append(Cagri(saglayici, model or s.varsayilan_model, rol, tur,
                                    istem_karakter, "", 0.0, f"{s.anahtar_env} yok"))
        return ""

    adaylar: list[str] = []
    if saglayici in _CALISAN:                 # bu sağlayıcıda çalışan model biliniyor
        adaylar.append(_CALISAN[saglayici])
    if model and model not in adaylar:
        adaylar.insert(0, model)
    if otomatik_model and not adaylar:
        adaylar.extend(model_adaylari(saglayici, 4))
    for y in (s.varsayilan_model, s.yedek_model):
        if y and y not in adaylar:
            adaylar.append(y)

    hatalar: list[str] = []
    adaylar = [m for m in adaylar if m]      # boş model adı gönderme (HTTP 400)
    for m in adaylar:
        if butce.bitti():
            hatalar.append("bütçe doldu")
            break
        metin, hata = _tek_cagri(s, m, mesajlar, butce, rol, tur,
                                 sicaklik, azami_token, istem_karakter)
        if metin:
            _CALISAN[saglayici] = m
            return metin
        hatalar.append(f"{m} → {hata}")
    son_hata = " | ".join(hatalar) if hatalar else "aday yok"
    butce.kayitlar.append(Cagri(saglayici, adaylar[0] if adaylar else "?", rol, tur,
                                istem_karakter, "", 0.0, son_hata[:220]))
    return ""


def _tek_cagri(s: "Saglayici", model: str, mesajlar: list[dict], butce: "Butce", rol: str,
               tur: int, sicaklik: float, azami_token: int, istem_karakter: int):
    anahtar = s.anahtar()
    hac = {"Content-Type": "application/json"}
    if anahtar:
        hac["Authorization"] = f"Bearer {anahtar}"
    govde = json.dumps({"model": model, "messages": mesajlar,
                        "temperature": sicaklik, "max_tokens": azami_token}).encode()
    son_hata = ""
    for deneme in range(3):
        t0 = time.time()
        try:
            istek = urllib.request.Request(f"{s.taban}/chat/completions", data=govde,
                                           headers=hac, method="POST")
            zaman = float(os.environ.get("ACARBOT_ZAMAN_ASIMI") or 300)
            with urllib.request.urlopen(istek, timeout=zaman) as y:
                ham = y.read().decode(errors="ignore")
            try:
                d = json.loads(ham)
            except json.JSONDecodeError:
                return "", f"JSON değil ({len(ham)} bayt): {ham[:120]!r}"
            if not d.get("choices"):
                return "", f"choices yok ({len(ham)} bayt): {ham[:120]!r}"
            metin = (d.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            butce.kullanilan += 1
            butce.kayitlar.append(Cagri(s.ad, model, rol, tur, istem_karakter,
                                        metin, round(time.time() - t0, 1)))
            return metin, ""
        except urllib.error.HTTPError as e:
            butce.denemeler += 1
            try:
                govde_hata = e.read().decode()[:200]
            except Exception:
                govde_hata = ""
            son_hata = f"HTTP {e.code} {govde_hata}"[:200]
            if e.code in (429, 500, 502, 503, 504) and deneme < 2:
                bekle = float(e.headers.get("Retry-After") or (2 ** deneme * 5))
                time.sleep(min(bekle, 60))
                continue
            break
        except Exception as e:                       # ağ/timeout
            butce.denemeler += 1
            son_hata = f"{type(e).__name__}: {e}"[:120]
            if isinstance(e, (TimeoutError, socket.timeout)) and deneme < 1:
                continue                             # bayat bağlantı: taze istek genelde hızlı döner
            if deneme < 2:
                time.sleep(2 ** deneme * 3)
                continue
            break
    return "", son_hata


def modeller_listele(saglayici: str, zaman_asimi: int = 30) -> list[str]:
    """Sağlayıcının /models ucundan geçerli model kimliklerini çeker.

    Neden: sağlayıcılar model emekliye ayırıyor (örn. NVIDIA 410 Gone). Kimlikleri
    koda gömmek yerine çalışma anında soruyoruz.
    """
    s = SAGLAYICILAR[saglayici]
    anahtar = s.anahtar()
    if s.anahtar_env and not anahtar:
        return []
    hac = {"Accept": "application/json"}
    if anahtar:
        hac["Authorization"] = f"Bearer {anahtar}"
    try:
        istek = urllib.request.Request(f"{s.taban}/models", headers=hac)
        with urllib.request.urlopen(istek, timeout=zaman_asimi) as y:
            d = json.loads(y.read().decode(errors="ignore"))
    except Exception:
        return []
    kimlikler = [m.get("id", "") for m in (d.get("data") or d.get("models") or []) if isinstance(m, dict)]
    return [k for k in kimlikler if k]


# sohbet modeli olduğu neredeyse kesin olan ad parçaları (öncelik sırasıyla)
IYI = ("nemotron", "llama-3.3", "llama-3.1", "deepseek", "qwen", "mistral", "gpt", "phi",
       "gemma", "instruct", "chat")
KOTU = ("embed", "rerank", "guard", "bge", "e5-", "clip", "vision-only", "safety")

# çalışan modeli süreç içinde hatırla: her rol için yeniden keşif yapılmasın
_CALISAN: dict[str, str] = {"nvidia": (os.environ.get("ACARBOT_MODEL") or "google/gemma-4-31b-it")}


def model_adaylari(saglayici: str, en_fazla: int = 4) -> list[str]:
    """`/models` listesinden sohbet için makul adayları öncelik sırasıyla döndürür."""
    mevcut = modeller_listele(saglayici)
    if not mevcut:
        return []
    puanli = []
    for k in mevcut:
        alt = k.lower()
        if any(x in alt for x in KOTU):
            continue
        puan = sum(10 - i for i, x in enumerate(IYI) if x in alt)
        if puan:
            puanli.append((puan, k))
    puanli.sort(reverse=True)
    return [k for _, k in puanli[:en_fazla]]


def _kuru_yanit(rol: str, tur: int, istem_karakter: int) -> str:
    """Ağ yokken boru hattını doğrulamak için deterministik yanıt."""
    if tur == 1:
        return (f"ÖNERİ ({rol}): Kanıta göre iki nokta öne çıkıyor. "
                f"(1) Stop bütçesi -10 $ iken komisyon 0.50 $; mesafe %1.90 olmalı. "
                f"(2) Rejim kapısı olmadan aynı eşik her piyasada çalışmaz. "
                f"Girdi {istem_karakter} karakterdi.")
    if tur == 2:
        return (f"İTİRAZ ({rol}): Diğer önerilerdeki 'eşiği düşürelim' fikri kanıtsız; "
                f"örneklem 100'ün altında. Risk sayıları değiştirilemez.")
    return json.dumps({"kararlar": [
        {"baslik": "Rejim eşiği göreli olsun", "gerekce": "mutlak eşik 78.516/78.516 tick'i sıkışma yaptı",
         "kanit": "bot/v9/rejim.py", "etki": "yüksek", "risk": "düşük"},
        {"baslik": "Komisyon muhasebesi tek yerde", "gerekce": "kapanışta çift düşüm",
         "kanit": "bot/v8/broker.py", "etki": "yüksek", "risk": "düşük"},
        {"baslik": "Rejim dönüşünde -7 $ altına inme", "gerekce": "market çıkış kayma+komisyon",
         "kanit": "bot/v9/motor.py", "etki": "orta", "risk": "düşük"},
    ]}, ensure_ascii=False)
