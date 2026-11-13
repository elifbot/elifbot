"""Bot Ekibi Beyni — modelleri isimli botlara çevirir, odayı yönetir.

Her yapay zekâ modeli kadroda İSİMLİ BİR BOT olarak çalışır (isim, emoji,
rol, model, aktif/pasif). Kullanıcı Bot Odası'na görev yazarsa:
  1) Görev sınıflandırılır (tarama / analiz / tanıtım / sohbet)
  2) İlgili bot görevi alır, işi yürütür
  3) Botlar arası danışma (@BotAdı) gerçek bir bot çağrısıdır
  4) Her adım odaya canlı mesaj olarak düşer
Konsensus analizi de buraya bağlandı: her botun oyu odaya anlık düşer.
"""
import asyncio
import re

import database as db
import bildirim
import config
from providers import _call_model, ChatError

ODA_KILIDI = asyncio.Lock()

# ---------------------------------------------------------------- roller
ROL_ACIKLAMA = {
    "analist":    "Baş Piyasa Analisti — yön tespiti ve gerekçeli analiz",
    "denetci":    "Risk Denetçisi — başkalarının kararını sorgular, kusuru bulur",
    "stratejist": "Strateji ve İşlem Planı — giriş/stop/TP/kaldıraç disiplini",
    "tarayici":   "Piyasa Tarayıcısı — tüm piyasa hızlı tarama ve özet",
    "hakem":      "Bağımsız Hakem — oylar bölünürse nihaî kararı o verir",
    "ozgur":      "Serbest Görevli — sohbet, araştırma, genel görevler",
}

ROL_KISILIK = {
    "analist": (
        "Adın: {ad} — ekipte Baş Piyasa Analisti olan bir yapay zekâ botusun. "
        "Trend, momentum ve türev verilerini (funding, açık pozisyon) okur, "
        "net bir yön ve gerekçe kurarsın. Kararını verirken tereddüt varsa "
        "odadaki başka bir bota '@BotAdı' diye seslenip görüşünü isteyebilirsin."
    ),
    "denetci": (
        "Adın: {ad} — ekibin Risk Denetçisi olan şüpheci bir yapay zekâ botusun. "
        "Görevin başkalarının analizini KONTROL ETMEK: aşırı alım/satım, kalabalık "
        "funding, zayıf hacim gibi kontra kanıtları arar, riskli kararı 'RED' "
        "diyeceğin zaman çekinmezsin. Gerektiğinde odada başka bir bota "
        "'@BotAdı' diye itiraz edebilirsin."
    ),
    "stratejist": (
        "Adın: {ad} — ekibin Strateji Uzmanı botusun. Analizleri işlem planına "
        "çevirirsin: makul giriş bölgesi, stop-loss, TP1/TP2, kaldıraç disiplini "
        "(maks 1-5x) ve risk/ödül oranı. Gereksiz riski her koşulda reddedersin."
    ),
    "tarayici": (
        "Adın: {ad} — ekibin Piyasa Tarayıcısı botusun. Hızlı, özet ve sayı "
        "odaklı konuşursun: hangi coin öne çıkıyor, skorlar ne söylüyor, "
        "sakınca var mı. Gerektiğinde başka bir bota '@BotAdı' diye sorabilirsin."
    ),
    "hakem": (
        "Adın: {ad} — ekibin Bağımsız Hakem botusun. Tarafsızsın: tüm kanıtı "
        "tarafsız tartar, tarafgirlik yapmaz, kanıt yetersizse 'NÖTR' dersin."
    ),
    "ozgur": (
        "Adın: {ad} — ekipte serbest görevli bir yapay zekâ botusun. Kripto "
        "piyasaları, teknik analiz ve genel konularda yardımcı olursun. "
        "Gerektiğinde odadaki uzman bota '@BotAdı' diye soru yönlendirebilirsin."
    ),
}

# ---------------------------------------------------------------- varsayılan kadro
VARSAYILAN_KADRO = [
    ("Kaptan",   "🧭", "analist",    "evren-glm",      "glm"),
    ("Denetçi",  "🛡️", "denetci",    "evren-deepseek", "pollinations"),
    ("Nişancı",  "🎯", "stratejist", "evren-qwen",     "glm"),
    ("Tarayıcı", "📡", "tarayici",   "evren-gemma",    "pollinations"),
    ("Hakem",    "⚖️", "hakem",      "evren-auto",     "glm"),
]


