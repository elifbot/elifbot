#!/usr/bin/env python3
"""
ws_bot.py — SÜREKLİ TARAMA BOTU (WebSocket)

Fark: tur yok. Borsa her fiyat/hacim tikini iter, dedektör her tikte çalışır,
eşik aşıldığı ANDA pozisyon açılır.

    python ws_bot.py                     # süresiz
    python ws_bot.py --sure-dk 15        # 15 dakika

Çıktılar (panel bunları okur):
    logs/ws_olay.csv     — tespit edilen her ani hareket
    logs/ws_durum.json   — canlı sayaçlar
    live_trades.csv      — kapanan işlemler
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import aiohttp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from logger.trade_logger import TradeLogger
from portfolio.paper_futures import PaperPortfolio
from scanner.ws_scanner import (
    BinanceAkisi,
    BinanceRestAkisi,
    OKXAkisi,
    SpikeDetector,
    Sinyal,
    okx_enstrumanlari,
    okx_dakika_onbellegi,
)

log = logging.getLogger("ws_bot")

TABAN = os.path.dirname(os.path.abspath(__file__))
OLAY_CSV = os.path.join(TABAN, "logs", "ws_olay.csv")
DURUM_JSON = os.path.join(TABAN, "logs", "ws_durum.json")
TELEMETRI_CSV = os.path.join(TABAN, "logs", "ws_cikis_telemetri.csv")

# --- işlem parametreleri ---
MARJ = 25.0
KALDIRAC = config.DEFAULT_LEVERAGE
TP_PCT = 0.8          # kâr al        (varsayılan; CLI ile değişir)
SL_PCT = 0.5          # zarar durdur  (varsayılan; CLI ile değişir)
AZAMI_SURE_MS = 120_000   # 2 dk sonra kapat  (varsayılan; CLI ile değişir)
GIRIS_ARALIGI_MS = 3_000  # aynı sembolde tekrar giriş için bekleme
# --- korelasyon freni ---
# v12: kullanıcı kararıyla 10 sn / 3 açılış freni varsayılan olarak KAPALI.
# 0 = sınırsız; istenirse --acilis-freni N ile yeniden etkinleştirilebilir.
# Aynı varlık/çift borsa, toplam pozisyon ve marj kontrolleri bundan etkilenmez.
OLAY_PENCERE_MS = 10_000
OLAY_AZAMI_ACILIS = 0

# CASCADE EŞİĞİ: son 60 saniyede kaç sinyal geldiyse "tasfiye zinciri" sayılır.
# 7 gün kanıtı (104 sembol, nedensel test):
#   eşik 1 (filtresiz) 1593 sinyal %60,1 isabet +0,197%/işlem · 4/8 gün pozitif
#   eşik 2              881 sinyal %70,0 isabet +0,359%      · 5/8 gün
#   eşik 3              592 sinyal %80,7 isabet +0,563%      · 6/8 gün  <- SEÇİLEN
#   eşik 4              519 sinyal %86,3 isabet +0,670%      · 5/6 gün
# Eşik 3: eğitim +0,607 / test +0,459 · bootstrap 2000× %0 negatif
# Mekanizma: zincirleme tasfiye fiyatı aşırı iter, sonra geri döner.
# Tek sembolün haberi fade edilmez — piyasa geneli aşırılık fade edilir.
# 28.10: 3 -> 2.  Eşik 3, 2 sn'de %5'lik sinyallerle birlikte pratikte hiç
# sağlanmıyordu. Aşama 1 gevşetildiği (%5 -> %0,5) için cascade 2 dengeli.
CASCADE_ESIK = 0
# 28.10: Aşama 1 penceresi 2 sn -> 60 sn, rvol 1 -> 5 yapıldı. Artık sinyalin
# kendisi "1 dakikalık hacim patlamalı gerçek hareket"; cascade sayacına gerek
# kalmadı (7 gün: cascade 0/2/3/4 aynı sonucu verdi, sinyaller zaten seyrek).

# PİYASA GENİŞLİĞİ EŞİĞİ (izlenen sembollerin oranı, 1 dakikada |ret|>=0,5%).
#
# ÖNEMLİ DÜZELTME (28.10): eski eşik 0,45 (= sembollerin %45'i) HİÇBİR ZAMAN
# sağlanmıyordu. 289 sembol × 8.421 dakikalık gerçek ölçüm:
#     ortalama %1,75 · medyan %1,73 · p90 %3,11 · p99 %6,23 · MAX %9,69
# Yani %45 fiziksel olarak imkânsız → bot 05:41-05:50 arası 0 sinyal üretti.
# Doğru eşik dağılımın üst çeyreği: %4.
#
# 7 gün, 3dk |ret|>=1%, TP1,25/SL2,0/240dk, ücret %0,10 dahil:
#     eşik 2,0 → 16.329 sinyal  -0,035%   (kenar yok)
#     eşik 3,0 →  6.983 sinyal  +0,081%
#     eşik 4,0 →  3.468 sinyal  +0,233%  %71,1 isabet · test +0,069  <-- SEÇİLEN
#     eşik 5,0 →  2.209 sinyal  +0,441%  %68,4 isabet · test +0,039
#     eşik 6,0 →  1.540 sinyal  +0,560%  ama sinyaller 2 güne sıkışıyor
# 4,0 seçildi: günde ~590 sinyal (15 dk'da ~6), dağılım düzenli, test pozitif.
# Üst eşikler daha yüksek kâr veriyor ama işlem sayısı çöküyor ve tek güne bağlı.
GENISLIK_ESIK = 0.04

# İZOLE MARJ MODU
# Kullanıcı isteği: sabit stop yok, marj bitene kadar pozisyon açık kalsın.
# 10x kaldıraçta marj %10 ters harekette biter; 20x'te %5.
# ÖLÇÜM UYARISI (7 gün, 524 sinyal, ücret dahil):
#   TP2/SL3/5dk   → +0,672%/işlem · en kötü işlem -3,1%
#   TP2/SL3/240dk → +0,853%/işlem · en kötü işlem -3,1%   <-- VARSAYILAN
#   İZOLE 10x     → +0,564%/işlem · en kötü işlem -10,1%  <-- bu mod
# Yani izole mod DAHA AZ kazandırıyor ve 3 kat daha riskli. Yine de
# kullanıcı isteğiyle --izole ile açılabilir.
CASCADE_PENCERE_MS = 60_000


class Bot:
    def __init__(self, detektor: SpikeDetector, sure_dk: float = 0,
                 binance_mod: str = "rest", sadece_kayit: bool = False,
                 strateji: str = "fade", tp: float = 0.8,
                 sl: float = 1.2, tut_dk: float = 10.0,
                 giris_modu: str = "market", limit_payi: float = 0.05,
                 limit_bekle_sn: float = 30.0,
                 cascade_esik: int = CASCADE_ESIK,
                 min_genislik: float = GENISLIK_ESIK,
                 izole: bool = False,
                 acilis_freni: int = OLAY_AZAMI_ACILIS) -> None:
        self.detektor = detektor
        self.sadece_kayit = sadece_kayit
        self.strateji = strateji
        self.tp_pct = tp
        self.sl_pct = sl
        self.azami_sure_ms = int(tut_dk * 60_000)
        self.yon_filtre = "hepsi"
        self.cascade_esik = cascade_esik
        self.min_genislik = min_genislik
        self.izole = izole
        if int(acilis_freni) < 0:
            raise ValueError("acilis_freni negatif olamaz")
        self.acilis_freni = int(acilis_freni)
        self.sinyal_gecmisi: list[int] = []   # cascade sayımı için sinyal zamanları
        self.son_cascade = 0
        self.giris_modu = giris_modu
        self.limit_payi = limit_payi
        self.limit_bekle_sn = limit_bekle_sn
        self.bekleyen: dict[tuple[str, str], tuple] = {}   # (son ts, limit fiyat, yön, sinyal)
        self.limit_dolan = 0
        self.limit_iptal = 0
        self.portfoy = PaperPortfolio(
            starting_balance=config.STARTING_BALANCE_USDT,
            fee_rate=config.TAKER_FEE_RATE,
            # v13 kullanıcı kararı: yapay açılış/risk limitleri kapalı.
            # Gerçek bakiye/marj yeterliliği ve aynı-varlık koruması korunur.
            max_open_positions=None,
            max_same_direction=None,
            max_utilisation=None,
            balance_floor=0.0,
            daily_loss_limit_pct=None,
        )
        self.ticaret = TradeLogger(os.path.join(TABAN, "live_trades.csv"))
        self.baslangic = time.time()
        self.sure_dk = sure_dk
        self.durdu = False

        self.binance_mod = binance_mod
        self.sinyal_sayisi = 0
        self.acilan = 0
        self.kapanan = 0
        self.csv_kapanan = 0
        self.kayit_hatalari = 0
        self.mutabakat_eklenen = 0
        self.reddedilen = 0
        self.pnl = 0.0
        self.son_sinyaller: list[dict] = []
        self._acilis_gecmisi: list[int] = []    # korelasyon freni için
        self.olay_yazici = None
        # v14: yalnızca ölçüm. Pozisyon kararlarını etkilemeyen açık-pozisyon
        # telemetrisi; kapanışta ayrı CSV'ye yazılır.
        self.telemetri: dict[tuple[str, str], dict] = {}
        self.telemetri_hatalari = 0
        self.telemetri_kayitlari = 0

        self.okx_tik = 0
        self.binance_tik = 0
        self.binance_aktif = False
        self.binance_hata: str | None = None
        self.okx_baglanti = 0
        self.okx_sembol = 0
        self.okx_ms = 0.0
        self.binance_ms = 0.0
        self._onceki_tik = (0, 0)
        self._olay_dosyasi_hazirla()

    # ------------------------------------------------------------------
    def _olay_dosyasi_hazirla(self) -> None:
        os.makedirs(os.path.dirname(OLAY_CSV), exist_ok=True)
        yeni = not os.path.exists(OLAY_CSV)
        self.olay_yazici = open(OLAY_CSV, "a", newline="", encoding="utf-8")
        self.olay_csv = csv.writer(self.olay_yazici)
        if yeni:
            self.olay_csv.writerow(["ts_utc", "exchange", "symbol", "yon", "etiket",
                                    "fiyat", "ret_pct", "rvol", "hacim_usd", "pencere_ms",
                                    "gecikme_ms", "durum", "baglam_ret", "baglam_vratio",
                                    "baglam_vratio3"])

    # ------------------------------------------------------------------
    async def sinyal(self, s: Sinyal) -> None:
        self.sinyal_sayisi += 1

        # CASCADE SAYIMI: son 60 saniyede kaç sinyal geldi (bu dahil).
        # Reddedilen sinyaller de sayılır — zinciri onlar da doğrular.
        simdi_ms = s.ts_ms
        self.sinyal_gecmisi = [t for t in self.sinyal_gecmisi
                               if simdi_ms - t <= CASCADE_PENCERE_MS]
        self.sinyal_gecmisi.append(simdi_ms)
        self.son_cascade = len(self.sinyal_gecmisi)
        ts_utc = datetime.fromtimestamp(s.ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        gecikme = int(time.time() * 1000) - s.ts_ms

        # strateji: momentum = ani hareketin yönünde, fade = tersine
        if self.strateji == "fade":
            s = Sinyal(ts_ms=s.ts_ms, exchange=s.exchange, symbol=s.symbol,
                       yon="SHORT" if s.yon == "LONG" else "LONG",
                       etiket=s.etiket, fiyat=s.fiyat, ret_pct=s.ret_pct,
                       rvol=s.rvol, hacim_usd=s.hacim_usd, gecen_ms=s.gecen_ms,
                       baglam_ret=s.baglam_ret, baglam_vratio=s.baglam_vratio,
                       baglam_vratio3=s.baglam_vratio3)
        durum = self._pozisyon_ac(s)

        self.olay_csv.writerow([ts_utc, s.exchange, s.symbol, s.yon, s.etiket,
                                s.fiyat, s.ret_pct, s.rvol, s.hacim_usd, s.gecen_ms,
                                gecikme, durum, s.baglam_ret, s.baglam_vratio,
                                s.baglam_vratio3])
        self.olay_yazici.flush()

        self.son_sinyaller.append({
            "ts": ts_utc[11:], "exchange": s.exchange, "symbol": s.symbol,
            "yon": s.yon, "etiket": s.etiket, "fiyat": s.fiyat,
            "ret": s.ret_pct, "rvol": s.rvol, "gecikme_ms": gecikme,
            "baglam_ret": s.baglam_ret, "vratio3": s.baglam_vratio3,
        })
        self.son_sinyaller = self.son_sinyaller[-40:]

    def _limit_fiyati(self, fiyat: float, yon: str) -> float:
        """Fade yönünde, cari fiyatın `limit_payi` kadar ÖNÜNDEKİ fiyat."""
        if yon == "LONG":
            return fiyat * (1 - self.limit_payi / 100)
        return fiyat * (1 + self.limit_payi / 100)

    def _pozisyon_ac(self, s: Sinyal, limit_doldu: bool = False) -> str:
        """Pozisyon açar; her durumda insan-okur bir sebep döndürür."""
        if self.sadece_kayit:
            return "kayit_modu"

        if self.yon_filtre != "hepsi":
            istenen = "SHORT" if self.yon_filtre == "short" else "LONG"
            if s.yon != istenen:
                self.reddedilen += 1
                return "engel:yon_filtresi"

        if self.cascade_esik > 1 and len(self.sinyal_gecmisi) < self.cascade_esik:
            self.reddedilen += 1
            return f"engel:cascade_esigi ({len(self.sinyal_gecmisi)}<{self.cascade_esik})"

        anahtar = (s.exchange, s.symbol)

        # 28.10 DÜZELTME — ÇİFT BORSA TEKRARI:
        # Aynı hareket hem OKX hem Binance'te sinyal üretiyor. v7 koşusunda
        # ATH-USDT-SWAP (OKX) ve ATHUSDT (Binance) aynı anda açıldı: tek olay,
        # iki kat risk. Portföy anahtarı (borsa, sembol) olduğu için eski
        # kontrol bunu yakalamıyordu. Artık base sembol karşılaştırılıyor.
        base = self._base_sembol(s.symbol)
        for (b_exc, b_sym) in list(self.portfoy.positions.keys()) + list(self.bekleyen.keys()):
            if self._base_sembol(b_sym) == base:
                self.reddedilen += 1
                return f"engel:cift_borsa ({b_exc}:{b_sym})"

        if anahtar in self.portfoy.positions:
            self.reddedilen += 1
            return "engel:ayni_sembol_acik"
        if anahtar in self.bekleyen:
            self.reddedilen += 1
            return "engel:ayni_sembol_bekliyor"

        # ---- MAKER (limit) GİRİŞ ----
        # Fade yönünde, cari fiyatın `limit_payi` kadar ÖNÜNE emir konur.
        # Fiyat oraya değerse dolar: komisyon %0,05 yerine %0,02 (işlem başı
        # ~0,15 USDT tasarruf) VE giriş %0,05 daha iyi olur. Değmezse emir
        # iptal, işlem hiç açılmaz. Bedeli: sinyallerin bir kısmı kaçar.
        if self.giris_modu == "limit" and not limit_doldu:
            limit_fiyat = self._limit_fiyati(s.fiyat, s.yon)
            self.bekleyen[anahtar] = (s.ts_ms + int(self.limit_bekle_sn * 1000),
                                      limit_fiyat, s.yon, s)
            return "bekliyor:limit"
        # limit_doldu=True iken s.fiyat zaten bekleyen emrin limit fiyatıdır.
        # Burada _limit_fiyati() tekrar çağrılmaz; aksi hâlde limit payı
        # girişe İKİNCİ kez uygulanır ve paper sonuçları yapay olarak iyileşir.

        if (self.portfoy.max_open_positions is not None
                and self.portfoy.open_count() >= self.portfoy.max_open_positions):
            self.reddedilen += 1
            return "engel:pozisyon_limiti"
        if self.portfoy.equity - self.portfoy.used_margin < MARJ:
            self.reddedilen += 1
            return "engel:marj_yetersiz"

        # Korelasyon freni v12'de varsayılan kapalıdır (0 = sınırsız).
        # Geçmiş, isteğe bağlı fren yeniden açılırsa kullanılmak üzere tutulur.
        simdi_ms = int(time.time() * 1000)
        self._acilis_gecmisi = [t for t in self._acilis_gecmisi
                                if simdi_ms - t < OLAY_PENCERE_MS]
        if self.acilis_freni > 0 and len(self._acilis_gecmisi) >= self.acilis_freni:
            self.reddedilen += 1
            return "engel:korelasyon_freni"

        if self.izole:
            # İZOLE MARJ: stop YOK. Pozisyon ancak marj bittiğinde kapanır.
            # Marjın bitmesi = fiyatın 100/kaldıraç kadar ters gitmesi.
            marj_bitis = 100.0 / KALDIRAC          # 10x → %10
            stop = (s.fiyat * (1 - marj_bitis / 100) if s.yon == "LONG"
                    else s.fiyat * (1 + marj_bitis / 100))
        else:
            stop = (s.fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                    else s.fiyat * (1 + self.sl_pct / 100))
        tp = (s.fiyat * (1 + self.tp_pct / 100) if s.yon == "LONG"
              else s.fiyat * (1 - self.tp_pct / 100))

        giris_ucreti = config.MAKER_FEE_RATE if limit_doldu else config.TAKER_FEE_RATE
        sonuc = self.portfoy.open_position(
            s.exchange, s.symbol, s.yon, s.fiyat, MARJ,
            leverage=KALDIRAC, now_ms=s.ts_ms, poll_interval_ms=2000,
            entry_fee_rate=giris_ucreti,
            stop_price=stop, take_profit_price=tp,
        )
        if sonuc.ok:
            self.acilan += 1
            self._acilis_gecmisi.append(simdi_ms)
            self._telemetri_baslat(s, anahtar)
            log.info("AÇ %-5s %-22s @ %-12.6f rvol=%.1f ret=%+.2f%%",
                     s.yon, s.symbol, s.fiyat, s.rvol, s.ret_pct)
            return "acildi"
        self.reddedilen += 1
        return f"engel:{sonuc.reason}"

    @staticmethod
    def _base_sembol(symbol: str) -> str:
        """okx:BTC-USDT-SWAP ve binance:BTCUSDT -> ikisi de BTC."""
        t = symbol.upper()
        for ek in ("-USDT-SWAP", "-USDT", "USDT"):
            if t.endswith(ek):
                t = t[: -len(ek)]
                break
        if t.startswith("1000") and len(t) > 5:   # 1000PEPE ~ PEPE
            t = t[4:]
        return t

    # ------------------------------------------------------------------
    def _telemetri_baslat(self, s: Sinyal, anahtar: tuple[str, str]) -> None:
        """Açılış anını kaydet; hiçbir işlem/risk kararını değiştirmez."""
        pos = self.portfoy.positions.get(anahtar)
        if pos is None:
            return
        tahmini_cikis_ucreti = pos.qty_base * pos.entry_price * config.TAKER_FEE_RATE
        net_0 = -pos.entry_fee - tahmini_cikis_ucreti
        self.telemetri[anahtar] = {
            "exchange": s.exchange, "symbol": s.symbol, "side": s.yon,
            "opened_at": pos.opened_at, "entry_price": pos.entry_price,
            "qty_base": pos.qty_base, "entry_fee": pos.entry_fee,
            "signal_ret_pct": s.ret_pct, "signal_rvol": s.rvol,
            "signal_volume_usd": s.hacim_usd,
            "mfe_pct": 0.0, "mae_pct": 0.0,
            "time_to_mfe_s": 0.0, "time_to_mae_s": 0.0,
            "max_net_est": net_0, "min_net_est": net_0,
            "ret_10s_pct": None, "ret_30s_pct": None, "ret_60s_pct": None,
            "pnl_10s_net_est": None, "pnl_30s_net_est": None,
            "pnl_60s_net_est": None, "olcum_10s_sn": None,
            "olcum_30s_sn": None, "olcum_60s_sn": None,
            "last_price": pos.entry_price, "last_mark_ts": pos.opened_at,
            "tick_count": 0,
        }

    def _telemetri_guncelle(self, exchange: str, symbol: str,
                            fiyat: float, simdi: int) -> None:
        """MFE/MAE, tahmini net zirve/dip ve 10/30/60 sn ölçümlerini işler."""
        anahtar = (exchange, symbol)
        t = self.telemetri.get(anahtar)
        pos = self.portfoy.positions.get(anahtar)
        if t is None or pos is None or not (fiyat > 0):
            return
        if t["last_mark_ts"] == simdi and t["last_price"] == fiyat:
            return
        yon = 1.0 if pos.side == "LONG" else -1.0
        ret = (fiyat / pos.entry_price - 1.0) * 100.0 * yon
        gross = pos.unrealised_pnl(fiyat)
        tahmini_cikis_ucreti = abs(pos.qty_base * fiyat) * config.TAKER_FEE_RATE
        net_est = gross - pos.entry_fee - tahmini_cikis_ucreti
        gecen = max(0.0, (simdi - pos.opened_at) / 1000.0)
        t["tick_count"] += 1
        if ret > t["mfe_pct"]:
            t["mfe_pct"] = ret
            t["time_to_mfe_s"] = gecen
        if -ret > t["mae_pct"]:
            t["mae_pct"] = -ret
            t["time_to_mae_s"] = gecen
        t["max_net_est"] = max(t["max_net_est"], net_est)
        t["min_net_est"] = min(t["min_net_est"], net_est)
        for sn in (10, 30, 60):
            if t[f"ret_{sn}s_pct"] is None and gecen >= sn:
                t[f"ret_{sn}s_pct"] = ret
                t[f"pnl_{sn}s_net_est"] = net_est
                t[f"olcum_{sn}s_sn"] = gecen
        t["last_price"] = fiyat
        t["last_mark_ts"] = simdi

    def _fiyat_guncelle(self, exchange: str, symbol: str, fiyat: float,
                        ts_ms: int | None = None) -> None:
        """Portföy mark'ı, salt-izleme telemetrisi ve bekleyen limitler."""
        simdi = ts_ms if ts_ms else int(time.time() * 1000)
        self.portfoy.mark_price(exchange, symbol, fiyat, simdi)
        self._telemetri_guncelle(exchange, symbol, fiyat, simdi)
        self._bekleyenleri_isle(exchange, symbol, fiyat)

    def _telemetri_yaz(self, t: dict, rec) -> None:
        """Kapanan pozisyonun telemetrisini ana işlem CSV'sinden ayrı yaz."""
        yon = 1.0 if rec.side == "LONG" else -1.0
        kapanis_ret = (rec.exit_price / rec.entry_price - 1.0) * 100.0 * yon
        alanlar = [
            "exchange", "symbol", "side", "opened_at", "closed_at", "reason",
            "entry_price", "exit_price", "signal_ret_pct", "signal_rvol",
            "signal_volume_usd", "close_ret_pct", "mfe_pct", "mae_pct",
            "time_to_mfe_s", "time_to_mae_s", "max_net_est", "min_net_est",
            "realized_pnl", "peak_was_profitable", "giveback_usd", "giveback_pct",
            "ret_10s_pct", "ret_30s_pct", "ret_60s_pct", "pnl_10s_net_est",
            "pnl_30s_net_est", "pnl_60s_net_est", "olcum_10s_sn",
            "olcum_30s_sn", "olcum_60s_sn", "tick_count",
        ]
        row = {k: t.get(k) for k in alanlar}
        row.update({
            "closed_at": rec.closed_at, "reason": rec.reason,
            "exit_price": rec.exit_price, "close_ret_pct": kapanis_ret,
            "realized_pnl": rec.realized_pnl,
            "peak_was_profitable": int(t["max_net_est"] > 0),
            "giveback_usd": t["max_net_est"] - rec.realized_pnl,
            "giveback_pct": t["mfe_pct"] - kapanis_ret,
        })
        for k, v in list(row.items()):
            if isinstance(v, float):
                row[k] = round(v, 10)
        os.makedirs(os.path.dirname(TELEMETRI_CSV), exist_ok=True)
        yeni = not os.path.exists(TELEMETRI_CSV) or os.path.getsize(TELEMETRI_CSV) == 0
        with open(TELEMETRI_CSV, "a", newline="", encoding="utf-8") as fh:
            yaz = csv.DictWriter(fh, fieldnames=alanlar)
            if yeni:
                yaz.writeheader()
            yaz.writerow(row)
            fh.flush()
            os.fsync(fh.fileno())
        self.telemetri_kayitlari += 1

    # ------------------------------------------------------------------
    def _bekleyenleri_isle(self, exchange: str, symbol: str, fiyat: float) -> None:
        """Bekleyen limit emirlerini cari fiyatla karşılaştırır."""
        if not self.bekleyen:
            return
        simdi = int(time.time() * 1000)
        anahtar = (exchange, symbol)
        kayit = self.bekleyen.get(anahtar)
        if not kayit:
            return
        son_ts, limit_fiyat, yon, s0 = kayit[0], kayit[1], kayit[2], kayit[3]

        if simdi > son_ts:
            self.bekleyen.pop(anahtar, None)
            self.limit_iptal += 1
            return

        doldu = ((yon == "LONG" and fiyat <= limit_fiyat)
                 or (yon == "SHORT" and fiyat >= limit_fiyat))
        if not doldu:
            return

        self.bekleyen.pop(anahtar, None)
        s = Sinyal(ts_ms=s0.ts_ms, exchange=s0.exchange, symbol=s0.symbol,
                   yon=s0.yon, etiket=s0.etiket, fiyat=limit_fiyat,
                   ret_pct=s0.ret_pct, rvol=s0.rvol, hacim_usd=s0.hacim_usd,
                   gecen_ms=s0.gecen_ms, baglam_ret=s0.baglam_ret,
                   baglam_vratio=s0.baglam_vratio,
                   baglam_vratio3=s0.baglam_vratio3)
        durum = self._pozisyon_ac(s, limit_doldu=True)
        if durum == "acildi":
            self.limit_dolan += 1

    def _kapat_ve_kaydet(self, exchange: str, symbol: str, fiyat: float,
                         simdi: int, sebep: str):
        """Kapanışı, sayaçları ve CSV'yi tek yoldan işler.

        CSV hatası kapanmış pozisyonu geri açmaz; hata görünür sayılır ve
        oturum sonundaki ``log_missing`` mutabakatı eksik satırı tamamlar.
        """
        self._telemetri_guncelle(exchange, symbol, fiyat, simdi)
        rec = self.portfoy.close_position(
            exchange, symbol, fiyat, now_ms=simdi, reason=sebep,
        )
        if rec is None:
            return None
        self.kapanan += 1
        self.pnl += rec.realized_pnl
        try:
            self.csv_kapanan += self.ticaret.log_trades([rec])
        except Exception:  # noqa: BLE001
            self.kayit_hatalari += 1
            log.exception("kapanan işlem CSV'ye yazılamadı: %s:%s", exchange, symbol)
        telemetri = self.telemetri.pop((exchange, symbol), None)
        if telemetri is not None:
            try:
                self._telemetri_yaz(telemetri, rec)
            except Exception:  # noqa: BLE001
                self.telemetri_hatalari += 1
                log.exception("çıkış telemetrisi yazılamadı: %s:%s", exchange, symbol)
        return rec

    def _kayit_mutabakati(self) -> None:
        """Oturum sonunda portföydeki bütün kapanışların CSV'de olduğunu doğrula."""
        try:
            eklenen = self.ticaret.log_missing(self.portfoy.closed_trades)
            self.mutabakat_eklenen += eklenen
            self.csv_kapanan = self.kapanan
            if eklenen:
                log.warning("CSV mutabakatı: %d eksik kapanış eklendi", eklenen)
        except Exception:  # noqa: BLE001
            self.kayit_hatalari += 1
            log.exception("kapanan işlem CSV mutabakatı başarısız")

    def _cikisleri_kontrol_et(self, simdi: int) -> int:
        """Tek çıkış turu; kapatılan pozisyon sayısını döndürür."""
        kapanan_once = self.kapanan
        for (ex, sym), pos in list(self.portfoy.positions.items()):
            fiyat = pos.last_price
            if not fiyat:
                continue
            yon = pos.side
            giris = pos.entry_price
            degisim = (fiyat - giris) / giris * 100
            if yon == "SHORT":
                degisim = -degisim

            sebep = None
            if pos.stop_price is not None:
                stop_vurdu = ((yon == "LONG" and fiyat <= pos.stop_price)
                              or (yon == "SHORT" and fiyat >= pos.stop_price))
                if stop_vurdu:
                    sebep = "stop_loss"
            if sebep is None and pos.take_profit_price is not None:
                tp_vurdu = ((yon == "LONG" and fiyat >= pos.take_profit_price)
                            or (yon == "SHORT" and fiyat <= pos.take_profit_price))
                if tp_vurdu:
                    sebep = "take_profit"
            if sebep is None and simdi - pos.opened_at > self.azami_sure_ms:
                sebep = "timeout"

            if sebep:
                rec = self._kapat_ve_kaydet(ex, sym, fiyat, simdi, sebep)
                if rec:
                    log.info("KAPA %-22s %-13s pnl=%+.4f (%.2f%%)",
                             sym, sebep, rec.realized_pnl, degisim)
        return self.kapanan - kapanan_once

    async def cikis_yonetimi(self) -> None:
        """Her 100 ms'de bir: pozisyonun kendi SL / TP'si ve zaman aşımı."""
        while not self.durdu:
            self._cikisleri_kontrol_et(int(time.time() * 1000))
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    def durum_yaz(self) -> None:
        d = {
            "simdi": datetime.now().strftime("%H:%M:%S"),
            "calisiyor": not self.durdu,
            "sure_sn": int(time.time() - self.baslangic),
            "sure_dk_hedef": self.sure_dk,
            "mod": "websocket",
            "strateji": self.strateji,
            "tp": self.tp_pct,
            "sl": self.sl_pct,
            "bakiye": round(self.portfoy.equity, 4),
            "baslangic_bakiye": config.STARTING_BALANCE_USDT,
            "acik_pozisyon": self.portfoy.open_count(),
            "acik_pozisyonlar": [
                {"sembol": f"{ex}:{sym}", "yon": p.side, "giris": p.entry_price,
                 "fiyat": p.last_price, "marj": p.margin,
                 "pnl": round(p.unrealised_pnl(p.last_price), 4) if p.last_price else 0}
                for (ex, sym), p in list(self.portfoy.positions.items())[:10]
            ],
            "kapanan_islem": self.kapanan,
            "csv_kapanan_islem": self.csv_kapanan,
            "kayit_mutabakati": self.csv_kapanan == self.kapanan,
            "kayit_hatalari": self.kayit_hatalari,
            "mutabakat_eklenen": self.mutabakat_eklenen,
            "telemetri_kayitlari": self.telemetri_kayitlari,
            "telemetri_hatalari": self.telemetri_hatalari,
            "toplam_pnl": round(self.pnl, 4),
            "sinyal": self.sinyal_sayisi,
            "acilan": self.acilan,
            "reddedilen": self.reddedilen,
            "limit_dolan": self.limit_dolan,
            "limit_iptal": self.limit_iptal,
            "bekleyen_limit": len(self.bekleyen),
            "cascade": self.son_cascade,
            "cascade_esik": self.cascade_esik,
            "acilis_freni_10sn": self.acilis_freni,
            "toplam_pozisyon_limiti": self.portfoy.max_open_positions,
            "ayni_yon_pozisyon_limiti": self.portfoy.max_same_direction,
            "marj_kullanim_limiti": self.portfoy.max_utilisation,
            "gunluk_zarar_giris_limiti": self.portfoy.daily_loss_limit_pct,
            "bakiye_rezerv_tabani": self.portfoy.balance_floor,
            "genislik": self.detektor.genislik,
            "genislik_oran": round(self.detektor.genislik_oran, 4),
            "min_genislik": self.min_genislik,
            "izole": self.izole,
            "okx": {"tik": self.okx_tik, "baglanti": self.okx_baglanti,
                    "sembol": self.okx_sembol, "msg_sn": self.okx_ms},
            "binance": {"tik": self.binance_tik, "aktif": self.binance_aktif,
                        "hata": self.binance_hata, "msg_sn": self.binance_ms,
                        "mod": self.binance_mod,
                        "sembol": len(getattr(getattr(self, "_bnc", None), "semboller", ()) or ())},
            "izlenen_sembol": len(self.detektor.durumlar),
            "hacim_hazir": sum(1 for d in self.detektor.durumlar.values() if d.hiz_uzun > 0),
            "son_gecikme_ms": self.son_sinyaller[-1].get("gecikme_ms") if self.son_sinyaller else None,
            "son_sinyaller": self.son_sinyaller[-20:],
        }
        gecici = DURUM_JSON + ".tmp"
        with open(gecici, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        os.replace(gecici, DURUM_JSON)

    # ------------------------------------------------------------------
    async def calistir(self) -> None:
        async with aiohttp.ClientSession() as oturum:
            semboller, spot_bazlar = await okx_enstrumanlari(oturum)
            self.okx_sembol = len(semboller)
            log.info("OKX USDT-SWAP enstrüman: %d | spot baz: %d", len(semboller), len(spot_bazlar))

            # Bağlam filtresi 33 tamamlanmış dakika ister. REST ön-dolgusu
            # olmadan bot açılıştan sonra ~33 dk HİÇ sinyal üretmez.
            if getattr(self.detektor, "baglam_aktif", False):
                log.info("dakika geçmişi REST'ten dolduruluyor (%d sembol)...", len(semboller))
                t_0 = time.time()
                dolu = await okx_dakika_onbellegi(oturum, self.detektor, semboller)
                log.info("dakika önbelleği: %d/%d sembol dolu (%.0f sn)",
                         dolu, len(semboller), time.time() - t_0)

            def fiyat_kontrol(exchange: str, symbol: str, fiyat: float,
                              ts_ms: int | None = None) -> None:
                """Canlı fiyat: portföy mark'ı + telemetri + limit dolumu."""
                self._fiyat_guncelle(exchange, symbol, fiyat, ts_ms)

            okx = OKXAkisi(self.detektor, semboller, self.sinyal, fiyat_kontrol)
            if self.binance_mod == "ws":
                bnc = BinanceAkisi(self.detektor, self.sinyal, fiyat_kontrol)
            else:
                # WebSocket bu ortamda engelli → REST akışı
                bnc = BinanceRestAkisi(self.detektor, self.sinyal, fiyat_kontrol)

            self._bnc = bnc
            gorevler = [
                asyncio.create_task(okx.calistir(oturum), name="okx"),
                asyncio.create_task(bnc.calistir(oturum), name="binance"),
                asyncio.create_task(self.cikis_yonetimi(), name="cikis"),
                asyncio.create_task(self._sayac_dongusu(okx, bnc), name="sayac"),
            ]

            baslangic = time.time()
            try:
                while not self.durdu:
                    await asyncio.sleep(1)
                    if self.sure_dk and (time.time() - baslangic) >= self.sure_dk * 60:
                        log.info("süre doldu (%.0f dk) — kapanıyor", self.sure_dk)
                        break
            finally:
                self.durdu = True
                for g in gorevler:
                    g.cancel()
                await asyncio.gather(*gorevler, return_exceptions=True)
                self._tumunu_kapat()
                self.durum_yaz()
                self.olay_yazici.close()

    async def _sayac_dongusu(self, okx: OKXAkisi, bnc: BinanceAkisi) -> None:
        while not self.durdu:
            # piyasa genişliğini saniyede bir yenile (812 sembolü gezmek ucuz)
            try:
                self.detektor.genislik_guncelle()
            except Exception:
                pass
            o, b = okx.mesaj_sayisi, bnc.mesaj_sayisi
            self.okx_ms = float(o - self._onceki_tik[0])
            self.binance_ms = float(b - self._onceki_tik[1])
            self._onceki_tik = (o, b)
            self.okx_tik = o
            self.okx_baglanti = okx.baglanti_sayisi
            self.binance_tik = b
            self.binance_aktif = bnc.aktif
            self.binance_hata = bnc.hata
            try:
                self.durum_yaz()
            except Exception as exc:                    # noqa: BLE001
                log.error("durum yazılamadı: %s", exc)
            await asyncio.sleep(1)

    def _tumunu_kapat(self) -> None:
        self.bekleyen.clear()
        simdi = int(time.time() * 1000)
        for (ex, sym), pos in list(self.portfoy.positions.items()):
            fiyat = pos.last_price or pos.entry_price
            self._kapat_ve_kaydet(ex, sym, fiyat, simdi, "session_end")
        self._kayit_mutabakati()


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sürekli WebSocket tarama botu")
    ap.add_argument("--sure-dk", type=float, default=0, help="0 = süresiz")
    ap.add_argument("--pencere-ms", type=int, default=60_000,
                    help="hareket penceresi (ms). 28.10: 2000 -> 60000. "
                         "2 sn'lik pencere mikro gürültüydü: 209 canlı sinyalin "
                         "1 dk isabeti %%41,2, ücret sonrası -0,104%%/işlem. "
                         "1 dk'lık pencere 7 günlük veriyle ölçüldü (+0,242%%/işlem)")
    ap.add_argument("--ret", type=float, default=0.5,
                    help="2 sn pencerede min |%%| hareket (bağlam filtresi asıl seçici)")
    ap.add_argument("--rvol", type=float, default=5.0,
                    help="min hacim çarpanı (kısa/uzun hacim hızı). 28.10: 1,0 -> 5,0. "
                         "7 gün: rvol>=5 kârı 5 katına çıkarıyor (esik1/gl4/TP1,25: "
                         "rvol yok +0,079%% test -0,018 | rvol3 +0,304%% test +0,067 | "
                         "rvol5 +0,419%% test +0,411)")
    ap.add_argument("--min-hacim", type=float, default=1_000,
                    help="son 10 sn'de min USD hacim")
    ap.add_argument("--min-hacim-24s", type=float, default=0,
                    help="24s USD likidite tabanı (0 = kapalı)")
    ap.add_argument("--strateji", choices=["momentum", "fade"], default="fade",
                    help="fade = ani hareketin TERSİNE (ölçümle seçildi) · momentum = aynı yönde")
    ap.add_argument("--tp", type=float, default=1.25,
                    help="kâr al %% (99 = kapalı; 7 gün: TP kazancın kuyruğunu kesiyor)")
    ap.add_argument("--sl", type=float, default=2.0, help="zarar durdur %%")
    ap.add_argument("--tut-dk", type=float, default=240.0,
                    help="azami tutma (dakika). 7 gün: 240 dk > 5 dk (+0,85 vs +0,67)")
    ap.add_argument("--sadece-kayit", action="store_true",
                    help="işlem açma, yalnızca sinyal kaydet (veri toplama)")
    ap.add_argument("--giris", choices=("market", "limit"), default="market",
                    help="market = anında piyasa emri · limit = maker (daha düşük ücret)")
    ap.add_argument("--limit-payi", type=float, default=0.05,
                    help="limit fiyatı cari fiyatın %% kaç önüne konur")
    ap.add_argument("--limit-bekle-sn", type=float, default=30.0,
                    help="limit emrin geçerlilik süresi (saniye)")
    ap.add_argument("--yon", choices=("hepsi", "long", "short"), default="hepsi",
                    help="işlem yönü filtresi")
    ap.add_argument("--baglam", action=argparse.BooleanOptionalAction, default=False,
                    help="1 dakikalık bağlam filtresi (geçmişte doğrulanmış)")
    ap.add_argument("--baglam-ret", type=float, default=1.2,
                    help="3 dk getiri ALT sınırı %%")
    ap.add_argument("--baglam-maks-ret", type=float, default=3.0,
                    help="3 dk getiri ÜST sınırı %% (0 = kapalı); >2%% gerçek momentum")
    ap.add_argument("--baglam-rvol", type=float, default=1.0,
                    help="cari dakika hacim oranı eşiği (0 = kapalı)")
    ap.add_argument("--baglam-rvol3", type=float, default=10.0,
                    help="3 dk ORTALAMA hacim oranı eşiği — geri testle birebir")
    ap.add_argument("--baglam-dk", type=int, default=3, help="bağlam getiri penceresi")
    ap.add_argument("--izole", action="store_true",
                    help="izole marj: sabit stop YOK, sadece marj bitince kapanır. "
                         "DİKKAT: ölçüldü, kâr düşüyor (+0,56 vs +0,85) ve risk 3 kat artıyor")
    ap.add_argument("--min-genislik", type=float, default=GENISLIK_ESIK,
                    help="piyasa genişliği eşiği (0-1 oranı; 0 = kapalı). "
                         "0.45 = sembollerin %%45'i aynı anda hareket ediyor olmalı")
    ap.add_argument("--cascade-esik", type=int, default=0,
                    help="son 60 sn'de bu kadar sinyal yoksa işlem açma (0/1 = kapalı)")
    ap.add_argument("--acilis-freni", type=int, default=OLAY_AZAMI_ACILIS,
                    help="10 sn içinde en fazla N yeni pozisyon; 0 = kapalı (v12 varsayılanı)")
    ap.add_argument("--binance", choices=["rest", "ws"], default="rest",
                    help="rest = www.binance.com/fapi (engel aşar) · ws = fstream")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    print("""
============================================================
 SÜREKLİ TARAMA — WEBSOCKET  ·  PAPER-ONLY
 Tüm borsa sembolleri abone · her tikte tespit · emir yok
============================================================
""")

    detektor = SpikeDetector(
        ret_pencere_ms=args.pencere_ms,
        ret_min_pct=args.ret,
        rvol_min=args.rvol,
        min_hacim_usd=args.min_hacim,
        min_hacim_24s_usd=args.min_hacim_24s,
        baglam_aktif=args.baglam,
        baglam_geri_dk=args.baglam_dk,
        baglam_min_ret=args.baglam_ret,
        baglam_maks_ret=args.baglam_maks_ret,
        baglam_min_vratio=args.baglam_rvol,
        baglam_min_vratio3=args.baglam_rvol3,
        min_genislik_oran=args.min_genislik,
    )
    bot = Bot(detektor, sure_dk=args.sure_dk, binance_mod=args.binance,
              sadece_kayit=args.sadece_kayit, strateji=args.strateji,
              tp=args.tp, sl=args.sl, tut_dk=args.tut_dk,
              giris_modu=args.giris, limit_payi=args.limit_payi,
              limit_bekle_sn=args.limit_bekle_sn,
              cascade_esik=args.cascade_esik,
              min_genislik=args.min_genislik,
              izole=args.izole,
              acilis_freni=args.acilis_freni)
    bot.yon_filtre = args.yon

    try:
        asyncio.run(bot.calistir())
    except KeyboardInterrupt:
        bot.durdu = True
        bot._tumunu_kapat()
        bot.durum_yaz()

    print(f"\n  Sinyal   : {bot.sinyal_sayisi}")
    print(f"  Açılan   : {bot.acilan}")
    print(f"  Kapanan  : {bot.kapanan}")
    print(f"  PnL      : {bot.pnl:+.4f} USDT")
    print(f"  Bakiye   : {bot.portfoy.equity:.2f} USDT")
    print("\n  Funding hariç · paper simülasyon · yatırım tavsiyesi değil")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
