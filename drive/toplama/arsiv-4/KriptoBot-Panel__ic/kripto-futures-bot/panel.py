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
import config
import konsensus
import market_data as md
import signal_engine as se
import database as db
from config import MODEL_CATALOG, model_available

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


def _detay_paketi(sonuc: dict) -> dict:
    """Analiz sonucunun DB'ye kaydedilecek kompakt hali."""
    return {
        "oylar": [{k: o.get(k) for k in ("model", "etiket", "durum", "yön",
                                         "guven", "gerekce", "risk", "hata")}
                  for o in sonuc.get("oylar", [])],
        "hakem": sonuc.get("hakem"),
        "oy_dagilimi": sonuc.get("oy_dagilimi"),
        "teknik": {k: sonuc["teknik"].get(k) for k in
                   ("sembol", "taraf", "skor", "guven", "fiyat", "deg24", "rsi",
                    "funding", "oi_deg", "stop", "tp1", "tp2", "kaldirac", "rr")},
        "nedenler": sonuc["teknik"].get("nedenler", []),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    kur = konsensus.kurul()
    return {
        "modeller": [{"id": m, "etiket": MODEL_CATALOG[m]["etiket"],
                      "uygun": model_available(m)} for m in kur],
        "hakem": konsensus.hakem_modeli(),
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
                     json.dumps(_detay_paketi(sonuc), ensure_ascii=False), alarm)
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


if __name__ == "__main__":
    import uvicorn

    PORT = int(os.getenv("PANEL_PORT", "8543"))
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    print(f"🌐 Panel: http://127.0.0.1:{PORT}  (kapatmak için Ctrl+C)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
