"""Bot Konsensus Motoru — kadrodaki botlar aynı canlı veriye bakıp oy verir,
birbirini kontrol eder; uyumsuzlukta Hakem botu nihaî kararı verir.

Akış:
  1) signal_engine ile canlı teknik veri + skor
  2) Bot kadrosundaki her bot AYNI veriyi görüp bağımsız JSON oyu verir;
     her oy Bot Odası'na canlı mesaj olarak düşer
  3) Oydaşlık >= %50 → konsensus; < %50 → Hakem botu çağrılır
  4) Hakem tüm oyları görüp nihaî kararı verir ve odaya yazar
"""
import asyncio
import json
import re
from datetime import datetime, timezone

import database as db
import signal_engine as se
from config import EVREN_API_KEY, MODEL_CATALOG, model_available
from providers import _call_model, ChatError

# Kadro boşsa yedek kurul (bot kadrosu silinmişse sistem yine çalışsın)
YEDEK_KURUL = ["evren-glm", "evren-deepseek", "evren-qwen", "evren-gemma"]
YEDEK_KURUL_ANAHTARSIZ = ["glm", "pollinations"]
YEDEK_HAKEM = "evren-glm"
YEDEK_HAKEM_ANAHTARSIZ = "glm"


def _yedek_bot(mid: str) -> dict:
    return {"id": -1, "ad": mid, "emoji": "🤖", "rol": "analist",
            "model": mid, "aktif": 1}


def kurul() -> list[dict]:
    """Oy verecek bot kadrosu (aktif botlar); boşsa yedek model listesi."""
    kadro = db.botlari_yukle(sadece_aktif=True)
    if kadro:
        return kadro
    liste = YEDEK_KURUL if EVREN_API_KEY else YEDEK_KURUL_ANAHTARSIZ
    return [_yedek_bot(m) for m in liste if model_available(m)]


def hakem_botu() -> dict | None:
    """Rolü 'hakem' olan aktif bot; yoksa yedek hakem modeli."""
    for b in db.botlari_yukle(sadece_aktif=True):
        if b["rol"] == "hakem":
            return b
    mid = YEDEK_HAKEM if (EVREN_API_KEY and model_available(YEDEK_HAKEM)) \
        else YEDEK_HAKEM_ANAHTARSIZ
    return _yedek_bot(mid) if model_available(mid) else None


def _kisilik(bot: dict) -> str:
    """Botun kişilik sistem promptu (konsensus oyu için kısa sürüm)."""
    ad = f"{bot.get('emoji', '🤖')} {bot['ad']}"
    rol_metin = {
        "analist": "Baş Piyasa Analisti: trend ve momentum odaklı net yön analizi",
        "denetci": "Risk Denetçisi: şüpheci bak, kontra kanıt ara, riskli kararı reddet",
        "stratejist": "Strateji Uzmanı: işlem planı, risk/ödül ve kaldıraç disiplini odaklı",
        "tarayici": "Piyasa Tarayıcısı: hızlı, sayı odaklı, piyasa geneli özet",
        "hakem": "Bağımsız Hakem: tüm kanıtı tarafsız tart, kanıt yoksa NÖTR",
        "ozgur": "Serbest Görevli: dengeli genel değerlendirme",
    }.get(bot.get("rol"), "dengeli genel değerlendirme")
    return (
        f"Sen {ad}'sın — bir kripto vadeli (futures) işlem bot ekibinin üyesisin. "
        f"Rolün: {rol_metin}. Türkçe düşün ve yaz."
    )


def _veri_paketi(sig: dict) -> str:
    return (
        f"Sembol: {sig['sembol']} (USDT perpetual futures)\n"
        f"Fiyat: {sig['fiyat']:.2f} USDT | 24s değişim: {sig['deg24']:+.2f}%\n"
        f"EMA9: {sig['ema9']:.2f} | EMA21: {sig['ema21']:.2f} | EMA50: {sig['ema50']:.2f}\n"
        f"RSI(14): {sig['rsi']:.1f} | MACD histogram: {sig['macd_hist']:.3f}\n"
        f"ATR(14): {sig['atr']:.2f} | Funding: {sig['funding']*100:+.3f}%\n"
        f"Açık pozisyon 24s değişimi: {sig['oi_deg']:+.1f}% | 24s hacim: {sig['hacim_usdt']:,.0f} USDT\n"
        f"Zaman dilimi: {sig['interval']} dakika\n"
        f"Teknik motor skoru: {sig['skor']:+d} / ±{sig['max_skor']} → {sig['taraf']}"
    )


