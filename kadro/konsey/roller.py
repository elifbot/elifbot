# -*- coding: utf-8 -*-
"""roller.py — konseyin 5 rolü.

Her rol bir havuз demetine bakar ve yalnızca o konuda konuşur. Bu, 8K token sınırında
çalışmanın tek yolu: bir rol = bir demet = bir soru.
"""
from __future__ import annotations

from dataclasses import dataclass

KURAL = ("DEĞİŞMEZ KURAL: 1.000 $ kasa · 50 $ teminat · 10x · CROSS · pozisyon limiti YOK · "
         "pozisyon başına net −10 $ stop. Bu sayıları değiştiren hiçbir öneri kabul edilmez; "
         "bunu istemek vakit kaybıdır.")


@dataclass(frozen=True)
class Rol:
    ad: str
    konu: str
    unvan: str
    sistem: str


ROLLER: tuple[Rol, ...] = (
    Rol("mimar", "giris", "Baş Mimar",
        "Sen bir kripto vadeli işlem sisteminin baş mimarısın. Sinyal katmanını tasarlarsın. "
        "Süslü cümle yok; her iddia kanıt satırına (`dosya:satır`) dayanır. "
        "Gürültüyü kenar sanma. " + KURAL),
    Rol("risk_subayi", "risk", "Risk Subayı",
        "Sen risk subayısın ve veto hakkın var. Teminat fiziği, eşzamanlı pozisyon, "
        "korelasyon ve tasfiye mesafesi senin alanın. Kural sayılarına dokunulmaz. "
        "Her öneride 'en kötü durumda kasa ne olur' sorusunu yanıtla. " + KURAL),
    Rol("icra", "icra", "İcra Mühendisi",
        "Sen emir icrası mühendisisin. Post-only, kısmi dolum, amend, idempotency, kayma ve "
        "borsa reddi senin alanın. 'Kağıtta çalışır' ile 'borsada çalışır' arasındaki farkı yaz. "
        + KURAL),
    Rol("test", "veri", "Test Mühendisi",
        "Sen test mühendisisin. Veri kalitesi, replay tutarlılığı, sentetik-gerçek ayrımı ve "
        "kabul kriterleri senin alanın. 'Kanıtlanamıyorsa yoktur' ilkesiyle yaz. " + KURAL),
    Rol("olcum", "cikis", "Ölçüm Analisti",
        "Sen ölçüm analistisin. WR tek başına anlamsızdır: başabaş WR, PF, maksDD ve "
        "en kötü tek işlemle birlikte okursun. Örneklem <100 ise 'yön göstergesi' dersin. "
        + KURAL),
    Rol("ops", "ops", "Operasyon Sorumlusu",
        "Sen operasyondan sorumlusun: kopma, yeniden başlatma, kill switch, log ve alarm. "
        "Bir botun 7/24 ayakta kalması için asgariyi yazarsın. " + KURAL),
)


def rol_bul(ad: str) -> Rol | None:
    return next((r for r in ROLLER if r.ad == ad), None)


def oneri_istemi(rol: Rol, demet: str, gorev: str) -> list[dict]:
    return [
        {"role": "system", "content": rol.sistem},
        {"role": "user", "content": (f"GÖREV: {gorev}\n\n"
                                     f"Aşağıda arşivden çıkarılmış kanıt demeti var.\n\n{demet}")},
    ]


def itiraz_istemi(rol: Rol, kendi: str, digerleri: dict[str, str]) -> list[dict]:
    ozet = "\n\n".join(f"### {ad}\n{metin[:700]}" for ad, metin in digerleri.items())
    return [
        {"role": "system", "content": rol.sistem},
        {"role": "user", "content": (f"SENİN ÖNERİN:\n{kendi[:1500]}\n\n"
                                     f"DİĞER ROLLER:\n{ozet}\n\n"
                                     "Görev: en fazla 3 itiraz yaz. Her itirazda hangi önerinin "
                                     "hangi kanıttan yoksun olduğunu söyle. Katıldığın noktayı da "
                                     "tek satırda yaz. Kısa yaz.")},
    ]


def sekreter_istemi(oneriler: dict[str, str], itirazlar: dict[str, str],
                    dosya_indeksi: str = "") -> list[dict]:
    o = "\n\n".join(f"## {ad}\n{m[:900]}" for ad, m in oneriler.items())
    i = "\n\n".join(f"## {ad}\n{m[:500]}" for ad, m in itirazlar.items())
    return [
        {"role": "system", "content":
            "Sen konseyin sekretersin. Önerileri ve itirazları süzüp UYGULANABİLİR kararlar çıkarırsın. "
            "YALNIZCA geçerli JSON döndür, başka metin yok. " + KURAL},
        {"role": "user", "content":
            f"ÖNERİLER:\n{o}\n\nİTİRAZLAR:\n{i}\n\n"
            f"REPODAKİ GERÇEK DOSYALAR (başka dosya adı uydurma):\n{dosya_indeksi}\n\n"
            "En fazla 4 karar seç. Her karar bir dosyada somut bir kod değişikliği olmalı.\n"
            "Şema:\n"
            '{"kararlar":[{"baslik":"...","gerekce":"...","dosya":"bot/v9/motor.py",'
            '"eski_kod":"dosyadan AYNEN kopyalanmış 3-20 satır","yeni_kod":"onun yerine geçecek kod",'
            '"etki":"yüksek|orta|düşük","risk":"düşük|orta|yüksek"}],"ozet":"tek paragraf"}\n'
            "KURALLAR:\n"
            "1) eski_kod, dosyada birebir var olan bir parça olmalı (girinti dahil). "
            "Emin değilsen o kararı hiç yazma.\n"
            "2) yeni_kod aynı girinti düzeyinde geçerli Python olmalı.\n"
            "3) Kural sayılarını (1000$, 50$, 10x, -10$) değiştiren hiçbir karar yazma."},
    ]

def yama_istemi(karar: dict, dosya: str, kaynak: str) -> list[dict]:
    """Tek kararı, dosyanın GERÇEK kaynağıyla uygulanabilir yamaya çevirir."""
    return [
        {"role": "system", "content":
            "Sen kıdemli bir Python mühendisisin. Sana bir karar ve bir dosyanın tam kaynağı verilir. "
            "YALNIZCA geçerli JSON döndür, başka metin yok. " + KURAL},
        {"role": "user", "content":
            f"KARAR: {karar.get('baslik', '')}\nGEREKÇE: {karar.get('gerekce', '')}\n\n"
            f"DOSYA: {dosya}\n```python\n{kaynak}\n```\n\n"
            f"MODELİN KENDİ ÖNERİSİ (fikir olarak kullan, birebir uygulamak zorunda değilsin): "
            f"{karar.get('hedef', '')} / {karar.get('yeni_kod', '')[:400]}\n\n"
            "Bu kararı bu dosyada uygula. Şema:\n"
            '{"eski_kod":"dosyadan BİREBİR kopyalanmış 2-25 satır (girinti dahil)",'
            '"yeni_kod":"onun yerine geçecek kod","aciklama":"tek cümle"}\n'
            "Kurallar: eski_kod dosyada birebir ve tek kez geçmeli; yeni_kod aynı girintiyle "
            "geçerli Python olmalı; 1000/50/10x/-10$ sayılarını değiştirme. "
            "Uygulanabilir bir değişiklik yoksa {\"eski_kod\":\"\",\"yeni_kod\":\"\"} döndür."},
    ]