def kadroyu_kur() -> list[dict]:
    """İlk çalıştırmada varsayılan 5 botu kurar; kadroyu döner."""
    if db.bot_sayisi() == 0:
        if config.EVREN_API_KEY:
            secim = [b for b in VARSAYILAN_KADRO]
        else:
            secim = [(ad, em, rol, yedek_model, yedek_model)
                     for ad, em, rol, _p, yedek_model in VARSAYILAN_KADRO]
        for ad, emoji, rol, evren_m, yedek_m in secim:
            model = evren_m if config.EVREN_API_KEY else yedek_m
            db.bot_ekle(ad, emoji, rol, model)
        db.oda_ekle("⚙️ Sistem",
                    "Bot ekibi kuruldu! Bota görev verebilirsin: 'BTC analiz et', "
                    "'piyasayı tara', ya da bota doğrudan soru sor. "
                    "Botlar birbirlerini kontrol eder ve kararı birlikte verir.",
                    tur="sistem", emoji="⚙️")
    return db.botlari_yukle()


def aktif_kadro() -> list[dict]:
    return [b for b in db.botlari_yukle(sadece_aktif=True)]


def bot_promptu(bot: dict) -> str:
    sablon = ROL_KISILIK.get(bot.get("rol") or "ozgur", ROL_KISILIK["ozgur"])
    govde = sablon.format(ad=f"{bot.get('emoji', '🤖')} {bot['ad']}")
    return (
        f"{govde}\n"
        "Kurallar: 1) Her zaman Türkçe konuş. 2) En fazla 120 kelime, öz konuş. "
        "3) Kesin yatırım tavsiyesi verme; belirsizlik varsa söyle. "
        "4) Başka bir bota danışmak istersen mesaj içinde '@BotAdı' yaz "
        "(örnek: '@Denetçi sen ne düşünüyorsun?'). "
        "5) Kendini daima adınla tanıt (örnek: 'ben Kaptan'); model altyapını "
        "yazma, rolünle konuş. "
        f"6) Rolün: {ROL_ACIKLAMA.get(bot.get('rol'), 'serbest görev')}."
    )


def _bot_bul(rol: str) -> dict | None:
    for b in aktif_kadro():
        if b["rol"] == rol:
            return b
    return None


async def _cagir(bot: dict, prompt: str, timeout: int = 100,
                 deneme: int = 3) -> str:
    """Botun modelini çağırır (kapasite doluysa bekleyip yeniden dener)."""
    hata = ""
    for k in range(deneme):
        try:
            mesajlar = [{"role": "system", "content": bot_promptu(bot)},
                        {"role": "user", "content": prompt}]
            ham, _ = await asyncio.wait_for(
                _call_model(bot["model"], mesajlar), timeout=timeout)
            return ham.strip()
        except asyncio.TimeoutError:
            hata = f"zaman aşımı ({timeout}sn)"
        except ChatError as e:
            hata = str(e)
            if "HTTP 503" in hata or "dolu" in hata:
                await asyncio.sleep(4 + 4 * k)
                continue
            raise
        except Exception as e:
            hata = f"{type(e).__name__}: {e}"
        await asyncio.sleep(2)
    raise ChatError(hata)


def _oda_yaz(kim: str, metin: str, tur: str = "bot", emoji: str = "",
             kime: str = "") -> None:
    db.oda_ekle(kim, metin, tur=tur, emoji=emoji, kime=kime)


def oda_bağlamı(n: int = 10) -> str:
    """Son n oda mesajını botun görebileceği düz metne çevirir."""
    mesajlar = db.oda_gecmis(limit=n)
    return "\n".join(
        f"{m['kim']}: {m['metin']}" for m in mesajlar
    ) or "(oda boş)"


