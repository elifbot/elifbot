"""KriptoBot Panel — masaüstü kripto sinyal + AI konsensus paneli.

Çalıştırma:  python panel.py
→ Sunucu 127.0.0.1:8543'te açılır ve tarayıcı otomatik açılır.
"""
import asyncio
import json
import os
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import bildirim
import botlar
import config
import konsensus
import market_data as md
import oto_trader
import signal_engine as se
import database as db
import exchange_trader as xt
from config import MODEL_CATALOG, model_available

oto = oto_trader.oto  # oto-işlem tekil örneği (tüm API uçları bunu kullanır)

BASE = Path(__file__).resolve().parent


# ============================================================ arka plan işi
async def otomatik_job() -> None:
    """İzleme listesindeki sembolleri tarar; eşik aşılırsa AI konsensusu
    doğrular, geçerse masaüstü bildirimi yollar."""
    semboller = set(db.get_watch_targets().keys())
    if not semboller:
        return
    print(f"⏱ [otomatik] Taranıyor: {', '.join(sorted(semboller))}")
    for sembol in sorted(semboller):
        try:
            sig = await se.generate_signal(sembol)
        except Exception as e:
            print(f"  ⚠️ {sembol}: teknik tarama hatası: {e}")
            continue
        if abs(sig["skor"]) < config.STRONG_ALERT_SCORE or sig["taraf"] == "NÖTR":
            print(f"  • {sembol}: teknik skor {sig['skor']:+d} — eşik altı, atlandı")
            continue
        try:
            sonuc = await konsensus.analiz_et(sembol)
        except Exception as e:
            print(f"  ⚠️ {sembol}: konsensus hatası: {e}")
            continue
        if (sonuc["final_yon"] in ("LONG", "SHORT")
                and sonuc["final_guven"] >= 60
                and not db.recent_analysis_alarm(sembol, sonuc["final_yon"],
                                                 config.ALERT_COOLDOWN_H)):
            db.save_analysis(
                sembol, sonuc["final_yon"], sonuc["final_guven"],
                sonuc["oydaslik"], sig["skor"], sig["fiyat"], sonuc["hukum"],
                json.dumps(_detay_paketi(sonuc), ensure_ascii=False), alarm=1)
            baslik, mesaj = konsensus.bildirim_metni(sonuc)
            bildirim.gonder(baslik, mesaj)
            print(f"  🚨 ALARM {sembol}: {baslik} — {mesaj}")
        else:
            print(f"  • {sembol}: konsensus {sonuc['final_yon']} "
                  f"(güven %{sonuc['final_guven']}) — alarm eşiği altı")


@asynccontextmanager
async def lifespan(app: FastAPI):
    kadro = botlar.kadroyu_kur()
    print(f"🤖 Bot kadrosu: " + ", ".join(
        f"{b['emoji']} {b['ad']} ({b['model']})" for b in kadro))
    sched = AsyncIOScheduler()
    sched.add_job(otomatik_job, "interval",
                  minutes=max(5, config.SCAN_INTERVAL_MIN), id="otomatik_tarama")
    sched.start()
    print(f"⏱ Otomatik tarama aktif: her {config.SCAN_INTERVAL_MIN} dk • "
          f"eşik |skor|≥{config.STRONG_ALERT_SCORE} • "
          f"bildirim: {bildirim.destekleniyor()}")
    yield
    sched.shutdown()


