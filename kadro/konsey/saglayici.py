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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

ESIK_KARAKTER = 26_000          # ~7.4K token; 8K girdi sınırının altında güvenli


@dataclass(frozen=True)
class Saglayici:
    ad: str
    taban: str
    anahtar_env: str | None
    varsayilan_model: str

    def anahtar(self) -> str:
        return os.environ.get(self.anahtar_env, "") if self.anahtar_env else ""


SAGLAYICILAR: dict[str, Saglayici] = {
    "github": Saglayici("github", "https://models.github.ai/inference", "GITHUB_TOKEN",
                        "openai/gpt-4.1-mini"),
    "nvidia": Saglayici("nvidia", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY",
                        "meta/llama-3.3-70b-instruct"),
    "ollama": Saglayici("ollama", "http://localhost:11434/v1", None, "llama3.1"),
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
    azami_saniye: float = 900.0
    kullanilan: int = 0
    baslangic: float = field(default_factory=time.time)
    kayitlar: list[Cagri] = field(default_factory=list)

    def bitti(self) -> bool:
        return self.kullanilan >= self.azami_cagri or (time.time() - self.baslangic) > self.azami_saniye


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
          sicaklik: float = 0.3, azami_token: int = 1200,
          kuru_kosu: bool = False) -> str:
    """Tek chat-completions çağrısı. Hata durumunda boş metin döner (konsey devam eder)."""
    s = SAGLAYICILAR[saglayici]
    model = model or s.varsayilan_model
    butce = butce or Butce()
    mesajlar = _kirp(mesajlar)
    istem_karakter = sum(len(m["content"]) for m in mesajlar)

    if kuru_kosu:
        yanit = _kuru_yanit(rol, tur, istem_karakter)
        butce.kayitlar.append(Cagri(saglayici, model, rol, tur, istem_karakter, yanit, 0.0))
        butce.kullanilan += 1
        return yanit

    if butce.bitti():
        return ""
    anahtar = s.anahtar()
    if s.anahtar_env and not anahtar:
        butce.kayitlar.append(Cagri(saglayici, model, rol, tur, istem_karakter, "",
                                    0.0, f"{s.anahtar_env} yok"))
        return ""

    govde = json.dumps({"model": model, "messages": mesajlar,
                        "temperature": sicaklik, "max_tokens": azami_token}).encode()
    basliklar = {"Content-Type": "application/json"}
    if anahtar:
        basliklar["Authorization"] = f"Bearer {anahtar}"

    son_hata = ""
    for deneme in range(3):
        t0 = time.time()
        try:
            istek = urllib.request.Request(f"{s.taban}/chat/completions", data=govde,
                                           headers=basliklar, method="POST")
            with urllib.request.urlopen(istek, timeout=120) as y:
                d = json.loads(y.read().decode())
            metin = (d.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            butce.kullanilan += 1
            butce.kayitlar.append(Cagri(saglayici, model, rol, tur, istem_karakter,
                                        metin, round(time.time() - t0, 1)))
            return metin
        except urllib.error.HTTPError as e:
            son_hata = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504) and deneme < 2:
                bekle = float(e.headers.get("Retry-After") or (2 ** deneme * 5))
                time.sleep(min(bekle, 60))
                continue
            break
        except Exception as e:                       # ağ/timeout
            son_hata = f"{type(e).__name__}: {e}"[:120]
            if deneme < 2:
                time.sleep(2 ** deneme * 3)
                continue
            break

    butce.kayitlar.append(Cagri(saglayici, model, rol, tur, istem_karakter, "",
                                0.0, son_hata))
    return ""


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