# ---------------------------------------------------------------- görev tespiti
ALIAS = {
    "BTC": "BTCUSDT", "BITCOIN": "BTCUSDT", "ETH": "ETHUSDT",
    "ETHEREUM": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT", "AVAX": "AVAXUSDT", "LINK": "LINKUSDT",
    "SUI": "SUIUSDT", "BNB": "BNBUSDT", "ADA": "ADAUSDT",
    "DOT": "DOTUSDT", "LTC": "LTCUSDT", "TRX": "TRXUSDT",
    "NEAR": "NEARUSDT", "ARB": "ARBUSDT", "OP": "OPUSDT",
    "PEPE": "PEPEUSDT", "SHIB": "SHIBUSDT", "TON": "TONUSDT",
    "ATOM": "ATOMUSDT", "FIL": "FILUSDT", "APT": "APTUSDT",
    "INJ": "INJUSDT", "SEI": "SEIUSDT", "TIA": "TIAUSDT",
    "ETC": "ETCUSDT", "XLM": "XLMUSDT", "HBAR": "HBARUSDT",
    "UNI": "UNIUSDT", "AAVE": "AAVEUSDT", "CRV": "CRVUSDT",
    "MATIC": "MATICUSDT", "POL": "POLUSDT", "RNDR": "RENDERUSDT",
}


def _sembol_ayikla(metin: str) -> str | None:
    m = metin.upper()
    t = m.replace("İ", "I").replace("Ş", "S").replace("Ğ", "G")
    # 1) doğrudan COINUSDT kalıbı
    mm = re.search(r"\b([A-Z0-9]{2,12}USDT)\b", t)
    if mm:
        return mm.group(1)
    # 2) alias tablosu
    for w in re.findall(r"[A-Z]{2,10}", t):
        if w in ALIAS:
            return ALIAS[w]
    return None


def _gorev_tespit(metin: str) -> tuple[str, str | None]:
    """(gorev_tipi, sembol) — anahtar kelime tabanlı, hızlı ve güvenilir."""
    m = metin.lower()
    tarama_kelimeler = ("tara", "tarama", "fırsat", "firsat", "en güçlü",
                        "en guclu", "hangi coin", "piyasa durumu",
                        "genel durum", "özet çıkar")
    sembol = _sembol_ayikla(metin)
    if any(k in m for k in tarama_kelimeler) and not sembol:
        return "tarama", None
    if sembol:
        return "analiz", sembol
    if any(k in m for k in ("kim", "kadro", "tanıt", "tanit", "takım", "ekip kim")):
        return "tanitim", None
    return "sohbet", None


# ---------------------------------------------------------------- görev akışları
async def _tarama_yurut() -> None:
    tarayici = _bot_bul("tarayici") or (aktif_kadro() or [None])[0]
    if not tarayici:
        _oda_yaz("⚙️ Sistem", "Aktif bot yok — Bot Kadrosu'ndan bot aç.",
                 tur="sistem", emoji="⚙️")
        return
    _oda_yaz(tarayici["ad"], "Görevi aldım, piyasa taramasını başlatıyorum…",
             emoji=tarayici["emoji"], kime="")
    import signal_engine as se
    semboller = list(dict.fromkeys(
        db.get_watchlist(0) + config.SCAN_SYMBOLS))[:10]
    sonuclar = await asyncio.gather(
        *[se.generate_signal(s) for s in semboller], return_exceptions=True)
    rows = [r for r in sonuclar if isinstance(r, dict)]
    rows.sort(key=lambda x: abs(x["skor"]), reverse=True)
    if not rows:
        _oda_yaz("⚙️ Sistem", "Tarama başarısız — veri kaynağına ulaşılamadı.",
                 tur="sistem", emoji="⚙️")
        return
    liste = "\n".join(
        f"{r['emoji']} {r['sembol']}: {r['taraf']} (skor {r['skor']:+d}, "
        f"fiyat {r['fiyat']:,.2f}, RSI {r['rsi']:.0f})"
        for r in rows)
    _oda_yaz("⚙️ Sistem", f"Tarama sonucu (teknik skor sırası):\n{liste}",
             tur="sistem", emoji="⚙️")
    try:
        ozet = await _cagir(tarayici, (
            "Aşağıdaki teknik tarama tablosunu piyasa tarayıcısı kimliğinle "
            "yorumla: 2-3 cümlelik özet yaz (en güçlü fırsat, genel piyasa "
            "ruhu, dikkat çeken risk). Tablo:\n" + liste))
        _oda_yaz(tarayici["ad"], ozet, emoji=tarayici["emoji"])
    except Exception as e:
        _oda_yaz("⚙️ Sistem", f"Tarayıcı yorumu alınamadı: {str(e)[:150]}",
                 tur="sistem", emoji="⚙️")


