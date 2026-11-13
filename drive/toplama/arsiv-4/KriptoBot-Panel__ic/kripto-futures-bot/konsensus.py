"""AI Konsensus Motoru — 4 model bağımsız oy verir, birbirini doğrular,
uyumsuzlukta hakem modeli nihaî kararı verir. Teknik motor tabanı oluşturur.

Akış:
  1) signal_engine ile canlı teknik veri + skor
  2) Her AI modeli AYNI piyasa verisini görüp bağımsız oyu (JSON) verir
  3) Oylar sayılır: oydaşlık >= %50 → konsensus; < %50 → HAKEM çağrılır
  4) Hakem tüm oyları + veriyi görüp nihaî kararı verir
"""
import asyncio
import json
import re
from datetime import datetime, timezone

import signal_engine as se
from config import EVREN_API_KEY, MODEL_CATALOG, model_available
from providers import _call_model, ChatError

# --- Oy verecek modeller: EVREN varsa 4'lü kurul, yoksa gömülü ikili ---
KURUL_EVREN = ["evren-glm", "evren-deepseek", "evren-qwen", "evren-gemma"]
KURUL_YEDEK = ["glm", "pollinations"]
HAKEM_EVREN = "evren-glm"
HAKEM_YEDEK = "glm"


def kurul() -> list[str]:
    if EVREN_API_KEY:
        return [m for m in KURUL_EVREN if model_available(m)]
    return [m for m in KURUL_YEDEK if model_available(m)]


def hakem_modeli() -> str:
    if EVREN_API_KEY and model_available(HAKEM_EVREN):
        return HAKEM_EVREN
    return HAKEM_YEDEK


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
    "Sen deneyimli bir kripto vadeli (futures) işlem analistisin. "
    "Aşağıdaki CANLI piyasa verisini incele ve TAMAMEN BAĞIMSIZ kararını ver. "
    "Funding ve OI gibi türev verileri kontra sinyal olarak da değerlendir. "
    "Yalnızca şu JSON'u döndür, başka hiçbir metin yazma:\n"
    '{"yön": "LONG veya SHORT veya NÖTR", "guven": 0-100, '
    '"gerekce": "en fazla 2 cümle", "risk": "düşük veya orta veya yüksek"}\n\n'
    "=== CANLI PİYASA VERİSİ ===\n{veri}\n\n"
    "Şimdi JSON oyu döndür."
)

HAKEM_PROMPTU = (
    "Sen bir HAKEM analistsin. 4 bağımsız model aynı piyasa verisine bakıp oy verdi "
    "ama oylar bölünmüş durumda. Piyasa verisini ve tüm oyları değerlendir, "
    "hangi yön savunulabilirse onu seç; kimse ikna edici değilse NÖTR ver. "
    "Yalnızca şu JSON'u döndür, başka metin yazma:\n"
    '{"yön": "LONG veya SHORT veya NÖTR", "guven": 0-100, '
    '"gerekce": "en fazla 3 cümle, oyları neden onayladın/aştın", '
    '"risk": "düşük veya orta veya yüksek"}\n\n'
    "=== PİYASA VERİSİ ===\n{veri}\n\n"
    "=== MODELLERİN OYLARI ===\n{oylar}\n\n"
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


async def _cagir_geri_cek(model_id: str, prompt: str, timeout: int = 120,
                          deneme: int = 3) -> str:
    """Model çağrısı + 503/zaman aşımında bekle-yeniden dene."""
    son_hata = ""
    for k in range(deneme):
        try:
            ham, _ = await asyncio.wait_for(
                _call_model(model_id, [{"role": "user", "content": prompt}]),
                timeout=timeout)
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


async def _oy_ver(model_id: str, veri: str) -> dict:
    """Bir modelden bağımsız oy al."""
    try:
        prompt = OY_PROMPTU.replace("{veri}", veri)
        ham = await _cagir_geri_cek(model_id, prompt)
        parsed = _json_ayikla(ham)
        if not parsed:
            raise ChatError(f"JSON çözümlenemedi: {ham[:120]}")
        return {"model": model_id, "etiket": MODEL_CATALOG[model_id]["etiket"],
                "durum": "tamam", **parsed, "ham": ham[:600]}
    except Exception as e:
        return {"model": model_id,
                "etiket": MODEL_CATALOG.get(model_id, {}).get("etiket", model_id),
                "durum": "hata", "hata": str(e)[:200]}


async def _hakem(veri: str, oylar: list[dict]) -> dict:
    mid = hakem_modeli()
    oy_metni = "\n".join(
        f"- {o['model']}: {o['yön']} (güven {o['guven']}, risk {o['risk']}) — {o['gerekce']}"
        for o in oylar)
    prompt = HAKEM_PROMPTU.replace("{veri}", veri).replace("{oylar}", oy_metni)
    try:
        ham = await _cagir_geri_cek(mid, prompt)
        parsed = _json_ayikla(ham)
        if not parsed:
            raise ChatError(f"hakem JSON çözülemedi: {ham[:120]}")
        return {"model": mid, "durum": "tamam", **parsed}
    except Exception as e:
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
    """Tam konsensus analizi: teknik + 4 bağımsız oy + (gerekirse) hakem."""
    sig = await se.generate_signal(sembol, interval)
    veri = _veri_paketi(sig)
    oylar = await asyncio.gather(*[_oy_ver(m, veri) for m in kurul()])
    k = _konsensus_hesapla(oylar, sig)

    hakem = None
    if k["gecerli_oy"] >= 2 and k["oydaslik"] < 50:
        hakem = await _hakem(veri, [o for o in oylar if o["durum"] == "tamam"])
        if hakem["durum"] == "tamam":
            k["final_yon"] = hakem["yön"]
            k["final_guven"] = hakem["guven"]
            k["hukum"] = "⚖️ HAKEM KARARI"

    return {
        "sembol": sig["sembol"], "zaman": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teknik": sig, "oylar": oylar, "hakem": hakem,
        "kurul": [m["model"] for m in oylar],
        **k,
    }


def bildirim_metni(r: dict) -> tuple[str, str]:
    """(başlık, mesaj) — masaüstü bildirimi için."""
    emoji = {"LONG": "🟢", "SHORT": "🔴", "NÖTR": "⚪"}.get(r["final_yon"], "⚪")
    baslik = f"{emoji} {r['sembol']} — {r['hukum']}: {r['final_yon']}"
    mesaj = (f"Güven %{r['final_guven']} • Oydaşlık %{r['oydaslik']} • "
             f"Fiyat {r['teknik']['fiyat']:,.2f} • "
             f"{r['oy_dagilimi']['LONG']}L/{r['oy_dagilimi']['SHORT']}S/{r['oy_dagilimi']['NÖTR']}N")
    return baslik, mesaj