OY_PROMPTU = (
    "Aşağıdaki CANLI piyasa verisini incele ve TAMAMEN BAĞIMSIZ kararını ver. "
    "Funding ve OI gibi türev verileri kontra sinyal olarak da değerlendir. "
    "Yalnızca şu JSON'u döndür, başka hiçbir metin yazma:\n"
    '{"yön": "LONG veya SHORT veya NÖTR", "guven": 0-100, '
    '"gerekce": "en fazla 2 cümle", "risk": "düşük veya orta veya yüksek"}\n\n'
    "=== CANLI PİYASA VERİSİ ===\n{veri}\n\n"
    "Şimdi JSON oyu döndür."
)

HAKEM_PROMPTU = (
    "Bot ekibinin oyları bölünmüş durumda. Piyasa verisini ve tüm oyları "
    "değerlendir, hangi yön savunulabilirse onu seç; kimse ikna edici değilse "
    "NÖTR ver. Yalnızca şu JSON'u döndür, başka metin yazma:\n"
    '{"yön": "LONG veya SHORT veya NÖTR", "guven": 0-100, '
    '"gerekce": "en fazla 3 cümle, oyları neden onayladın/aştın", '
    '"risk": "düşük veya orta veya yüksek"}\n\n'
    "=== PİYASA VERİSİ ===\n{veri}\n\n"
    "=== BOTLARIN OYLARI ===\n{oylar}\n\n"
    "Şimdi nihaî JSON kararını döndür."
)