def sonuc_odaya_yaz(sonuc: dict) -> None:
    """Konsensus sonucunu 🏁 SONUÇ sistem mesajı olarak odaya yazar."""
    t = sonuc["teknik"]
    db.oda_ekle(
        "⚙️ Sistem",
        f"🏁 SONUÇ — {sonuc['sembol']}: {sonuc['final_yon']} "
        f"({sonuc['hukum']}, güven %{sonuc['final_guven']}, "
        f"oydaşlık %{sonuc['oydaslik']}) • Fiyat {t['fiyat']:,.2f} • "
        f"SL {t['stop']:,.2f} • TP1 {t['tp1']:,.2f} • TP2 {t['tp2']:,.2f} • "
        f"maks {t['kaldirac']}x",
        tur="sistem", emoji="⚙️")


async def _analiz_yurut(sembol: str) -> None:
    import konsensus
    kaptan = _bot_bul("analist") or (aktif_kadro() or [None])[0]
    if not kaptan:
        _oda_yaz("⚙️ Sistem", "Aktif bot yok — Bot Kadrosu'ndan bot aç.",
                 tur="sistem", emoji="⚙️")
        return
    _oda_yaz(kaptan["ad"],
             f"{sembol} için konsensus analizi başlatıyorum — her bot oy verecek, "
             f"bölünme olursa Hakem devreye girecek.",
             emoji=kaptan["emoji"], kime="")
    try:
        sonuc = await konsensus.analiz_et(sembol)
    except Exception as e:
        _oda_yaz("⚙️ Sistem",
                 f"❌ {sembol} analizi başarısız: {str(e)[:200]}",
                 tur="sistem", emoji="⚙️")
        return
    sonuc_odaya_yaz(sonuc)
    t = sonuc["teknik"]
    stratejist = _bot_bul("stratejist")
    if stratejist:
        try:
            plan = await _cagir(stratejist, (
                f"Ekip {sonuc['sembol']} için {sonuc['final_yon']} kararına vardı "
                f"(güven %{sonuc['final_guven']}, teknik skor {t['skor']:+d}, "
                f"fiyat {t['fiyat']:,.2f}, SL {t['stop']:,.2f}, "
                f"TP1 {t['tp1']:,.2f}, TP2 {t['tp2']:,.2f}, maks {t['kaldirac']}x). "
                "Bu planı strateji uzmanı kimliğinle 1-2 cümleyle değerlendir: "
                "makul mu, hangi koşulda iptal edilmeli?"))
            _oda_yaz(stratejist["ad"], plan, emoji=stratejist["emoji"])
        except Exception:
            pass
    # ---- kayıt + alarm ----
    alarm = 1 if (sonuc["final_yon"] in ("LONG", "SHORT")
                  and sonuc["final_guven"] >= 60
                  and sonuc["oydaslik"] >= 50) else 0
    if alarm and not db.recent_analysis_alarm(sonuc["sembol"], sonuc["final_yon"],
                                              config.ALERT_COOLDOWN_H):
        db.save_analysis(sonuc["sembol"], sonuc["final_yon"],
                         sonuc["final_guven"], sonuc["oydaslik"], t["skor"],
                         t["fiyat"], sonuc["hukum"],
                         konsensus.detay_paketi(sonuc), alarm=1)
        baslik, mesaj = konsensus.bildirim_metni(sonuc)
        bildirim.gonder(baslik, mesaj)
        _oda_yaz("⚙️ Sistem", f"🔔 Masaüstü bildirimi gönderildi: {baslik} — {mesaj}",
                 tur="sistem", emoji="⚙️")
    else:
        db.save_analysis(sonuc["sembol"], sonuc["final_yon"],
                         sonuc["final_guven"], sonuc["oydaslik"], t["skor"],
                         t["fiyat"], sonuc["hukum"],
                         konsensus.detay_paketi(sonuc), alarm=0)


