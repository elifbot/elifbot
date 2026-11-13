# -*- coding: utf-8 -*-
"""canli_6bot.py — TUM BOTLAR TEK AKISTA: TURBO v1 · OMEGA v1 · Uc-R (v5.1) · DORT (v6) · BES (v7) · ALTI (v1 kodu, TUM PIYASA).

Evren: 510 OKX USDT-SWAP sembolu tek WS aboneligi. BOT 1-5 yalniz ilk 30 sembolu isler
(eski kosularla ayni kimlik), BOT 6 tum piyasayi isler. Filtre: motor._evren_filtresi.

ÜÇ = TURBO ve OMEGA'nin iyi taraflarini tek botta birlestirir:
  giris  : 2/2 anlasma veya güçlü çöküş-SHORT istisnasi · zayıf LONG patlamasi RED
  cikis  : -10 $ stop · BE 3,5 · trail 6,0 · sıkı taban · tükeniş TP · parabolik 15 $ · zombi 8 dk


Veri kaynagi : OKX vadeli (USDT-SWAP) halka acik "trades" WebSocket akisi
Tick kovasi  : 500 ms -> delta_usd (gercek islem hacmi, $) + buy_usd (alici-agresif, $)
Adalet       : Ayni tick listesi 8 motora da beslenir.
v2 korumalari: v2/ortak.py (trend uyum · ters pozisyon kilidi · kar sonrasi kilit ·
               siki trailing · ters yon zaman asimi)
v3 korumalari: v3/ortak.py (FIX1 trend-donusu sartli zaman asimi · FIX2 kosullu ivme tavani ·
               FIX3 4,5x hacim · FIX4 900 sn stagnation · FIX5 golge defteri)

Kullanim:
    python canli_3bot.py --saat 3 --etiket 6bot --json logs/rapor_6bot.json
    python canli_3bot.py --saniye 60 --sembol 10 --etiket deneme6
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from collections import deque

import requests
import websockets

import acarbot_omega
import apex_bot
import hybrid_bot
import test_4bot
import turbo_engine
from v2 import ortak
from v3 import ortak as ortak3
from v2.apex_v2 import ApexV2
from v2.hybrid_v2 import HybridV2Plus
from v2.omega_v2 import OmegaV2
from v2.turbo_v2 import TurboV2
from v3.apex_v3 import ApexV3
from v3.hybrid_v3 import HybridV3Plus
from v3.omega_v3 import OmegaV3
from v3.turbo_v3 import TurboV3
from v5.birlesik import UcBot
from v51.birlesik_v51 import UcR
from v6.dort import DortBot
from v7.bes import BesBot
from v3 import ortak as _ortak3

OKX_REST = "https://www.okx.com"
OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
KOVA_MS = 500
PANEL_MS = 2000
RADAR_MS = 30000
VERI_ZAMAN_ASIMI = 20.0

KOK = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(KOK, "logs")


# ------------------------------------------------------------------ veri
def evren_sec(adet: int):
    ins = requests.get(f"{OKX_REST}/api/v5/public/instruments",
                       params={"instType": "SWAP"}, timeout=20).json()["data"]
    carpan = {}
    for i in ins:
        if i.get("settleCcy") != "USDT" or i.get("state") != "live":
            continue
        try:
            carpan[i["instId"]] = float(i.get("ctVal") or 1.0) * float(i.get("ctMult") or 1.0)
        except (TypeError, ValueError):
            carpan[i["instId"]] = 1.0
    tik = requests.get(f"{OKX_REST}/api/v5/market/tickers",
                       params={"instType": "SWAP"}, timeout=20).json()["data"]
    satirlar = []
    for t in tik:
        inst = t.get("instId")
        if inst not in carpan:
            continue
        try:
            px = float(t.get("last") or 0.0)
            hacim_usd = float(t.get("volCcy24h") or 0.0) * px
        except (TypeError, ValueError):
            continue
        if px <= 0 or hacim_usd < 25000:
            continue
        satirlar.append((hacim_usd, inst, px))
    satirlar.sort(reverse=True)
    return {inst: {"carpan": carpan[inst], "px0": px, "hacim24_usd": hacim_usd}
            for hacim_usd, inst, px in satirlar[:adet]}


# ------------------------------------------------------------------ motorlar
def motorlari_kur():
    """(id, panel etiketi, motor, besleme metodu, surum)"""
    return [
        ("BOT1_TURBO", "BOT 1 · TURBO v1 (30 sembol)", turbo_engine.RealTimeVolumeShockEngine(), "ingest_batch", "v1"),
        ("BOT2_OMEGA", "BOT 2 · OMEGA v1 (30 sembol)", acarbot_omega.AcarbotOmegaEngine(), "ingest_ticks", "v1"),
        ("BOT3_UC51", "BOT 3 · ÜÇ-R (v5.1 · 30 sembol)", UcR(), "ingest_batch", "v5.1"),
        ("BOT4_DORT", "BOT 4 · DÖRT (v6 · 30 sembol)", DortBot(), "ingest_batch", "v6"),
        ("BOT5_BES", "BOT 5 · BEŞ (v7 · 30 sembol)", BesBot(), "ingest_batch", "v7"),
        ("BOT6_ALTI", "BOT 6 · ALTI (TURBO v1 kodu · TÜM PİYASA)", turbo_engine.RealTimeVolumeShockEngine(), "ingest_batch", "v1"),
    ]


def besle(ad, motor, metod, ticks):
    try:
        filtre = getattr(motor, "_evren_filtresi", None)
        if filtre is not None:
            ticks = [t for t in ticks if _ortak3.baz(str(t.get("symbol") or "")) in filtre]
            if not ticks:
                return
        getattr(motor, metod)(ticks)
    except Exception:
        print(f"[{ad}] besleme hatasi:")
        traceback.print_exc()


def radar(motor, adet=8):
    cikti = []
    try:
        for key, tape in getattr(motor, "tapes", {}).items():
            fn = getattr(tape, "metrik", None) or getattr(tape, "metrics", None)
            if not callable(fn):
                continue
            try:
                m = fn(12.0)
            except TypeError:
                m = fn()
            if not m:
                continue
            cikti.append({"sembol": key,
                          "vol_mult": round(m.get("vol_mult", 0.0), 2),
                          "burst_usd": round(m.get("burst_usd", 0.0)),
                          "ret_pct": round(m.get("ret_burst_pct", 0.0), 3),
                          "akis": round(m.get("orderflow_bias", 0.0), 3)})
    except Exception:
        traceback.print_exc()
    cikti.sort(key=lambda x: x["vol_mult"], reverse=True)
    return cikti[:adet]


def satir(ad, etiket, motor, surum):
    try:
        snap = test_4bot.durum_al(motor)
        d = test_4bot.normalize(snap)
    except Exception:
        traceback.print_exc()
        snap, d = {}, {}
    ek = snap.get("ek") or {}
    return {"bot": ad, "etiket": etiket, "surum": surum,
            "kasa": round(float(d.get("kasa") or 0.0), 2),
            "realize": round(float(d.get("realize") or 0.0), 2),
            "acik_pnl": round(float(d.get("acik_pnl") or 0.0), 2),
            "acik": int(d.get("acik_adet") or 0),
            "kapanan": int(d.get("kapanan") or 0),
            "wr": round(float(d.get("wr") or 0.0), 3),
            "pf": d.get("pf"),
            "teminat": round(float(d.get("teminat") or 0.0), 2),
            "risk": round(float(d.get("risk") or 0.0), 2),
            "veto": d.get("veto") or {},
            "koruma": ek.get("koruma_veto") or {},
            "ek": ek}


# ------------------------------------------------------------------ kapanan takibi
def kapanan_kayitlar(motor):
    for attr in ("closed_trades", "kapanan"):
        d = getattr(motor, attr, None)
        if d is None:
            continue
        cikti = []
        for it in list(d):
            if isinstance(it, dict):
                cikti.append((it.get("id") or it.get("pos_id"), it.get("symbol"),
                              float(it.get("net_pnl_usd") or 0.0)))
            else:
                cikti.append((getattr(it, "id", None), getattr(it, "symbol", ""),
                              float(getattr(it, "net_pnl_usd", 0.0) or 0.0)))
        return cikti
    return []


# ------------------------------------------------------------------ durum
class Durum:
    def __init__(self, yol, etiket, saniye, evren, botlar):
        self.yol = yol
        self.etiket = etiket
        self.hedef_sn = saniye
        self.bitis = time.time() + saniye
        self.evren = evren
        self.baslangic = time.time()
        self.seri = {b[0]: deque(maxlen=1400) for b in botlar}
        self._seri_ts = 0.0
        self.olaylar = deque(maxlen=40)
        self.baglanti = {"durum": "hazirlaniyor", "deneme": 0, "son_hata": "",
                         "son_veri_ts": 0.0, "kopma": 0, "toplam_baglanti_sn": 0.0}
        self.tick = 0
        self.islem = 0
        self.botlar = []
        self.radar = []
        self._bagli_ts = 0.0

    def olay(self, metin):
        self.olaylar.appendleft({"t": time.strftime("%H:%M:%S"), "m": metin})
        print(f"  * {time.strftime('%H:%M:%S')} {metin}", flush=True)

    def baglandi(self):
        self.baglanti["durum"] = "bagli"
        self.baglanti["son_hata"] = ""
        self._bagli_ts = time.time()

    def koptu(self, hata):
        self.baglanti["durum"] = "koptu"
        self.baglanti["son_hata"] = str(hata)[:300]
        self.baglanti["kopma"] = int(self.baglanti.get("kopma") or 0) + 1
        if self._bagli_ts:
            self.baglanti["toplam_bagli_sn"] = round(
                float(self.baglanti.get("toplam_bagli_sn") or 0.0) + (time.time() - self._bagli_ts), 1)
            self._bagli_ts = 0.0

    def yaz(self, motorlar=None, radar_veri=None):
        simdi = time.time()
        if radar_veri is not None:
            self.radar = radar_veri
        if motorlar is not None:
            self.botlar = [satir(ad, et, m, sv) for ad, et, m, _md, sv in motorlar]
            if simdi - self._seri_ts >= 15.0:      # 15 sn'de bir örnek -> 1400 nokta ~ 5 saat
                self._seri_ts = simdi
                for s in self.botlar:
                    self.seri[s["bot"]].append({"t": time.strftime("%H:%M:%S"), "k": s["kasa"]})
            # işlem jurnalı (CSV) — koşu erken kapatılsa bile döküm kaybolmaz
            try:
                if not hasattr(self, "jurnal"):
                    from jurnal import IslemJurnali
                    self.jurnal = IslemJurnali(self.etiket)
                self.jurnal.yaz(motorlar, test_4bot.durum_al)
            except Exception:
                pass
        veri = {
            "baslik": "ACARBOT · 6 BOT TEK AKIS · 1-5 otuz sembol · 6 tüm piyasa",
            "etiket": self.etiket,
            "guncelleme": time.strftime("%H:%M:%S"),
            "baslangic": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.baslangic)),
            "gecen_sn": round(simdi - self.baslangic, 1),
            "hedef_sn": self.hedef_sn,
            "kalan_sn": round(max(0.0, self.hedef_sn - (simdi - self.baslangic)), 1),
            "bitti": (simdi - self.baslangic) >= self.hedef_sn,
            "baglanti": self.baglanti,
            "tick": self.tick,
            "islem": self.islem,
            "sembol_sayisi": len(self.evren),
            "semboller": sorted(self.evren.keys()),
            "botlar": self.botlar,
            "radar": self.radar,
            "seri": {k: list(v) for k, v in self.seri.items()},
            "olaylar": list(self.olaylar),
        }
        gecici = self.yol + ".tmp"
        with open(gecici, "w", encoding="utf-8") as fh:
            json.dump(veri, fh, ensure_ascii=False, indent=1)
        os.replace(gecici, self.yol)


# ------------------------------------------------------------------ oturum
async def oturum(durum, evren, motorlar, bitis, gorulen):
    kovalar = {}
    son_veri = time.time()
    v2_botlar = [(ad, m) for ad, _et, m, _md, sv in motorlar if sv == "v2"]
    v3_botlar = [(ad, m) for ad, _et, m, _md, sv in motorlar if sv == "v3"]

    async with websockets.connect(OKX_WS, ping_interval=20, ping_timeout=20,
                                  max_queue=None, close_timeout=10) as ws:
        args = [{"channel": "trades", "instId": inst} for inst in evren]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        durum.baglandi()
        durum.olay(f"WS baglandi - {len(evren)} sembol abone · {len(motorlar)} motor")

        async def alici():
            nonlocal son_veri
            async for ham in ws:
                if ham in ("pong", b"pong"):
                    continue
                try:
                    msg = json.loads(ham)
                except (ValueError, TypeError):
                    continue
                if msg.get("event"):
                    if msg["event"] == "error":
                        print("WS HATA:", msg, flush=True)
                    continue
                dizi = msg.get("data") or []
                if not dizi:
                    continue
                simdi = time.time()
                for tr in dizi:
                    inst = tr.get("instId")
                    meta = evren.get(inst)
                    if meta is None:
                        continue
                    try:
                        px = float(tr["px"])
                        sz = float(tr["sz"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    usd = sz * meta["carpan"] * px
                    kova = int(simdi * 1000 // KOVA_MS)
                    k = kovalar.get(inst)
                    if k is None or k["kova"] != kova:
                        k = {"kova": kova, "ts": simdi, "px": px, "delta": 0.0, "buy": 0.0}
                        kovalar[inst] = k
                    k["ts"] = simdi
                    k["px"] = px
                    k["delta"] += usd
                    if str(tr.get("side", "")).lower() == "buy":
                        k["buy"] += usd
                    durum.islem += 1
                son_veri = simdi
                durum.baglanti["son_veri_ts"] = round(simdi, 3)

        gorev = asyncio.create_task(alici())
        son_ping = time.time()
        son_panel = 0.0
        son_radar = 0.0
        try:
            while time.time() < durum.bitis:
                await asyncio.sleep(KOVA_MS / 1000.0)
                # ---- CANLI SURE UZATMA: logs/uzat_<etiket>.txt icine dakika yaz
                _uz = os.path.join(LOG_DIR, f"uzat_{durum.etiket}.txt")
                if os.path.exists(_uz):
                    try:
                        with open(_uz, encoding="utf-8") as _f:
                            _ek = float(_f.read().strip() or 0)
                        if _ek > 0:
                            durum.bitis += _ek * 60.0
                            durum.hedef_sn += _ek * 60.0
                            durum.olay(f"SURE UZATILDI: +{_ek:.0f} dk -> hedef "
                                       f"{durum.hedef_sn/60:.0f} dk (kalan {max(0,durum.bitis-time.time())/60:.0f} dk)")
                    except Exception as _e:
                        durum.olay(f"uzatma okunamadi: {_e}")
                    finally:
                        try:
                            os.remove(_uz)
                        except OSError:
                            pass
                simdi = time.time()

                if simdi - son_ping > 20:
                    son_ping = simdi
                    try:
                        await ws.send("ping")
                    except Exception:
                        pass
                if simdi - son_veri > VERI_ZAMAN_ASIMI:
                    raise ConnectionError(f"veri akisi {VERI_ZAMAN_ASIMI:.0f} sn kesildi (watchdog)")

                ticks = []
                for inst, k in list(kovalar.items()):
                    if k["delta"] <= 0:
                        continue
                    meta = evren[inst]
                    ticks.append({"exchange": "okx", "symbol": inst, "price": k["px"],
                                  "delta_usd": round(k["delta"], 4),
                                  "buy_usd": round(k["buy"], 4), "ts": k["ts"],
                                  "quote_vol_24h": meta["hacim24_usd"], "pct_24h": 0.0})
                    k["delta"] = 0.0
                    k["buy"] = 0.0

                if ticks:
                    durum.tick += len(ticks)
                    ortak.TREND.besle(ticks)                      # v2 trend olcumer
                    ortak3.TREND.besle(ticks)                     # v3 trend olcumer
                    for _t in ticks:                              # FIX5 golge fiyatlari
                        ortak3.GOLGE.fiyat(_t["symbol"], _t["price"], _t["ts"])
                    for ad, motor, metod in [(a, m, md) for a, _e, m, md, _s in motorlar]:
                        besle(ad, motor, metod, ticks)
                    ortak.DEFTER.senkron(v2_botlar)               # v2 ters pozisyon kilidi
                    ortak3.DEFTER.senkron(v3_botlar)              # v3 ters pozisyon kilidi
                    for ad, motor in v2_botlar:                   # v2 kar sonrasi kilit
                        for rid, sym, net in kapanan_kayitlar(motor):
                            anahtar = (ad, rid)
                            if rid is None or anahtar in gorulen:
                                continue
                            gorulen.add(anahtar)
                            ortak.KILIT.isaretle(ad, sym, net, simdi)
                    for ad, motor in v3_botlar:                   # v3 kar sonrasi kilit
                        for rid, sym, net in kapanan_kayitlar(motor):
                            anahtar = (ad, rid)
                            if rid is None or anahtar in gorulen:
                                continue
                            gorulen.add(anahtar)
                            ortak3.KILIT.isaretle(ad, sym, net, simdi)

                if simdi - son_radar >= RADAR_MS / 1000.0:
                    son_radar = simdi
                    durum.radar = radar(motorlar[min(3, len(motorlar) - 1)][2])
                    en = durum.radar[0] if durum.radar else None
                    if en:
                        print(f"[{int(simdi-durum.baslangic):>4}s] tick {durum.tick:>7} | "
                              f"radar: {en['sembol']} {en['vol_mult']}x ${en['burst_usd']}", flush=True)

                if simdi - son_panel >= PANEL_MS / 1000.0:
                    son_panel = simdi
                    durum.yaz(motorlar)
        finally:
            gorev.cancel()
            try:
                await ws.send(json.dumps({"op": "unsubscribe", "args": args}))
            except Exception:
                pass


# ------------------------------------------------------------------ ana kosu
async def kosu(sembol, saniye, json_yolu, etiket):
    os.makedirs(LOG_DIR, exist_ok=True)
    durum_yolu = os.path.join(LOG_DIR, f"durum_{etiket}.json")

    evren = None
    for deneme in range(1, 6):
        try:
            evren = evren_sec(sembol)
            if evren:
                break
        except Exception as exc:
            print(f"evren alinamadi ({exc}); {deneme}. deneme...", flush=True)
            await asyncio.sleep(3)
    if not evren:
        print("Evren secilemedi.")
        return 1

    print(f"evren ({len(evren)} sembol):")
    for inst, v in evren.items():
        print(f"  {inst:<20} 24s hacim {v['hacim24_usd']/1e9:6.2f} mlr $")
    print()

    motorlar = motorlari_kur()
    ilk30 = {_ortak3.baz(k) for k in list(evren.keys())[:30]}
    for ad, _et, motor, _md, _sv in motorlar:
        if ad != "BOT6_ALTI":
            motor._evren_filtresi = ilk30
    durum = Durum(durum_yolu, etiket, saniye, evren, motorlar)
    durum.olay("test basladi: " + ", ".join(f"{et}" for _a, et, _m, _md, _s in motorlar))
    durum.yaz(motorlar)
    print(f"hedef sure: {saniye/60:.1f} dakika | panel: {durum_yolu}\n" + "-" * 96, flush=True)

    deneme = 0
    gorulen = set()
    while time.time() < durum.bitis:
        deneme += 1
        durum.baglanti["deneme"] = deneme
        try:
            await oturum(durum, evren, motorlar, durum.bitis, gorulen)
        except Exception as exc:
            durum.koptu(exc)
            durum.yaz(motorlar)
            bekle = min(15.0, 2.0 * deneme)
            durum.olay(f"KOPMA #{durum.baglanti['kopma']} ({type(exc).__name__}: {str(exc)[:120]})"
                       f" -> {bekle:.0f} sn sonra yeniden baglaniyor")
            await asyncio.sleep(bekle)
            try:
                yeni = evren_sec(sembol)
                if yeni:
                    evren = yeni
            except Exception:
                pass

    durum.baglanti["durum"] = "bitti"
    son = [satir(ad, et, m, sv) for ad, et, m, _md, sv in motorlar]
    durum.botlar = son
    durum.yaz()

    detay = {}
    for (ad, _et, motor, _md, _sv) in motorlar:
        try:
            snap = test_4bot.durum_al(motor)
            acik = snap.get("open_positions")
            if acik is None:
                pozlar = getattr(motor, "positions", None) or getattr(motor, "pozisyonlar", {}) or {}
                acik = []
                for p in pozlar.values():
                    try:
                        acik.append(p.to_dict() if hasattr(p, "to_dict") else p.to_public_dict())
                    except Exception:
                        acik.append({"symbol": getattr(p, "symbol", ""),
                                     "side": getattr(p, "side", getattr(p, "yon", 0)),
                                     "net_pnl_usd": getattr(p, "net_pnl_usd", 0.0)})
            detay[ad] = {"acik_pozisyonlar": acik or [],
                         "kapanan_islemler": (snap.get("closed_trades") or [])[:40],
                         "olaylar": (snap.get("events") or [])[:10]}
        except Exception:
            traceback.print_exc()
    # cekirdek tabanli botlarin kapanan listesi snapshot'ta yok -> dogrudan al
    for (ad, _et, motor, _md, _sv) in motorlar:
        if ad not in detay:
            continue
        if not detay[ad]["kapanan_islemler"] and hasattr(motor, "kapanan"):
            detay[ad]["kapanan_islemler"] = list(motor.kapanan)[:40]

    rapor = {
        "test": "6 BOT TEK AKIS (TURBO v1 + OMEGA v1 + UC-R + DORT + BES + ALTI tum piyasa)",
        "borsa": "OKX USDT-SWAP (gercek trades akisi)",
        "baslangic": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(durum.baslangic)),
        "bitis": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sure_sn": round(time.time() - durum.baslangic, 1),
        "hedef_sn": saniye,
        "kopma_sayisi": durum.baglanti["kopma"],
        "sembol_sayisi": len(evren),
        "semboller": list(evren.keys()),
        "toplam_tick": durum.tick,
        "toplam_islem": durum.islem,
        "sonuc": son,
        "koruma_veto": {**{k: dict(v) for k, v in ortak.VETO.items()},
                        **{k: dict(v) for k, v in ortak3.VETO.items()}},
        "golge_ozet": ortak3.GOLGE.ozet(),
        "radar_son": durum.radar,
        "olaylar": list(durum.olaylar),
        "detay": detay,
        "seri": {k: list(v) for k, v in durum.seri.items()},
    }
    if json_yolu:
        with open(json_yolu, "w", encoding="utf-8") as fh:
            json.dump(rapor, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\nrapor yazildi: {json_yolu}")

    print("\n" + "=" * 108)
    basliklar = ["BOT", "Kasa", "Getiri%", "Realize", "Acik PnL", "Acik", "Kapanan", "WR", "PF",
                 "Teminat", "Risk"]
    genislik = [18, 10, 9, 9, 10, 6, 9, 7, 6, 9, 8]
    def b(deger, w): return ("%s" % deger).rjust(w)
    print("".join(b(x, w) for x, w in zip(basliklar, genislik)))
    print("-" * sum(genislik))
    for s in son:
        getiri = (float(s["kasa"]) - 1000.0) / 10.0
        pf = s["pf"]
        deger = [s["etiket"], "%.2f" % s["kasa"], "%+.2f" % getiri, "%+.2f" % s["realize"],
                 "%+.2f" % s["acik_pnl"], "%d" % s["acik"], "%d" % s["kapanan"],
                 "%%%.0f" % (100.0 * s["wr"]), "-" if pf is None else "%.2f" % float(pf),
                 "%.0f" % s["teminat"], "%.0f" % s["risk"]]
        print("".join(b(v, w) for v, w in zip(deger, genislik)))
    print("\nkoruma veto (v2):", json.dumps({k: v for k, v in ortak.VETO.items()}, ensure_ascii=False))
    print("koruma veto (v3):", json.dumps({k: v for k, v in ortak3.VETO.items()}, ensure_ascii=False))
    print("golge defteri (v3):", json.dumps({k: v for k, v in ortak3.GOLGE.ozet().items() if k != "ornek"}, ensure_ascii=False))
    print(f"kopma: {durum.baglanti['kopma']} | tick: {durum.tick} | islem: {durum.islem}")
    print("KAZANAN: %s" % max(son, key=lambda s: s["kasa"])["etiket"])
    return 0


def main():
    ap = argparse.ArgumentParser(description="6 bot tek akis")
    ap.add_argument("--dakika", type=float, default=30.0)
    ap.add_argument("--saat", type=float, default=None)
    ap.add_argument("--saniye", type=float, default=None)
    ap.add_argument("--sembol", type=int, default=999)
    ap.add_argument("--json", default=None)
    ap.add_argument("--etiket", default="6bot")
    a = ap.parse_args()
    saniye = a.saniye if a.saniye else (a.saat * 3600.0 if a.saat else a.dakika * 60.0)
    return asyncio.run(kosu(a.sembol, saniye, a.json, a.etiket))


if __name__ == "__main__":
    sys.exit(main())
