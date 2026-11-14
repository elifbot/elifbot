# -*- coding: utf-8 -*-
"""akis_test.py — OKX canlı akış (WebSocket) üzerinde 30 dakikalık gerçek zamanlı test.

Üç bot aynı canlı tick akışını alır, 5 saniyelik barlara toplanır, gerçek zamanlı
olarak pozisyon açar/kapatır. Hiçbir geçmiş veri kullanılmaz — akış canlıdır.

    python3 -m bot.canli.akis_test --dakika 30 --sembol 20
    python3 -m bot.canli.akis_test --kuru --dakika 2      # ağ yok: kendini dener

AKIŞ: wss://ws.okx.com:8443/ws/v5/public → {"channel":"trades","instId":...}
YEDEK: WebSocket kurulamazsa REST `/market/trades` 2 saniyede bir yoklanır.
Çıktı: runs/akis_<zaman>/ozet.json + her dakika runs/akis_<zaman>/ilerleme.json
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

try:                                        # paket içinden
    from .botlar import MotorV1, MotorV2, MotorV3, Taban
    from .canli_test import okx_semboller
except ImportError:                         # doğrudan betik
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from botlar import MotorV1, MotorV2, MotorV3, Taban            # type: ignore
    from canli_test import okx_semboller                            # type: ignore

BAR_SN = 5                                  # 5 saniyelik bar
WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
UA = {"User-Agent": "Mozilla/5.0 (kbot akis test)"}


class Akis:
    """Canlı tick → 5 sn bar → üç bot."""

    def __init__(self, semboller: list[str], ayar: Taban | None = None):
        self.semboller = list(semboller)
        self.ayar = ayar or Taban()
        self.botlar = {
            "v1 kbot (EMA+hacim)": MotorV1(self.ayar),
            "v2 kbot2 (rejim+komite)": MotorV2(self.ayar),
            "v3 kbot3 (kanit esikleri)": MotorV3(self.ayar),
        }
        self.kova: dict[str, dict] = {}
        self.bar_sayaci = 0
        self.tick_sayaci = 0
        self.baslangic = time.time()
        self.kilit = threading.Lock()
        self.son_hata = ""

    # --- tick
    def tick(self, sembol: str, fiyat: float, hacim: float, ts_ms: int) -> None:
        with self.kilit:
            self.tick_sayaci += 1
            b = ts_ms // (BAR_SN * 1000)
            k = self.kova.get(sembol)
            if k is None or k["b"] != b:
                if k is not None:
                    self._bar_besle(sembol, k)
                self.kova[sembol] = {"b": b, "o": fiyat, "h": fiyat, "l": fiyat,
                                     "c": fiyat, "v": hacim}
            else:
                k["h"] = max(k["h"], fiyat)
                k["l"] = min(k["l"], fiyat)
                k["c"] = fiyat
                k["v"] += hacim

    def _bar_besle(self, sembol: str, k: dict) -> None:
        self.bar_sayaci += 1
        for motor in self.botlar.values():
            motor.tick(sembol, k["o"], k["h"], k["l"], k["c"], k["v"])

    def kapat(self) -> None:
        with self.kilit:
            for s, k in self.kova.items():
                self._bar_besle(s, k)
            self.kova.clear()

    # --- özet
    def ozet(self) -> dict:
        sure = round(time.time() - self.baslangic, 1)
        sonuc = []
        for ad, m in self.botlar.items():
            o = m.ozet()
            o["acik_pozisyon"] = len(m.pozlar)
            o["acik_pnl_usd"] = round(sum(
                (m.c[s][-1] - p.giris) * p.miktar * p.yon - self.ayar.komisyon
                for s, p in m.pozlar.items() if m.c.get(s)), 2)
            sonuc.append({"surum": ad, **o})
        return {"sure_sn": sure, "tick": self.tick_sayaci, "bar": self.bar_sayaci,
                "sembol": len(self.semboller), "son_hata": self.son_hata,
                "sonuclar": sonuc}


def _ws_dongu(akis: Akis, bitis: float, durum: dict) -> None:
    """OKX public trades kanalı. Koparsa yeniden bağlanır."""
    try:
        import websocket                                   # websocket-client
    except ImportError as e:
        durum["hata"] = f"websocket-client yok: {e}"
        return

    def on_message(_ws, mesaj):
        try:
            d = json.loads(mesaj)
        except json.JSONDecodeError:
            return
        for t in d.get("data", []) or []:
            try:
                akis.tick(t["instId"], float(t["px"]), float(t["sz"]), int(t["ts"]))
            except (KeyError, TypeError, ValueError):
                continue

    def on_error(_ws, e):
        akis.son_hata = str(e)[:200]

    abone = {"op": "subscribe",
             "args": [{"channel": "trades", "instId": s} for s in akis.semboller]}
    while time.time() < bitis:
        try:
            ws = websocket.WebSocketApp(WS_URL, on_message=on_message, on_error=on_error)
            threading.Thread(target=ws.run_forever, kwargs={"ping_interval": 20},
                             daemon=True).start()
            time.sleep(1.0)
            ws.send(json.dumps(abone))
            durum["ws"] = "bagli"
            while time.time() < bitis and ws.sock and ws.sock.connected:
                time.sleep(1.0)
            ws.close()
        except Exception as e:                             # noqa: BLE001
            akis.son_hata = f"ws: {str(e)[:150]}"
            time.sleep(2)
    durum["ws"] = "bitti"


def _rest_yedek(akis: Akis, bitis: float, durum: dict) -> None:
    """WS yoksa: her 2 saniyede son işlemleri çek."""
    durum["rest"] = "calisiyor"
    while time.time() < bitis:
        for s in akis.semboller:
            if time.time() >= bitis:
                break
            try:
                url = f"https://www.okx.com/api/v5/market/trades?instId={s}&limit=1"
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                            timeout=8) as r:
                    d = json.loads(r.read().decode())["data"]
                for t in d:
                    akis.tick(s, float(t["px"]), float(t["sz"]), int(t["ts"]))
            except Exception as e:                          # noqa: BLE001
                akis.son_hata = f"rest: {str(e)[:150]}"
        time.sleep(2)
    durum["rest"] = "bitti"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dakika", type=float, default=30)
    ap.add_argument("--sembol", type=int, default=20)
    ap.add_argument("--kuru", action="store_true", help="ağ yok: sentetik akış")
    ap.add_argument("--etiket", default="")
    a = ap.parse_args(argv)

    if a.kuru:
        semboller = [f"S{i:02d}" for i in range(1, a.sembol + 1)]
    else:
        semboller = okx_semboller(a.sembol)
        print(f"semboller: {', '.join(semboller[:8])} ... ({len(semboller)})")

    akis = Akis(semboller)
    bitis = time.time() + a.dakika * 60
    etiket = a.etiket or time.strftime("akis_%Y%m%d_%H%M%S")
    d = Path("runs") / etiket
    d.mkdir(parents=True, exist_ok=True)
    durum: dict = {}

    if a.kuru:
        import random
        r = random.Random(7)
        fiyat = {s: 100.0 * r.uniform(0.5, 3) for s in semboller}
        while time.time() < bitis:
            simdi = int(time.time() * 1000)
            for s in semboller:
                fiyat[s] *= 1 + r.gauss(0, 0.0006)
                akis.tick(s, fiyat[s], r.uniform(0.5, 2.0), simdi)
            time.sleep(BAR_SN / 4)
        durum["ws"] = "kuru"
    else:
        ws_t = threading.Thread(target=_ws_dongu, args=(akis, bitis, durum), daemon=True)
        ws_t.start()
        time.sleep(min(15.0, a.dakika * 60 / 4))            # WS bağlantısına şans ver
        if akis.tick_sayaci == 0:                          # akış gelmiyorsa REST'e düş
            print("WS'ten veri gelmedi, REST yedeğine geçiliyor")
            durum["ws"] = "veri_yok"
            threading.Thread(target=_rest_yedek, args=(akis, bitis, durum),
                             daemon=True).start()
        while time.time() < bitis:                         # ilerleme kaydı
            kalan = int(bitis - time.time())
            (d / "ilerleme.json").write_text(json.dumps(
                {"kalan_sn": kalan, "tick": akis.tick_sayaci, "bar": akis.bar_sayaci,
                 **durum}, ensure_ascii=False), encoding="utf-8")
            if kalan % 60 < 5:
                print(f"  kalan {kalan // 60} dk · tick {akis.tick_sayaci} · "
                      f"bar {akis.bar_sayaci} · {durum}", flush=True)
            time.sleep(5)

    akis.kapat()
    o = akis.ozet()
    (d / "ozet.json").write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== {o['sure_sn']} sn · {o['tick']} tick · {o['bar']} bar · {o['sembol']} sembol")
    print(f"{'surum':<30}{'islem':>7}{'WR':>8}{'PF':>8}{'net':>12}{'acik':>6}{'acikPnL':>10}")
    for s in o["sonuclar"]:
        print(f"  {s['surum']:<28}{s['islem']:>7}{s['kazanma_orani'] * 100:>7.1f}%"
              f"{s['kar_faktoru']:>8.2f}{s['realize_usd']:>+11.2f}${s['acik_pozisyon']:>6}"
              f"{s['acik_pnl_usd']:>+10.2f}")
    print(f"\nyazildi: {d / 'ozet.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