async def _tanitim_yurut() -> None:
    kadro = aktif_kadro()
    if not kadro:
        _oda_yaz("⚙️ Sistem", "Aktif bot yok — Bot Kadrosu'ndan bot aç.",
                 tur="sistem", emoji="⚙️")
        return
    _oda_yaz("⚙️ Sistem", "Kadro tanıtımı — her bot kendini tanıtıyor:",
             tur="sistem", emoji="⚙️")
    for b in kadro:
        try:
            txt = await _cagir(b, (
                "Odaya kendini 2 cümleyle tanıt: kim olduğunu, hangi model "
                "üzerinden çalıştığını ve ekipte ne işi yaptığını söyle. "
                "Selamlaşmayla başla."))
            _oda_yaz(b["ad"], txt, emoji=b["emoji"])
        except Exception as e:
            _oda_yaz(b["ad"], f"(şu an sesim kesik: {str(e)[:120]})",
                     emoji=b["emoji"])


async def _sohbet_yurut(metin: str) -> None:
    kadro = aktif_kadro()
    if not kadro:
        _oda_yaz("⚙️ Sistem", "Aktif bot yok — Bot Kadrosu'ndan bot aç.",
                 tur="sistem", emoji="⚙️")
        return
    # hedef: mesajda @ad geçen bot → yoksa Kaptan/ilk bot
    hedef = None
    for b in kadro:
        if f"@{b['ad'].lower()}" in metin.lower():
            hedef = b
            break
    if not hedef:
        hedef = _bot_bul("analist") or kadro[0]
    try:
        yanit = await _cagir(hedef, (
            f"Bot odasının son konuşmaları:\n{oda_bağlamı(10)}\n\n"
            f"Kullanıcı sana şu görevi/sorusunu verdi:\n\"{metin}\"\n\n"
            "Kendi rolüne uygun, kısa ve net yanıt ver. Gerekirse başka bir "
            "bota '@BotAdı' ile soru yönlendir."))
    except Exception as e:
        _oda_yaz("⚙️ Sistem", f"❌ {hedef['ad']} yanıt veremedi: {str(e)[:150]}",
                 tur="sistem", emoji="⚙️")
        return
    _oda_yaz(hedef["ad"], yanit, emoji=hedef["emoji"], kime="👤 Sen")
    # ---- botlar arası danışma: yanıt içinde @BotAdı arayan 1 kez devreye girer
    danişacak = None
    for b in kadro:
        if b["id"] == hedef["id"]:
            continue
        if f"@{b['ad'].lower()}" in yanit.lower():
            danişacak = b
            break
    if danişacak:
        try:
            yanit2 = await _cagir(danişacak, (
                f"Oda konuşması:\n{oda_bağlamı(8)}\n\n"
                f"{hedef['emoji']} {hedef['ad']} seni bu konuya dahil etti. "
                "Rolüne uygun, en fazla 100 kelimelik görüşünü yaz."))
            _oda_yaz(danişacak["ad"], yanit2, emoji=danişacak["emoji"],
                     kime=f"{hedef['emoji']} {hedef['ad']}")
        except Exception as e:
            _oda_yaz("⚙️ Sistem",
                     f"❌ {danişacak['ad']} yanıt veremedi: {str(e)[:150]}",
                     tur="sistem", emoji="⚙️")


# ---------------------------------------------------------------- ana giriş
async def gorev_yurut(metin: str) -> dict:
    """Kullanıcı görevini kadroya dağıtır. Oda mesajları DB'ye canlı düşer.
    Botlar meşgulse görev sıraya girer; bitince otomatik çalışır."""
    if ODA_KILIDI.locked():
        _oda_yaz("⚙️ Sistem",
                 "⏳ Botlar şu anda bir görev yürütüyor — görevin sırada; "
                 "sıra gelince otomatik çalışacak.",
                 tur="sistem", emoji="⚙️")
    async with ODA_KILIDI:
        gorev, sembol = _gorev_tespit(metin)
        try:
            if gorev == "tarama":
                await _tarama_yurut()
            elif gorev == "analiz":
                await _analiz_yurut(sembol)
            elif gorev == "tanitim":
                await _tanitim_yurut()
            else:
                await _sohbet_yurut(metin)
        except Exception as e:
            _oda_yaz("⚙️ Sistem", f"❌ Görev yürütme hatası: {str(e)[:200]}",
                     tur="sistem", emoji="⚙️")
        return {"ok": True, "gorev": gorev, "sembol": sembol}
