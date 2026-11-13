# -*- coding: utf-8 -*-
"""replay_6bot.py — 6 botu 60 dakikalık piyasa zamanında koşturan çevrimdışı koşucu.

NE YAPAR
--------
`canli_6bot.py` ile **aynı 6 motoru**, **aynı besleme metodlarını** (ingest_batch /
ingest_ticks) ve **aynı tick şemasını** kullanır. Tek fark: tick'ler OKX WebSocket'
inden değil, `sentetik_besleme.SentetikPiyasa`'dan gelir ve saat sanaldır.

Motor kodu değiştirilmez. `time.time` modül düzeyinde sanal saate bağlanır; böylece
motorların kendi iç zamanlayıcıları (kovalama filtresi, zombi poz süresi, soğuma
kilitleri, kâr süzülmesi) gerçek 60 dakika beklenmeden, 60 dakikalık piyasa
zamanında çalışır.

ÇIKTI
-----
runs/<etiket>/durum.json          panelin okuduğu canlı durum (canli_6bot ile aynı şema)
runs/<etiket>/islem_jurnali.csv   kapanan her işlem (canli_6bot sütunlarıyla aynı)
runs/<etiket>/rapor.json          özet + kasa eğrisi + kaldıraç ölçümleri
runs/<etiket>/metrikler.txt       metrikler.py çıktısı
runs/<etiket>/ozet.md             insan okunur tablo

KULLANIM
--------
    python3 bot/tools/replay_6bot.py --dakika 60 --etiket 6bot_60dk
    python3 bot/tools/replay_6bot.py --dakika 60 --seed 7 --sembol 510
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics as st
import sys
import time
import traceback

BURASI = os.path.dirname(os.path.abspath(__file__))
BOT_KOK = os.path.dirname(BURASI)                  # bot/
REPO_KOK = os.path.dirname(BOT_KOK)                # depo kökü
ACAR = os.path.join(BOT_KOK, "acarbot_6bot")

# --- sanal saat: motorlar import edilmeden ÖNCE kurulur -------------------
class _Saat:
    simdi: float = 0.0
    hiz: float = 1.0


def _vtime() -> float:
    return _Saat.simdi


time.time = _vtime  # noqa: A001 - bilinçli global yama (motorlar time.time() çağırır)

sys.path.insert(0, ACAR)
sys.path.insert(0, os.path.join(ACAR, "motorlar"))
sys.path.insert(0, BURASI)

import canli_6bot                       # noqa: E402
import jurnal                            # noqa: E402
import test_4bot                         # noqa: E402
from v3 import ortak as ortak3           # noqa: E402
from sentetik_besleme import SentetikPiyasa, PiyasaAyari, evren_yukle  # noqa: E402


class GercekBesleme:
    """GERÇEK piyasa tick arşivini oynatır (sentetik değil).

    Beklenen CSV başlığı (fazlası yok sayılır):
        ts,symbol,price,delta_usd,buy_usd,quote_vol_24h
    ts: saniye (float) veya milisaniye (1e12'den büyükse ms kabul edilir)

    Kaynak örnekleri: Binance aggTrades / OKX trades dump, kendi kaydettiğin
    canli_6bot tick jurnalı, data.binance.vision indirmeleri.
    """

    def __init__(self, yol: str, bucket_sn: float) -> None:
        self.bucket_sn = bucket_sn
        self.kova: dict[int, list[dict]] = {}
        with open(yol, encoding="utf-8") as fh:
            okuyucu = csv.DictReader(fh)
            for r in okuyucu:
                try:
                    ts = float(r.get("ts") or r.get("zaman") or 0)
                    if ts > 1e11:            # milisaniye
                        ts /= 1000.0
                    px = float(r["price"] if "price" in r else r["fiyat"])
                except (KeyError, TypeError, ValueError):
                    continue
                if ts <= 0 or px <= 0:
                    continue
                k = int(ts / self.bucket_sn)
                self.kova.setdefault(k, []).append({
                    "exchange": "gercek", "symbol": r.get("symbol") or r.get("sembol"),
                    "price": px,
                    "delta_usd": float(r.get("delta_usd") or 0.0),
                    "buy_usd": float(r.get("buy_usd") or 0.0),
                    "ts": ts,
                    "quote_vol_24h": float(r.get("quote_vol_24h") or 0.0),
                    "pct_24h": 0.0,
                })
        if not self.kova:
            raise ValueError(f"gercek veri okunamadi: {yol}")
        self.ilk_kova = min(self.kova)
        self.son_kova = max(self.kova)
        self.adim = self.ilk_kova
        self.semboller = sorted({t["symbol"] for v in self.kova.values() for t in v})

    @property
    def bitti(self) -> bool:
        return self.adim > self.son_kova

    def ticks(self, ts: float) -> list[dict]:
        k = int(ts / self.bucket_sn)
        self.adim = k
        return self.kova.get(k, [])

    @property
    def fiyatlar(self) -> dict:
        son = {}
        for k in sorted(self.kova)[:1]:
            for t in self.kova[k]:
                son[t["symbol"]] = t["price"]
        return son


BUCKET_SN = 0.5
PANEL_HER_SN = 10.0


def _baslangic_epoch(gun: str = "2026-11-13 19:00:00") -> float:
    return time.mktime(time.strptime(gun, "%Y-%m-%d %H:%M:%S"))


def _motorlari_hazirla(ilk30: set[str]):
    motorlar = canli_6bot.motorlari_kur()
    for ad, _et, motor, _md, _sv in motorlar:
        if ad != "BOT6_ALTI":
            motor._evren_filtresi = ilk30
    return motorlar


def _besle(ad: str, motor, metod: str, ticks: list[dict]) -> None:
    filtre = getattr(motor, "_evren_filtresi", None)
    if filtre is not None:
        ticks = [t for t in ticks if ortak3.baz(str(t.get("symbol") or "")) in filtre]
        if not ticks:
            return
    try:
        getattr(motor, metod)(ticks)
    except Exception:
        print(f"[{ad}] besleme hatasi:")
        traceback.print_exc()


def _kasa_egrisi(motorlar, adim: int) -> dict:
    cikti = {}
    for ad, _et, motor, _md, _sv in motorlar:
        try:
            d = test_4bot.normalize(test_4bot.durum_al(motor))
            cikti[ad] = round(float(d.get("kasa") or 0.0), 2)
        except Exception:
            cikti[ad] = 0.0
    return cikti


def _maks_dusus(seri: list[float]) -> float:
    tepe, mdd = -math.inf, 0.0
    for x in seri:
        tepe = max(tepe, x)
        mdd = min(mdd, x - tepe)
    return round(mdd, 2)


def kosu(dakika: float, sembol: int, seed: int, etiket: str, bucket: float,
         besleme_tipi: str = "sentetik", ticks_yolu: str = "") -> int:
    global BUCKET_SN
    BUCKET_SN = bucket
    sure_sn = dakika * 60.0
    adim_sayisi = int(round(sure_sn / BUCKET_SN))
    cikti_dir = os.path.join(REPO_KOK, "runs", etiket)
    os.makedirs(cikti_dir, exist_ok=True)
    for eski in ("islem_jurnali.csv", "durum.json"):
        yol = os.path.join(cikti_dir, eski)
        if os.path.exists(yol):
            os.remove(yol)

    # --- besleme: sentetik (davranış testi) veya gerçek tik arşivi ---------
    if besleme_tipi == "csv":
        if not ticks_yolu or not os.path.exists(ticks_yolu):
            print(f"gercek veri dosyasi yok: {ticks_yolu}")
            return 1
        gercek = GercekBesleme(ticks_yolu, BUCKET_SN)
        semboller = gercek.semboller
        adim_sayisi = min(adim_sayisi, gercek.son_kova - gercek.ilk_kova + 1)
        piyasa = gercek
        baslangic = gercek.ilk_kova * BUCKET_SN
        print(f"GERCEK VERI: {ticks_yolu} | {len(semboller)} sembol | "
              f"{adim_sayisi} bucket | gercek piyasa zamani")
    else:
        # --- evren: gerçek sembol adları (kayıtlı durum dosyasından) -------
        kaynak = os.path.join(ACAR, "loglar", "durum_6bot_ILK25DK.json")
        semboller = evren_yukle(kaynak, adet=max(sembol, 40))
        piyasa = SentetikPiyasa(semboller, PiyasaAyari(sure_sn=sure_sn, bucket_sn=BUCKET_SN, seed=seed))

    motorlar = _motorlari_hazirla({ortak3.baz(s) for s in semboller[:30]})
    jwt = jurnal.IslemJurnali(etiket, klasor=cikti_dir)

    if besleme_tipi != "csv":
        baslangic = _baslangic_epoch()
    _Saat.simdi = baslangic
    durum_yolu = os.path.join(cikti_dir, "durum.json")

    print(f"evren: {len(semboller)} sembol (ilk 30 -> BOT1-5, hepsi -> BOT6)")
    print(f"sure: {dakika:.0f} dk piyasa zamani | bucket {BUCKET_SN}s | adim {adim_sayisi} | seed {seed}")
    print("-" * 92, flush=True)

    toplam_tick = 0
    islem_sayaci = 0
    kasa_serisi: dict[str, list[float]] = {ad: [] for ad, *_ in motorlar}
    t0 = time.perf_counter()
    son_panel = -1e9

    for adim in range(adim_sayisi):
        _Saat.simdi = baslangic + adim * BUCKET_SN
        ticks = piyasa.ticks(_Saat.simdi)
        if besleme_tipi == "csv" and getattr(piyasa, "bitti", False):
            break
        if not ticks:
            continue
        toplam_tick += len(ticks)
        for t in ticks:
            ortak3.GOLGE.fiyat(t["symbol"], t["price"], t["ts"])
        for ad, _et, motor, metod, _sv in motorlar:
            _besle(ad, motor, metod, ticks)

        if _Saat.simdi - son_panel >= PANEL_HER_SN:
            son_panel = _Saat.simdi
            islem_sayaci += jwt.yaz(motorlar, test_4bot.durum_al)
            egri = _kasa_egrisi(motorlar, adim)
            for k, v in egri.items():
                kasa_serisi[k].append(v)
            _durum_yaz(durum_yolu, motorlar, piyasa, semboller, baslangic, etiket, toplam_tick)
            gecen = _Saat.simdi - baslangic
            if adim % max(1, int(60 / BUCKET_SN)) == 0:
                en_iyi = max(egri.items(), key=lambda kv: kv[1])
                print(f"[{gecen/60:5.1f} dk] tick {toplam_tick:>8} | islem {islem_sayaci:>4} | "
                      f"en iyi: {en_iyi[0]} {en_iyi[1]:.2f}$", flush=True)

    gecen_wall = time.perf_counter() - t0
    islem_sayaci += jwt.yaz(motorlar, test_4bot.durum_al)
    _durum_yaz(durum_yolu, motorlar, piyasa, semboller, baslangic, etiket, toplam_tick)

    # --- özet ------------------------------------------------------------
    satirlar = [canli_6bot.satir(ad, et, m, sv) for ad, et, m, _md, sv in motorlar]
    rapor = {
        "test": "6 BOT TEK AKIS — 60 dk piyasa zamani (cevrimdisi replay)",
        "besleme": ("GERCEK PIYASA VERISI" if besleme_tipi == "csv" else
                     "SENTETIK (OKX/Binance'e ag erisimi yok) — kenar olcumu DEGIL, davranis olcumu"),
        "etiket": etiket,
        "baslangic": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(baslangic)),
        "sure_dk": dakika,
        "bucket_sn": BUCKET_SN,
        "adim": adim_sayisi,
        "seed": seed,
        "sembol_sayisi": len(semboller),
        "toplam_tick_satiri": toplam_tick,
        "toplam_islem": islem_sayaci,
        "duvar_suresi_sn": round(gecen_wall, 1),
        "sonuc": satirlar,
        "kasa_egrisi": kasa_serisi,
        "maks_dusus_usd": {k: _maks_dusus(v) for k, v in kasa_serisi.items() if v},
        "son": {k: (v[-1] if v else 0.0) for k, v in kasa_serisi.items()},
        "koruma_veto": {**{k: dict(v) for k, v in ortak3.VETO.items()}},
        "olaylar": [
            f"replay basladi: {dakika:.0f} dk piyasa zamani, seed {seed}",
            f"motor sayisi: {len(motorlar)}, sembol: {len(semboller)}",
            f"toplam tick satiri: {toplam_tick}, kapanan islem: {islem_sayaci}",
            f"duvar suresi: {gecen_wall:.1f} sn (hizlanmis replay)",
        ],
    }
    with open(os.path.join(cikti_dir, "rapor.json"), "w", encoding="utf-8") as fh:
        json.dump(rapor, fh, ensure_ascii=False, indent=2, default=str)

    _ozet_yaz(os.path.join(cikti_dir, "ozet.md"), rapor)

    # --- metrikler (paketin kendi metrikler.py'si) ------------------------
    sys.path.insert(0, ACAR)
    import metrikler as paket_metrikler
    from contextlib import redirect_stdout
    from io import StringIO
    buf = StringIO()
    with redirect_stdout(buf):
        paket_metrikler.main(jwt.yol)
    metin = buf.getvalue()
    with open(os.path.join(cikti_dir, "metrikler.txt"), "w", encoding="utf-8") as fh:
        fh.write(metin)
    print(metin)

    print(f"\n{'BOT':<16}{'Kasa':>9}{'Getiri%':>9}{'Realize':>9}{'AcikPnL':>9}{'Acik':>6}"
          f"{'Kapanan':>9}{'WR':>7}{'PF':>7}{'Teminat':>9}{'Kaldirac':>10}")
    print("-" * 104)
    for s in satirlar:
        kaldirac = (s["teminat"] * 10.0) / max(1.0, s["kasa"])
        print(f"{s['etiket'][:16]:<16}{s['kasa']:>9.2f}{(s['kasa']-1000)/10:>+9.2f}"
              f"{s['realize']:>+9.2f}{s['acik_pnl']:>+9.2f}{s['acik']:>6}{s['kapanan']:>9}"
              f"{s['wr']:>7.3f}{('-' if s['pf'] is None else f'{s[chr(112)+chr(102)]:.2f}'):>7}"
              f"{s['teminat']:>9.0f}{kaldirac:>9.1f}x")
    print(f"\njurnal: {jwt.yol}")
    print(f"rapor : {os.path.join(cikti_dir, 'rapor.json')}")
    print(f"duvar suresi: {gecen_wall:.1f} sn")
    return 0


def _durum_yaz(yol, motorlar, piyasa, semboller, baslangic, etiket, toplam_tick) -> None:
    botlar = [canli_6bot.satir(ad, et, m, sv) for ad, et, m, _md, sv in motorlar]
    durum = {
        "baslik": "ACARBOT · 6 BOT · cevrimdisi replay (SENTETIK besleme)",
        "etiket": etiket,
        "guncelleme": time.strftime("%H:%M:%S", time.localtime(_Saat.simdi)),
        "baslangic": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(baslangic)),
        "gecen_sn": round(_Saat.simdi - baslangic, 1),
        "tick": toplam_tick,
        "sembol_sayisi": len(semboller),
        "semboller": semboller,
        "botlar": botlar,
        "fiyatlar": {k: round(v, 8) for k, v in list(piyasa.fiyatlar.items())[:60]},
    }
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as fh:
        json.dump(durum, fh, ensure_ascii=False, default=str)
    os.replace(gecici, yol)


def _ozet_yaz(yol: str, rapor: dict) -> None:
    s = rapor["sonuc"]
    cizgi = ["| # | Bot | Kural seti | Kasa | Realize | Açık PnL | Açık | Kapanan | WR | PF | Teminat | Kaldıraç | MaksDD |",
             "|---|-----|-----------|------|---------|----------|------|---------|----|----|---------|----------|--------|"]
    for i, b in enumerate(s, 1):
        kaldirac = (b["teminat"] * 10.0) / max(1.0, b["kasa"])
        mdd = rapor["maks_dusus_usd"].get(b["bot"], 0.0)
        pf = "-" if b["pf"] is None else f"{float(b['pf']):.2f}"
        cizgi.append(f"| {i} | {b['etiket']} | {b['surum']} | {b['kasa']:.2f} | {b['realize']:+.2f} | "
                     f"{b['acik_pnl']:+.2f} | {b['acik']} | {b['kapanan']} | {b['wr']*100:.0f}% | {pf} | "
                     f"{b['teminat']:.0f} | {kaldirac:.1f}x | {mdd:+.2f} |")
    metin = f"""# 60 dakikalık 6-bot koşusu — özet

- **Besleme:** SENTETİK (bu ortamda OKX/Binance'e ağ erişimi yok). Sonuç **kenar (edge) ölçümü değildir**;
  motor davranışı, risk kuralı uyumu ve kasa/kaldıraç dinamiği ölçümüdür.
- **Piyasa zamanı:** {rapor['sure_dk']:.0f} dk · bucket {rapor['bucket_sn']}s · adım {rapor['adim']} · seed {rapor['seed']}
- **Evren:** {rapor['sembol_sayisi']} sembol (ilk 30 → BOT1-5, hepsi → BOT6)
- **Tick satırı:** {rapor['toplam_tick_satiri']} · **kapanan işlem:** {rapor['toplam_islem']}
- **Duvar süresi:** {rapor['duvar_suresi_sn']} sn (hızlandırılmış replay)

""" + "\n".join(cizgi) + f"""

> Kaldıraç = (kullanılan teminat × 10) / kasa. 1.0x = kasa kadar notional; 12x = kasanın 12 katı
> notional. Cross marjinde bu oran, %{100/12:.1f} ters harekette kasanın tamamının gitmesi demektir.
"""
    with open(yol, "w", encoding="utf-8") as fh:
        fh.write(metin)


def main() -> int:
    ap = argparse.ArgumentParser(description="6 botu cevrimdisi, sanal saatle kos")
    ap.add_argument("--dakika", type=float, default=60.0)
    ap.add_argument("--sembol", type=int, default=510)
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--bucket", type=float, default=0.5)
    ap.add_argument("--etiket", default="6bot_60dk")
    ap.add_argument("--besleme", choices=["sentetik", "csv"], default="sentetik",
                    help="csv = GERCEK tik arsivi oynat")
    ap.add_argument("--ticks", default="", help="gercek tick CSV yolu (--besleme csv ile)")
    a = ap.parse_args()
    return kosu(a.dakika, a.sembol, a.seed, a.etiket, a.bucket, a.besleme, a.ticks)


if __name__ == "__main__":
    sys.exit(main())
