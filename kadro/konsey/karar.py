# -*- coding: utf-8 -*-
"""karar.py — karar katmanı: sekreterin işini tek zekâya bırakmaz.

Sekreter (LLM) şemayı tutturamadığında tüm oturum kararsız kalıyordu. Bu modül
kararı üç bağımsız üreticiden toplar:

1. **sekreter** (LLM, mevcut yol)  — tartisma.sekreter_turu
2. **mühendis ajanı** — önerilerden hedef dosyayı çıkarır, o dosyanın TAM kaynağıyla
   ayrı bir çağrı yapar; şema tek ve dar olduğu için hata payı düşük.
3. **deterministik çıkarıcı** — hiç LLM kullanmaz: öneri metinlerinde geçen
   `bot/.../dosya.py` referanslarını ve fonksiyon adlarını toplar. Mühendis ajanına
   hedef listesi verir; böylece sekreter çökse bile iş ilerler.

Hepsi aynı doğrulayıcıdan geçer (yama.py): dosya var mı, eski_kod tek geçiyor mu,
sözdizimi sağlam mı.
"""
from __future__ import annotations

import re
from collections import Counter

DOSYA_DESENI = re.compile(r"bot/[\w/]+\.py")
FONK_DESENI = re.compile(r"(?:def|class)\s+([A-Za-z_]\w*)")

# LLM'in "şu dosyaya dokun" demek için kullandığı yaygın adlar
ES_ANLAM = ("motor.py", "rejim.py", "sinyaller.py", "broker.py", "sizing.py")


def hedefler(oneriler: dict[str, str], itirazlar: dict[str, str] | None = None,
             azami: int = 2) -> list[dict]:
    """Öneri/itiraz metinlerinden deterministik hedef listesi çıkarır.

    Dönen öğe: {"dosya": "bot/v9/motor.py", "fonksiyon": "_izle", "skor": 12}
    """
    metin = "\n".join(oneriler.values())
    if itirazlar:
        metin += "\n" + "\n".join(itirazlar.values())

    sayac: Counter = Counter(DOSYA_DESENI.findall(metin))
    for ad in ES_ANLAM:                       # kısa adla anılan dosyalar
        kisa = metin.count(ad)
        if kisa:
            for tam in ("bot/v9/" + ad, "bot/v8/" + ad):
                sayac[tam] += kisa
    if not sayac:
        return []

    from . import yama as ym
    api = ym.indeks()

    sonuc = []
    from pathlib import Path
    kok = Path(__file__).resolve().parents[2]
    for dosya, skor in sayac.most_common(azami * 3):
        if not (kok / dosya).exists():            # olmayan yolu ele
            continue
        adlar: list[str] = []
        for satir in api.get(dosya, []):
            parca = satir.split(":")[0]           # "def _izle()" / "class Poz"
            adlar.append(parca.split()[-1].rstrip("()"))
        adlar = [a for a in adlar if len(a) > 2]
        if adlar:
            en = max(adlar, key=lambda a: metin.count(a))
            fonk = en if metin.count(en) else ""
        else:
            fonk = ""
        sonuc.append({"dosya": dosya, "fonksiyon": fonk, "skor": skor})
        if len(sonuc) >= azami:
            break
    return sonuc


def muhendis_istemi(hedef: dict, gorev: str, oneri_metni: str, kaynak: str) -> list[dict]:
    """Mühendis ajanı: hedef dosyanın tam kaynağıyla dar şemalı yama ister."""
    from .roller import KURAL
    return [
        {"role": "system", "content":
            "Sen kıdemli bir Python mühendisisin. Görevin: verilen dosyada, verilen hedefe "
            "hizmet eden EN KÜÇÜK uygulanabilir kod değişikliğini yazmak. "
            "YALNIZCA geçerli JSON döndür, açıklama yazma. " + KURAL},
        {"role": "user", "content":
            f"GÖREV: {gorev}\n\nHEDEF: {hedef.get('dosya', '')} · {hedef.get('fonksiyon', '')}\n\n"
            f"KONSEY TARTIŞMASI (öz):\n{oneri_metni[:2500]}\n\n"
            f"DOSYANIN TAM KAYNAĞI:\n```python\n{kaynak}\n```\n\n"
            "Şema (tek anahtar, başka alan yok):\n"
            '{"degisiklikler":[{"eski_kod":"dosyadan BİREBİR kopyalanmış 2-25 satır",'
            '"yeni_kod":"onun yerine geçecek kod"}]}\n'
            "Kurallar:\n"
            "1) 1-3 değişiklik yaz; parçalar sırayla uygulanır, sonraki parçanın eski_kodu "
            "önceki parçanın çıktısında geçen hâliyle olmalı.\n"
            "2) Her eski_kod dosyada birebir ve TEK kez geçmeli (girinti dahil).\n"
            "3) yeni_kod aynı girintiyle geçerli Python olmalı; yeni isim kullanacaksan "
            "onun tanımını da aynı yamada yaz.\n"
            "4) 1000/50/10x/−10$ sayılarına dokunma.\n"
            "5) Uygulanabilir bir değişiklik yoksa {\"degisiklikler\":[]} döndür."},
    ]