app = FastAPI(title="KriptoBot Panel", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/durum")
async def api_durum():
    kadro = db.botlari_yukle()
    return {
        "modeller": [{"ad": b["ad"], "emoji": b["emoji"], "model": b["model"],
                      "aktif": bool(b["aktif"])} for b in kadro],
        "hakem": (konsensus.hakem_botu() or {}).get("ad", "—"),
        "modeller_listesi": [
            {"id": mid, "etiket": M["etiket"], "uygun": model_available(mid)}
            for mid, M in MODEL_CATALOG.items()
        ],
        "roller": botlar.ROL_ACIKLAMA,
        "bildirim": bildirim.destekleniyor(),
        "tarama_dk": config.SCAN_INTERVAL_MIN,
        "esik": config.STRONG_ALERT_SCORE,
        "soylama": config.ALERT_COOLDOWN_H,
        "populer": config.SCAN_SYMBOLS,
        "izleme": db.get_watchlist(0),  # panel geneli: chat_id=0
        "istatistik": db.analysis_stats(),
    }


class SembolIn(BaseModel):
    sembol: str


@app.post("/api/analiz")
async def api_analiz(inp: SembolIn):
    sembol = inp.sembol.strip().upper().replace("/", "")
    if not sembol.endswith("USDT"):
        sembol += "USDT"
    try:
        if not await md.check_symbol(sembol):
            return JSONResponse(status_code=400,
                                content={"hata": f"{sembol} vadeli piyasada bulunamadı"})
        sonuc = await konsensus.analiz_et(sembol)
    except Exception as e:
        return JSONResponse(status_code=500, content={"hata": str(e)[:300]})
    alarm = 1 if (sonuc["final_yon"] in ("LONG", "SHORT")
                  and sonuc["final_guven"] >= 60
                  and sonuc["oydaslik"] >= 50) else 0
    db.save_analysis(sembol, sonuc["final_yon"], sonuc["final_guven"],
                     sonuc["oydaslik"], sonuc["teknik"]["skor"],
                     sonuc["teknik"]["fiyat"], sonuc["hukum"],
                     konsensus.detay_paketi(sonuc), alarm)
    botlar.sonuc_odaya_yaz(sonuc)
    if alarm:
        baslik, mesaj = konsensus.bildirim_metni(sonuc)
        bildirim.gonder(baslik, mesaj)
    return sonuc


@app.post("/api/tarama")
async def api_tarama():
    semboller = list(dict.fromkeys(db.get_watchlist(0) + config.SCAN_SYMBOLS))[:10]
    sonuclar = await asyncio.gather(
        *[se.generate_signal(s) for s in semboller], return_exceptions=True)
    rows = [r for r in sonuclar if isinstance(r, dict)]
    rows.sort(key=lambda x: abs(x["skor"]), reverse=True)
    for r in rows[:5]:
        db.save_analysis(r["sembol"], r["taraf"], r["guven"], 0,
                         r["skor"], r["fiyat"], "TEKNİK TARAMA", "{}", 0)
    return {"rows": [{
        "sembol": r["sembol"], "taraf": r["taraf"], "emoji": r["emoji"],
        "skor": r["skor"], "guven": r["guven"], "fiyat": r["fiyat"],
        "deg24": r["deg24"], "rsi": round(r["rsi"], 1),
        "funding": round(r["funding"] * 100, 3), "oi_deg": round(r["oi_deg"], 1),
        "kaldirac": r["kaldirac"],
    } for r in rows]}


@app.get("/api/gecmis")
async def api_gecmis(limit: int = 30):
    rows = db.get_analyses(limit)
    for r in rows:
        try:
            r["detay"] = json.loads(r["detay"]) if r["detay"] else {}
        except Exception:
            r["detay"] = {}
    return {"rows": rows}


@app.get("/api/alarmlar")
async def api_alarmlar():
    return {"rows": db.get_analyses(20, only_alarms=True)}


# ---------------------------------------------------------------- bot kadrosu
@app.get("/api/botlar")
async def api_botlar_getir():
    return {
        "botlar": db.botlari_yukle(),
        "roller": botlar.ROL_ACIKLAMA,
        "modeller": [{"id": mid, "etiket": M["etiket"],
                      "uygun": model_available(mid)}
                     for mid, M in MODEL_CATALOG.items()],
    }


class BotIn(BaseModel):
    ad: str
    emoji: str = "🤖"
    rol: str = "ozgur"
    model: str


@app.post("/api/botlar")
async def api_bot_ekle(inp: BotIn):
    ad = inp.ad.strip()[:30]
    if not ad:
        return JSONResponse(status_code=400, content={"hata": "Bot adı gerekli"})
    if inp.model not in MODEL_CATALOG:
        return JSONResponse(status_code=400,
                            content={"hata": f"Bilinmeyen model: {inp.model}"})
    if db.bot_bul(ad):
        return JSONResponse(status_code=400,
                            content={"hata": f"'{ad}' adında bir bot zaten var"})
    bid = db.bot_ekle(ad, inp.emoji.strip()[:4] or "🤖", inp.rol, inp.model)
    db.oda_ekle("⚙️ Sistem",
                f"{inp.emoji} {ad} kadroya katıldı! "
                f"Rolü: {botlar.ROL_ACIKLAMA.get(inp.rol, inp.rol)} • "
                f"Model: {inp.model}", tur="sistem", emoji="⚙️")
    return {"ok": True, "id": bid}


class BotGuncelle(BaseModel):
    ad: str | None = None
    emoji: str | None = None
    rol: str | None = None
    model: str | None = None
    aktif: bool | None = None


@app.post("/api/botlar/{bot_id}")
async def api_bot_guncelle(bot_id: int, inp: BotGuncelle):
    kv = {k: v for k, v in inp.model_dump().items() if v is not None}
    if "aktif" in kv:
        kv["aktif"] = 1 if kv["aktif"] else 0
    if kv.get("model") and kv["model"] not in MODEL_CATALOG:
        return JSONResponse(status_code=400,
                            content={"hata": f"Bilinmeyen model: {kv['model']}"})
    ok = db.bot_guncelle(bot_id, **kv)
    return {"ok": ok}


@app.delete("/api/botlar/{bot_id}")
async def api_bot_sil(bot_id: int):
    ok = db.bot_sil(bot_id)
    return {"ok": ok, "mesaj": "Bot kadrodan çıkarıldı" if ok else "Bot bulunamadı"}


# ---------------------------------------------------------------- bot odası
@app.get("/api/oda")
async def api_oda(son_id: int = 0):
    mesajlar = db.oda_gecmis(limit=120, son_id=son_id)
    return {"mesajlar": mesajlar, "mesgul": botlar.ODA_KILIDI.locked(),
            "son_id": db.oda_son_id()}


class OdaIn(BaseModel):
    metin: str


@app.post("/api/oda")
async def api_oda_gonder(inp: OdaIn):
    metin = inp.metin.strip()[:1000]
    if not metin:
        return JSONResponse(status_code=400, content={"hata": "Boş mesaj"})
    db.oda_ekle("👤 Sen", metin, tur="kullanici", emoji="👤")
    asyncio.create_task(botlar.gorev_yurut(metin))
    return {"ok": True, "mesgul": botlar.ODA_KILIDI.locked()}


@app.post("/api/oda/temizle")
async def api_oda_temizle():
    n = db.oda_temizle()
    db.oda_ekle("⚙️ Sistem", "Oda temizlendi. Botlara yeni bir görev verebilirsin.",
                tur="sistem", emoji="⚙️")
    return {"ok": True, "silinen": n}


class WatchIn(BaseModel):
    sembol: str
    ekle: bool = True


@app.post("/api/izleme")
async def api_izleme(inp: WatchIn):
    sembol = inp.sembol.strip().upper().replace("/", "")
    if not sembol.endswith("USDT"):
        sembol += "USDT"
    if inp.ekle:
        try:
            if not await md.check_symbol(sembol):
                return {"ok": False, "mesaj": f"{sembol} vadeli piyasada bulunamadı"}
        except Exception:
            return {"ok": False, "mesaj": "Veri kaynağına ulaşılamadı"}
        yeni = db.add_watch(0, sembol)
        return {"ok": True, "mesaj": f"{sembol} izlemeye alındı" if yeni
                else f"{sembol} zaten listede", "izleme": db.get_watchlist(0)}
    db.remove_watch(0, sembol)
    return {"ok": True, "mesaj": f"{sembol} listeden çıkarıldı",
            "izleme": db.get_watchlist(0)}


class AyarIn(BaseModel):
    tarama_dk: int | None = None
    esik: int | None = None


@app.post("/api/ayarlar")
async def api_ayarlar(inp: AyarIn):
    if inp.tarama_dk and 5 <= inp.tarama_dk <= 240:
        config.SCAN_INTERVAL_MIN = inp.tarama_dk
    if inp.esik is not None and 10 <= inp.esik <= 80:
        config.STRONG_ALERT_SCORE = inp.esik
    # .env'e de yaz (kalıcı)
    _env_guncelle({"SCAN_INTERVAL_MIN": str(config.SCAN_INTERVAL_MIN),
                   "STRONG_ALERT_SCORE": str(config.STRONG_ALERT_SCORE)})
    return {"ok": True, "tarama_dk": config.SCAN_INTERVAL_MIN,
            "esik": config.STRONG_ALERT_SCORE,
            "mesaj": "Ayarlar kaydedildi (uygulama yeniden başlayınca scheduler yeni süreyi alır)"}


def _env_guncelle(kv: dict) -> None:
    p = BASE / ".env"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    for k, v in kv.items():
        found = False
        for i, ln in enumerate(lines):
            if ln.startswith(f"{k}="):
                lines[i] = f"{k}={v}"
                found = True
        if not found:
            lines.append(f"{k}={v}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ============================================================ OTO İŞLEM API
async def _pozisyon_guncel(p: dict) -> dict:
    """Açık pozisyona güncel fiyat ve PnL hesaplayıp ekler."""
    try:
        if oto.broker:
            fiyat = await oto.broker.fiyat(p["sembol"])
        else:
            fiyat = (await md.fetch_snapshot(p["sembol"])).get("fiyat", 0)
    except Exception:
        fiyat = 0
    yon = 1 if p["taraf"] == "LONG" else -1
    pnl = (fiyat - p["giris"]) * p["miktar"] * yon if fiyat else 0
    marjin = p["miktar"] * p["giris"] / max(p["kaldirac"], 1)
    return {**p, "guncel": fiyat,
            "pnl": round(pnl, 4) if fiyat else 0,
            "pnl_pct": round(pnl / marjin * 100, 2) if fiyat and marjin else 0}


@app.get("/api/trade/durum")
async def api_trade_durum():
    acik = [await _pozisyon_guncel(p) for p in db.acik_pozisyonlar()]
    try:
        bakiye = await oto.broker.bakiye() if oto.broker else None
    except Exception:
        bakiye = None
    ist = db.trade_istatistik()
    if bakiye is not None:
        ist["bakiye"] = round(bakiye, 4)
    return {
        **oto.durum(),
        "secili_borsa": config.TRADE_EXCHANGE,
        "bakiye": bakiye,
        "acik": acik,
        "kapanan": db.kapananlar(15),
        "istatistik": ist,
        "loglar": db.tlog_son(60),
        "risk": {
            "pos_pct": config.RISK_POS_PCT,
            "max_positions": config.RISK_MAX_POSITIONS,
            "max_leverage": config.RISK_MAX_LEVERAGE,
            "daily_loss_pct": config.RISK_DAILY_LOSS_PCT,
            "min_guven": config.RISK_MIN_GUVEN,
            "scan_max": config.SCAN_MAX_SYMBOLS,
            "min_volume": config.MIN_VOLUME_USDT,
            "max_aday": config.OTO_MAX_ADAY,
            "timeout_h": config.POS_TIMEOUT_H,
            "cooldown_h": config.POS_COOLDOWN_H,
            "paper_balance": config.PAPER_BALANCE,
        },
        "anahtar_var": {
            "binance": bool(config.BINANCE_API_KEY and config.BINANCE_API_SECRET),
            "okx": bool(config.OKX_API_KEY and config.OKX_API_SECRET
                        and config.OKX_PASSPHRASE),
        },
    }


@app.post("/api/trade/baslat")
async def api_trade_baslat():
    try:
        mesaj = await oto.baslat()
    except xt.EmirHatasi as e:
        return JSONResponse(status_code=400, content={"hata": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"hata": str(e)[:300]})
    return {"ok": True, "mesaj": mesaj}


class DurdurIn(BaseModel):
    pozisyonlari_kapat: bool = False


@app.post("/api/trade/durdur")
async def api_trade_durdur(inp: DurdurIn | None = None):
    kapat = bool(inp.pozisyonlari_kapat) if inp else False
    mesaj = await oto.durdur(kapat)
    return {"ok": True, "mesaj": mesaj}


@app.post("/api/trade/kill")
async def api_trade_kill():
    mesaj = await oto.kill_switch()
    return {"ok": True, "mesaj": mesaj}


@app.post("/api/trade/pasif-sifirla")
async def api_trade_pasif_sifirla():
    return {"ok": True, "mesaj": await oto.pasif_sifirla()}


@app.post("/api/trade/tara")
async def api_trade_tara():
    if not oto.calisiyor:
        return JSONResponse(status_code=400, content={
            "hata": "Oto trader kapalı — önce 'Başlat'a bas. "
                    "(Manuel tarama emir güvenliğinden geçer)"})
    asyncio.create_task(oto.tarama_turu())
    return {"ok": True, "mesaj": "Tarama turu başlatıldı — sonuçlar "
                                 "trade loguna ve Bot Odası'na düşecek"}


@app.post("/api/trade/kapat/{pos_id}")
async def api_trade_kapat(pos_id: int):
    if not oto.broker:
        return JSONResponse(status_code=400, content={
            "hata": "Borsa bağlantısı yok — trader başlatılmadı"})
    try:
        ok = await oto.tek_kapat(pos_id, "👤 Manuel kapatma")
    except Exception as e:
        return JSONResponse(status_code=500, content={"hata": str(e)[:300]})
    return {"ok": ok, "mesaj": "Pozisyon kapatıldı" if ok
            else "Pozisyon bulunamadı veya zaten kapalı"}


class TradeAyarIn(BaseModel):
    mod: str | None = None          # kagit | testnet | gercek
    borsa: str | None = None        # binance | okx
    pos_pct: float | None = None
    max_positions: int | None = None
    max_leverage: int | None = None
    daily_loss_pct: float | None = None
    min_guven: int | None = None
    scan_max: int | None = None
    min_volume: float | None = None
    max_aday: int | None = None
    timeout_h: float | None = None
    cooldown_h: float | None = None
    paper_balance: float | None = None
    onay: str = ""                  # mod=gercek için 'RISKLI BILIYORUM'


@app.post("/api/trade/ayarlar")
async def api_trade_ayarlar(inp: TradeAyarIn):
    if oto.calisiyor:
        return JSONResponse(status_code=400, content={
            "hata": "Oto trader çalışıyor — önce Durdur, sonra ayarla"})
    hatalar = []
    env_kv = {}
    d = inp.model_dump(exclude_none=True)

    if "mod" in d:
        if d["mod"] not in ("kagit", "testnet", "gercek"):
            hatalar.append("Geçersiz mod")
        elif d["mod"] == "gercek" and inp.onay != "RISKLI BILIYORUM":
            hatalar.append("Gerçek emir modu için onay kutusunu işaretle")
    if "borsa" in d and d["borsa"] not in ("binance", "okx"):
        hatalar.append("Borsa binance veya okx olmalı")
    if "pos_pct" in d and not (0.5 <= d["pos_pct"] <= 50):
        hatalar.append("Pozisyon % 0.5-50 arası olmalı")
    if "max_positions" in d and not (1 <= d["max_positions"] <= 10):
        hatalar.append("Maks pozisyon 1-10 arası olmalı")
    if "max_leverage" in d and not (1 <= d["max_leverage"] <= 20):
        hatalar.append("Kaldıraç tavanı 1-20 arası olmalı")
    if "daily_loss_pct" in d and not (1 <= d["daily_loss_pct"] <= 50):
        hatalar.append("Günlük zarar limiti %1-50 arası olmalı")
    if "min_guven" in d and not (30 <= d["min_guven"] <= 95):
        hatalar.append("Güven eşiği %30-95 arası olmalı")
    if "scan_max" in d and not (5 <= d["scan_max"] <= 150):
        hatalar.append("Tarama sembol sayısı 5-150 arası olmalı")
    if "max_aday" in d and not (1 <= d["max_aday"] <= 5):
        hatalar.append("Aday sayısı 1-5 arası olmalı")
    if hatalar:
        return JSONResponse(status_code=400, content={"hata": "; ".join(hatalar)})

    # config'i güncelle + .env'e yaz
    AD_MAP = {
        "mod": "TRADE_MODE", "borsa": "TRADE_EXCHANGE",
        "pos_pct": "RISK_POS_PCT", "max_positions": "RISK_MAX_POSITIONS",
        "max_leverage": "RISK_MAX_LEVERAGE",
        "daily_loss_pct": "RISK_DAILY_LOSS_PCT",
        "min_guven": "RISK_MIN_GUVEN", "scan_max": "SCAN_MAX_SYMBOLS",
        "min_volume": "MIN_VOLUME_USDT", "max_aday": "OTO_MAX_ADAY",
        "timeout_h": "POS_TIMEOUT_H", "cooldown_h": "POS_COOLDOWN_H",
        "paper_balance": "PAPER_BALANCE",
    }
    for alan, env_adi in AD_MAP.items():
        if alan in d:
            setattr(config, env_adi, d[alan])
            env_kv[env_adi] = str(d[alan])
    if env_kv:
        _env_guncelle(env_kv)
    db.tlog(f"⚙️ Trade ayarları güncellendi: {env_kv}")
    return {"ok": True, "mesaj": "Ayarlar kaydedildi", "env": env_kv}


if __name__ == "__main__":
    import uvicorn

    PORT = int(os.getenv("PANEL_PORT", "8543"))
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    print(f"🌐 Panel: http://127.0.0.1:{PORT}  (kapatmak için Ctrl+C)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