def _json_ayikla(text: str) -> dict | None:
    """Model çıktısından JSON'u çıkar (```fence ve fazlalıklara dayanıklı)."""
    t = re.sub(r"```(?:json)?", "", text).strip("` \n")
    m = re.search(r"\{[^{}]*\}", t, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    yon = str(d.get("yön") or d.get("yon") or "").upper()
    if "LONG" in yon and "SHORT" not in yon:
        yon = "LONG"
    elif "SHORT" in yon:
        yon = "SHORT"
    else:
        yon = "NÖTR"
    try:
        guven = max(0, min(100, int(float(d.get("guven", 50)))))
    except Exception:
        guven = 50
    risk = str(d.get("risk") or "orta").lower()
    if risk not in ("düşük", "orta", "yüksek"):
        risk = "orta"
    return {
        "yön": yon, "guven": guven,
        "gerekce": str(d.get("gerekce") or "").strip()[:400],
        "risk": risk,
    }


async def _cagir_geri_cek(model_id: str, system: str, prompt: str,
                          timeout: int = 120, deneme: int = 3) -> str:
    """Model çağrısı + 503/zaman aşımında bekle-yeniden dene."""
    son_hata = ""
    for k in range(deneme):
        try:
            mesajlar = [{"role": "system", "content": system},
                        {"role": "user", "content": prompt}]
            ham, _ = await asyncio.wait_for(
                _call_model(model_id, mesajlar), timeout=timeout)
            return ham
        except asyncio.TimeoutError:
            son_hata = f"zaman aşımı ({timeout}sn)"
        except ChatError as e:
            son_hata = str(e)
            if "HTTP 503" in son_hata or "dolu" in son_hata:
                await asyncio.sleep(5 + 5 * k)  # kapasite dolu → bekle
                continue
            raise  # diğer hatalar anlamlı, yeniden deneme yok
        except Exception as e:
            son_hata = f"{type(e).__name__}: {e}"
        await asyncio.sleep(2)
    raise ChatError(son_hata)


def _oy_oda_yaz(bot: dict, metin: str, kime: str = "") -> None:
    db.oda_ekle(bot["ad"], metin, tur="bot",
                emoji=bot.get("emoji", "🤖"), kime=kime)


async def _oy_ver(bot: dict, veri: str, sembol: str) -> dict:
    """Bir botu bağımsız oya çağır; oyu odaya canlı düşür."""
    sistem = (_kisilik(bot)
              + " Şu an görevin: piyasa verisini inceleyip JSON oyu döndürmek. "
                "Yanıtında YALNIZCA geçerli JSON olsun.")
    try:
        prompt = OY_PROMPTU.replace("{veri}", veri)
        ham = await _cagir_geri_cek(bot["model"], sistem, prompt)
        parsed = _json_ayikla(ham)
        if not parsed:
            raise ChatError(f"JSON çözümlenemedi: {ham[:120]}")
        _oy_oda_yaz(
            bot,
            f"{sembol} için oyum: {parsed['yön']} (güven %{parsed['guven']}, "
            f"risk {parsed['risk']}) — {parsed['gerekce']}",
            kime="Hakem'e")
        return {"model": bot["model"], "etiket": MODEL_CATALOG.get(bot["model"], {})
                .get("etiket", bot["model"]),
                "bot_ad": bot["ad"], "bot_emoji": bot.get("emoji", "🤖"),
                "durum": "tamam", **parsed, "ham": ham[:600]}
    except Exception as e:
        db.oda_ekle("⚙️ Sistem", f"❌ {bot['ad']} oy veremedi: {str(e)[:150]}",
                    tur="sistem", emoji="⚙️")
        return {"model": bot["model"],
                "etiket": MODEL_CATALOG.get(bot["model"], {})
                .get("etiket", bot["model"]),
                "bot_ad": bot["ad"], "bot_emoji": bot.get("emoji", "🤖"),
                "durum": "hata", "hata": str(e)[:200]}


async def _hakem(veri: str, oylar: list[dict]) -> dict:
    bot = hakem_botu()
    mid = bot["model"] if bot else (YEDEK_HAKEM if EVREN_API_KEY
                                    else YEDEK_HAKEM_ANAHTARSIZ)
    oy_metni = "\n".join(
        f"- {o.get('bot_ad', o['model'])}: {o['yön']} "
        f"(güven {o['guven']}, risk {o['risk']}) — {o['gerekce']}"
        for o in oylar)
    sistem = (_kisilik(bot) if bot
              else "Sen tarafsız bir hakem analistsin.")
    try:
        prompt = HAKEM_PROMPTU.replace("{veri}", veri).replace("{oylar}", oy_metni)
        ham = await _cagir_geri_cek(mid, sistem, prompt)
        parsed = _json_ayikla(ham)
        if not parsed:
            raise ChatError(f"hakem JSON çözülemedi: {ham[:120]}")
        ad = bot["ad"] if bot else mid
        emoji = bot.get("emoji", "⚖️") if bot else "⚖️"
        db.oda_ekle(
            ad, f"Oylar bölündü, kararı veriyorum: {parsed['yön']} "
                f"(güven %{parsed['guven']}) — {parsed['gerekce']}",
            tur="bot", emoji=emoji)
        return {"model": mid, "bot_ad": ad, "bot_emoji": emoji,
                "durum": "tamam", **parsed}
    except Exception as e:
        db.oda_ekle("⚙️ Sistem", f"❌ Hakem kararı alınamadı: {str(e)[:150]}",
                    tur="sistem", emoji="⚙️")
        return {"model": mid, "durum": "hata", "hata": str(e)[:200]}


def _konsensus_hesapla(oylar: list[dict], sig: dict) -> dict:
    gecerli = [o for o in oylar if o["durum"] == "tamam"]
    dagilim = {"LONG": 0, "SHORT": 0, "NÖTR": 0}
    for o in gecerli:
        dagilim[o["yön"]] += 1
    kazanan = max(dagilim, key=dagilim.get)
    n = len(gecerli)
    oydaslik = (dagilim[kazanan] / n) if n else 0.0

    if n and dagilim[kazanan] > 0:
        kazanan_oylar = [o for o in gecerli if o["yön"] == kazanan]
        ort_guven = sum(o["guven"] for o in kazanan_oylar) / len(kazanan_oylar)
    else:
        ort_guven = 0.0

    # teknik motorla uyum (±10)
    tek = sig["skor"]
    uyum = 0
    if kazanan == "LONG" and tek >= 20:
        uyum = 10
    elif kazanan == "SHORT" and tek <= -20:
        uyum = 10
    elif kazanan == "LONG" and tek <= -20:
        uyum = -10
    elif kazanan == "SHORT" and tek >= 20:
        uyum = -10

    final_yon, final_guven = kazanan, ort_guven
    hukum = "KONSENSÜS"
    if n == 0:
        final_yon, final_guven, hukum = "NÖTR", 0, "OY YOK"
    elif oydaslik >= 0.75:
        hukum = "GÜÇLÜ KONSENSÜS"
    elif oydaslik < 0.5:
        hukum = "BÖLÜNMÜŞ"
    final_guven = int(max(0, min(99, final_guven * (0.5 + 0.5 * oydaslik) + uyum)))

    return {
        "oy_dagilimi": dagilim, "kazanan_yon": kazanan,
        "oydaslik": round(oydaslik * 100), "ort_guven": int(ort_guven),
        "teknik_uyum": uyum, "final_yon": final_yon,
        "final_guven": final_guven, "hukum": hukum, "gecerli_oy": n,
    }


async def analiz_et(sembol: str, interval: str = "60") -> dict:
    """Tam konsensus analizi: teknik + kadro oyları + (gerekirse) Hakem botu."""
    sig = await se.generate_signal(sembol, interval)
    veri = _veri_paketi(sig)
    oylar = await asyncio.gather(*[_oy_ver(b, veri, sembol) for b in kurul()])
    k = _konsensus_hesapla(oylar, sig)

    hakem = None
    if k["gecerli_oy"] >= 2 and k["oydaslik"] < 50:
        hakem = await _hakem(veri, [o for o in oylar if o["durum"] == "tamam"])
        if hakem["durum"] == "tamam":
            k["final_yon"] = hakem["yön"]
            k["final_guven"] = hakem["guven"]
            k["hukum"] = "⚖️ HAKEM KARARI"

    return {
        "sembol": sig["sembol"],
        "zaman": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teknik": sig, "oylar": oylar, "hakem": hakem,
        "kurul": [o.get("bot_ad", o["model"]) for o in oylar],
        **k,
    }


def detay_paketi(sonuc: dict) -> str:
    """Analiz sonucunun DB'ye kaydedilecek kompakt JSON'u."""
    return json.dumps({
        "oylar": [{k: o.get(k) for k in
                   ("bot_ad", "bot_emoji", "model", "etiket", "durum", "yön",
                    "guven", "gerekce", "risk", "hata")}
                  for o in sonuc.get("oylar", [])],
        "hakem": sonuc.get("hakem"),
        "oy_dagilimi": sonuc.get("oy_dagilimi"),
        "teknik": {k: sonuc["teknik"].get(k) for k in
                   ("sembol", "taraf", "skor", "guven", "fiyat", "deg24", "rsi",
                    "funding", "oi_deg", "stop", "tp1", "tp2", "kaldirac", "rr")},
        "nedenler": sonuc["teknik"].get("nedenler", []),
    }, ensure_ascii=False)


def bildirim_metni(r: dict) -> tuple[str, str]:
    """(başlık, mesaj) — masaüstü bildirimi için."""
    emoji = {"LONG": "🟢", "SHORT": "🔴", "NÖTR": "⚪"}.get(r["final_yon"], "⚪")
    baslik = f"{emoji} {r['sembol']} — {r['hukum']}: {r['final_yon']}"
    mesaj = (f"Güven %{r['final_guven']} • Oydaşlık %{r['oydaslik']} • "
             f"Fiyat {r['teknik']['fiyat']:,.2f} • "
             f"{r['oy_dagilimi']['LONG']}L/{r['oy_dagilimi']['SHORT']}S/{r['oy_dagilimi']['NÖTR']}N")
    return baslik, mesaj
