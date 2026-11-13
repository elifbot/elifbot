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
from dataclasses import asdict

import aiohttp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from logger.trade_logger import TradeLogger
from data.extended.funding_events import FundingWatcher
from portfolio.exit_shadow import ShadowPosition, default_variants
from portfolio.flow_runner import FlowShadowEngine, tamamlanmis_mumlar
from portfolio.paper_futures import PaperPortfolio
from portfolio.orderbook_shadow import snapshot as orderbook_snapshot
from scanner.binance_flow import BinanceAggTradeFlow, binance_sembolleri
from scanner.money_flow import AkisDefteri, akis_csv_alanlari
from scanner.regime_shadow import evaluate as regime_evaluate, fetch_candles as regime_fetch
from scanner.aggtrade_shadow import AggTradeShadow
from scanner.aggtrade_input import BinanceAggTradeInput
from scanner.signal_intel import (
    BINANCE_PUBLIC_BASE, MAX_SIGNAL_DECISION_AGE_MS, SignalEnricher,
)
from scanner.ind_aktif import giris_karari, kapsam
from scanner.universe import is_stock_like, split_okx_binance_overlap
from reports.process_health import process_identity
from reports.process_diagnostics import Diagnostics, ProcessSignal
from reports.file_safety import file_lock, instance_lock, atomic_json, InstanceBusy
from scanner.ws_scanner import (
    BinanceAkisi,
    BinanceRestAkisi,
    OKXAkisi,
    SpikeDetector,
    Sinyal,
    binance_indikator_mum_eksiklerini_doldur,
    okx_enstrumanlari,
    okx_kontrat_carpanlari,
    okx_dakika_onbellegi,
)

log = logging.getLogger("ws_bot")

TABAN = os.path.dirname(os.path.abspath(__file__))
OLAY_CSV = os.path.join(TABAN, "logs", "ws_olay.csv")
DURUM_JSON = os.path.join(TABAN, "logs", "ws_durum.json")
TELEMETRI_CSV = os.path.join(TABAN, "logs", "ws_cikis_telemetri.csv")
GOLGE_CSV = os.path.join(TABAN, "logs", "ws_golge_cikis.csv")
AKIS_SINYAL_CSV = os.path.join(TABAN, "logs", "ws_akis_sinyal.csv")
AKIS_KAPANIS_CSV = os.path.join(TABAN, "logs", "ws_akis_kapanis.csv")
AKIS_GOLGE_OLAY_CSV = os.path.join(TABAN, "logs", "ws_akis_golge_olay.csv")
AKIS_GOLGE_KAPANIS_CSV = os.path.join(TABAN, "logs", "ws_akis_golge_kapanis.csv")

# --- işlem parametreleri ---
MARJ = 25.0
KALDIRAC = config.DEFAULT_LEVERAGE
TP_PCT = 0.8          # kâr al        (varsayılan; CLI ile değişir)
SL_PCT = 0.5          # zarar durdur  (varsayılan; CLI ile değişir)
AZAMI_SURE_MS = 300_000   # 5 dk sonra kapat  (varsayılan; CLI ile değişir)
GIRIS_ARALIGI_MS = 3_000  # aynı sembolde tekrar giriş için bekleme
# --- korelasyon freni ---
# v12: kullanıcı kararıyla 10 sn / 3 açılış freni varsayılan olarak KAPALI.
# 0 = sınırsız; istenirse --acilis-freni N ile yeniden etkinleştirilebilir.
# Aynı varlık/çift borsa, toplam pozisyon ve marj kontrolleri bundan etkilenmez.
OLAY_PENCERE_MS = 10_000
OLAY_AZAMI_ACILIS = 0

# CASCADE EŞİĞİ: son 60 saniyedeki sinyal sayısı.
# Kısa paper denemesi için 1: mevcut sinyal de sayaca eklendiğinden,
# cascade_esik <= 1 iken bu kapı devre dışıdır; tek aday başka kapılardan
# geçerse değerlendirilebilir. 2+ değerleri son 60 sn'de birden çok sinyal ister.
CASCADE_ESIK = 1

# PİYASA GENİŞLİĞİ EŞİĞİ: 0 kapıyı kapatır (ölçüm/sayaç yine tutulabilir).
# Bu kısa paper denemesi için kullanıcı isteğiyle breadth filtresi devre dışı.
# Bu ayar tek başına sinyal ya da işlem üretileceğini garanti etmez.
GENISLIK_ESIK = 0.0

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


def _genislik_aday_ozet(degerler) -> dict:
    """
    v21 gözlem: son kapıya (genişlik) gelen adayların o ANDAKİ genişlik oranları.

    "Eşiği %4'te mi bırakalım, %2'ye mi indirelim" kararı için gereken veri:
    adayların genişlik dağılımı. Örn. medyan %0,9 ise %2 eşiği de botu kapatır;
    medyan %1,8 ise %2 anlamlı bir kapı olur.
    """
    if not degerler:
        return {"n": 0}
    s = sorted(degerler)
    n = len(s)
    return {
        "n": n,
        "min": round(s[0], 4),
        "medyan": round(s[n // 2], 4),
        "p90": round(s[min(n - 1, int(n * 0.9))], 4),
        "maks": round(s[-1], 4),
    }


class Bot:
    def __init__(self, detektor: SpikeDetector, sure_dk: float = 0,
                 binance_mod: str = "rest", sadece_kayit: bool = False,
                 strateji: str = "fade", tp: float = 0.8,
                 sl: float = 0.5, tut_dk: float = 5.0,
                 giris_modu: str = "limit", limit_payi: float = 0.05,
                 limit_bekle_sn: float = 30.0,
                 cascade_esik: int = CASCADE_ESIK,
                 min_genislik: float = GENISLIK_ESIK,
                 izole: bool = False,
                 acilis_freni: int = OLAY_AZAMI_ACILIS,
                 golge_cikis: bool = False,
                 akis_olcum: bool = False,
                 akis_golge: bool = False,
                 cikis_tamamlama_dk: float = 0.0,
                 risk_limitleri: bool = True,
                 kayma_pct: float = 0.0,
                 durum_devam: bool = False,
                 erken_hata_sn: float = 90.0, erken_hata_pct: float = 0.8,
                 be_tetik_pct: float = 0.6, be_kilit_pct: float = 0.30,
                 trail_tetik_pct: float = 1.0, trail_mesafe_pct: float = 0.5,
                 acilis_kap_10dk: int = 20, ayni_yon_kap: int = 20,
                 teyit_aktif: bool = False, teyit_pct: float = 0.15,
                 teyit_bekle_sn: float = 30.0, stop_asma_pct: float = 0.10,
                 erken_hata_ilk_sn: float = 30.0, erken_hata_ilk_pct: float = 0.5,
                 binance_onbellek: bool = True, funding_aktif: bool = True,
                 defter_golge: bool = True,
                 indikator_golge: bool = False,
                 binance_gercek_hacim_golge: bool = False,
                 binance_hacim_kaynagi: str = 'proxy',
                 sembol_limit: int = 0,
                 indikator_hazirlik_oran: float = 90.0,
                 indikator_hazirlik_zamanasimi_dk: float = 75.0,
                 sinyal_zenginlestirme: bool = False,
                 kar_kilidi_aktif: bool = False) -> None:
        if isinstance(sembol_limit, bool) or not isinstance(sembol_limit, int) or sembol_limit < 0:
            raise ValueError('sembol_limit negatif olmayan tam sayı olmalı')
        if not 0.0 <= float(indikator_hazirlik_oran) < 100.0:
            raise ValueError('indikator_hazirlik_oran 0 ile 100 arasında olmalı')
        if not float(indikator_hazirlik_zamanasimi_dk) > 0.0:
            raise ValueError('indikator_hazirlik_zamanasimi_dk pozitif olmalı')
        self.sembol_limit = sembol_limit
        self.indikator_hazirlik_oran = float(indikator_hazirlik_oran)
        self.indikator_hazirlik_zamanasimi_dk = float(indikator_hazirlik_zamanasimi_dk)
        self.indikator_evrenleri: dict[str, set[str]] = {}
        self.indikator_hazirlik_baslangic_utc = None
        self.indikator_hazirlik_bitis_utc = None
        self.indikator_hazirlik_hata = None
        self.indikator_kapsam_son = None
        self.indikator_aktif = bool(getattr(detektor, 'ind_aktif', False))
        self.indikator_hazir = not self.indikator_aktif
        self.detektor = detektor
        self.proses_baslama_utc = datetime.now(timezone.utc).isoformat()
        self.proses_baslama_ts = time.time()
        self.proses_identity = process_identity(os.getpid())
        self.kapanis_nedeni = None
        # Shadow ölçümü ana kararı değiştirmez. Zengin sinyal yolu ise ayrı ve
        # açıkça sayaçlanan paper giriş filtresidir; live/testnet yolu eklemez.
        self.indikator_golge = bool(indikator_golge)
        self.signal_enrichment_active = bool(sinyal_zenginlestirme)
        self.signal_enricher = SignalEnricher() if self.signal_enrichment_active else None
        self.signal_filter_counts = {
            "candidate": 0, "fade_applied": 0, "mtf_pass": 0, "mtf_block": 0,
            "mtf_unavailable": 0, "funding_pass": 0, "funding_block": 0,
            "funding_unavailable": 0, "oi_available": 0, "oi_unavailable": 0,
            "funding_or_oi_unavailable": 0, "oi_conflict": 0, "oi_delta_known": 0,
            "orderflow_pass": 0, "orderflow_block": 0, "orderflow_unavailable": 0,
            "stale_at_decision": 0, "entry_eligible": 0,
            "entry_blocked": 0,
        }
        self.signal_intel_events = 0
        self.signal_intel_csv = os.path.join(TABAN, "logs", "ws_sinyal_zenginlestirme.csv")
        self._signal_key_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self.kar_kilidi_aktif = bool(kar_kilidi_aktif)
        self.kar_kilidi_olaylari = 0
        self.kar_kilidi_kademe1 = 0
        self.kar_kilidi_kademe2 = 0
        self.mfe_kalkan_aktivasyon = 0
        self.profit_protection_csv = os.path.join(TABAN, "logs", "ws_kar_kilidi.csv")
        self.binance_gercek_hacim_golge = bool(binance_gercek_hacim_golge)
        if binance_hacim_kaynagi not in ('proxy','aggtrade'):
            raise ValueError('gecersiz Binance hacim kaynagi')
        if binance_hacim_kaynagi == 'aggtrade' and binance_mod != 'rest':
            raise ValueError('aggtrade hacim icin Binance REST fiyat modu gerekli')
        self.binance_hacim_kaynagi = binance_hacim_kaynagi
        self._real_volume = BinanceAggTradeInput(detektor,self._sinyal_dispatch) if binance_hacim_kaynagi == 'aggtrade' else None
        self._hacim_shadow = AggTradeShadow() if self.binance_gercek_hacim_golge else None
        self._regime_limit = asyncio.Semaphore(3)
        self._regime_rate_lock = asyncio.Lock()
        self._regime_next_request = 0.0
        self._regime_tasks: set[asyncio.Task] = set()
        self.regime_olcum = 0
        self.regime_hata = 0
        self.regime_yazma_hata = 0
        self.sadece_kayit = sadece_kayit
        self.strateji = strateji
        self.tp_pct = tp
        self.sl_pct = sl
        self.azami_sure_ms = int(tut_dk * 60_000)
        self.yon_filtre = "hepsi"
        self.cascade_esik = cascade_esik
        self.min_genislik = min_genislik
        # v21: Binance dakika geçmişi REST ön-dolgusu (bağlam ısınması 35 dk -> ~0)
        self.binance_onbellek = bool(binance_onbellek)
        self.funding_aktif = bool(funding_aktif)
        self.funding_izleyici = None
        self.defter_golge = bool(defter_golge)
        self.defter_olcum = 0
        self.defter_hata = 0
        self._defter_kontratlar = {}
        self._defter_limit = asyncio.Semaphore(4)
        self.izole = izole
        self.golge_cikis = bool(golge_cikis)
        self.akis_golge_aktif = bool(akis_golge)
        # Order-flow teyidi aktifken de gerçek public taker akışı açılır; bu
        # akış yalnızca (venue,symbol) anahtarında tutulur, borsalar karışmaz.
        self.akis_olcum = bool(akis_olcum or akis_golge or self.signal_enrichment_active)
        self.akis = AkisDefteri() if self.akis_olcum else None
        self.akis_giris: dict[tuple[str, str], dict] = {}
        self.akis_sinyal_kayitlari = 0
        self.akis_kapanis_kayitlari = 0
        self.akis_kayit_hatalari = 0
        self.akis_golge_hatalari = 0
        self.akis_golge_mum_hatalari = 0
        self._akis_mum_indirilen: set[tuple[str, str]] = set()
        self._akis_gorevler: set[asyncio.Task] = set()
        self._oturum = None
        self._bnc = None
        self._bnc_akis = None
        if float(cikis_tamamlama_dk) < 0:
            raise ValueError("cikis_tamamlama_dk negatif olamaz")
        self.cikis_tamamlama_dk = float(cikis_tamamlama_dk)
        self.asama = "indikator_hazirlik" if self.indikator_aktif else "hazirlik"
        self.yeni_giris_kapali = False
        self.drenaj_sinyal_red = 0
        self.drain_deadline = 0.0
        self.drain_baslatildi = False
        self.akis_motor = (FlowShadowEngine(
            self.akis, on_event=self._akis_golge_olay_yaz,
            on_close=self._akis_golge_kapanis_yaz,
        ) if self.akis_golge_aktif else None)
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
        # v18: risk limitleri VARSAYILAN ACIK ve config.py ile ayni gercegi
        # kullanir. Eski v13 davranisi yalnizca acikca risk_limitleri=False
        # verilirse (CLI: --risk-limitleri-kapali) elde edilir; bu durum
        # durum JSON'una da yazilir, sessiz sapma olmaz.
        if risk_limitleri:
            self.portfoy = PaperPortfolio(
                starting_balance=config.STARTING_BALANCE_USDT,
                fee_rate=config.TAKER_FEE_RATE,
                max_open_positions=config.MAX_OPEN_POSITIONS,
                max_same_direction=config.MAX_SAME_DIRECTION,
                max_utilisation=config.MAX_UTILISATION,
                balance_floor=config.BALANCE_FLOOR_USDT,
                daily_loss_limit_pct=config.DAILY_LOSS_LIMIT_PCT,
            )
        else:
            self.portfoy = PaperPortfolio(
                starting_balance=config.STARTING_BALANCE_USDT,
                fee_rate=config.TAKER_FEE_RATE,
                max_open_positions=None, max_same_direction=None,
                max_utilisation=None, balance_floor=0.0,
                daily_loss_limit_pct=None,
            )
        self.ticaret = TradeLogger(os.path.join(TABAN, "live_trades.csv"))
        # sure_dk sayacı, indikatör kapsamı kapısından geçmeden başlatılmaz.
        self.baslangic = None
        self.tarama_baslangic_utc = None
        self.sure_dk = sure_dk
        self.durdu = False

        self.binance_mod = binance_mod
        self.kayma_pct = float(kayma_pct)
        self.erken_hata_sn = float(erken_hata_sn); self.erken_hata_pct = float(erken_hata_pct)
        self.be_tetik_pct = float(be_tetik_pct); self.be_kilit_pct = float(be_kilit_pct)
        self.trail_tetik_pct = float(trail_tetik_pct); self.trail_mesafe_pct = float(trail_mesafe_pct)
        self.acilis_kap_10dk = int(acilis_kap_10dk); self.ayni_yon_kap = int(ayni_yon_kap)
        self._acilis_10dk: list[int] = []
        self.erken_hata_kapanan = 0; self.be_tetiklenen = 0; self.trail_tetiklenen = 0
        self._alarm_son: str = ""
        # v20: giris teyidi + stop asmasi + kademeli erken hata
        self.teyit_aktif = bool(teyit_aktif); self.teyit_pct = float(teyit_pct)
        self.teyit_bekle_sn = float(teyit_bekle_sn); self.stop_asma_pct = float(stop_asma_pct)
        self.erken_hata_ilk_sn = float(erken_hata_ilk_sn); self.erken_hata_ilk_pct = float(erken_hata_ilk_pct)
        self.teyit_bekleyen: dict[tuple[str, str], tuple] = {}
        self.teyit_acilan = 0; self.teyit_iptal = 0
        self.risk_limitleri = bool(risk_limitleri)
        self.durum_dosya = os.path.join(TABAN, 'logs', 'ws_state.json')
        self.sinyal_sayisi = 0
        self.indikator_hazirlik_sinyal_red = 0
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
        self.golge: dict[tuple[str, str], ShadowPosition] = {}
        self.golge_hatalari = 0
        self.golge_kayitlari = 0

        self.okx_tik = 0
        self.binance_tik = 0
        self.binance_aktif = False
        self.binance_hata: str | None = None
        self.okx_baglanti = 0
        self.okx_sembol = 0
        self.sembol_filtre_raporu = {}
        self.okx_ms = 0.0
        self.binance_ms = 0.0
        self._onceki_tik = (0, 0)
        self._olay_dosyasi_hazirla()
        if durum_devam:
            try:
                yuklenen = self._durum_yukle()
                log.info('durum devam: %d acik pozisyon kurtarildi', yuklenen)
            except Exception as exc:  # noqa: BLE001
                self.olay_yazici.close()
                raise RuntimeError('Kaydedilmis durum yuklenemedi; guvenlik icin baslatilmadi') from exc

    # ------------------------------------------------------------------
    def _olay_dosyasi_hazirla(self) -> None:
        fields = ["ts_utc", "exchange", "symbol", "yon", "etiket", "fiyat", "ret_pct", "rvol",
                  "hacim_usd", "pencere_ms", "gecikme_ms", "durum", "baglam_ret", "baglam_vratio", "baglam_vratio3"]
        os.makedirs(os.path.dirname(os.path.abspath(OLAY_CSV)), exist_ok=True)
        fh = open(OLAY_CSV, 'a+', newline='', encoding='utf-8')
        try:
            # Aynı lock protokolünü kullanan açılışları serileştirir.
            with file_lock(OLAY_CSV + '.lock'):
                fh.seek(0, os.SEEK_END)
                if fh.tell() == 0:
                    csv.writer(fh).writerow(fields)
                    fh.flush()
                    os.fsync(fh.fileno())
                else:
                    fh.seek(0)
                    first = next(csv.reader(fh), None)
                    if first: first[0] = first[0].lstrip('\ufeff')
                    if first != fields:
                        raise RuntimeError(f'olay CSV başlığı beklenmiyor: {first!r}; dosya korundu')
        except BaseException:
            fh.close()
            raise
        self.olay_yazici = fh
        self.olay_csv = csv.writer(fh)

    # ------------------------------------------------------------------
    def _akis_trade(self, sembol: str, fiyat: float, kontrat: float,
                    yon: str, ts: int, carpan: float) -> None:
        if self.akis is not None:
            self.akis.okx_ekle(sembol, fiyat, kontrat, yon, ts, carpan)
        if self.akis_motor is not None:
            try:
                self.akis_motor.on_trade("okx", sembol, ts, fiyat)
            except Exception:  # noqa: BLE001
                self.akis_golge_hatalari += 1
                if self.akis_golge_hatalari <= 3:
                    log.exception("akış gölge trade hatası: %s", sembol)

    def _binance_akis_trade(self, exchange: str, sembol: str, fiyat: float,
                            base: float, yon: str, ts: int) -> None:
        if self._real_volume is not None:
            self._real_volume.trade(exchange,sembol,fiyat,base,yon,ts)
        if self._hacim_shadow is not None:
            self._hacim_shadow.add(sembol, fiyat, base, ts)
        if self.akis is not None:
            self.akis.binance_ekle(sembol, fiyat, base, yon, ts)
        if self.akis_motor is not None:
            try:
                self.akis_motor.on_trade(exchange, sembol, ts, fiyat)
            except Exception:  # noqa: BLE001
                self.akis_golge_hatalari += 1
                if self.akis_golge_hatalari <= 3:
                    log.exception("binance akış gölge trade hatası: %s", sembol)

    @staticmethod
    def _akis_dosya_yaz(yol: str, alanlar: list[str], satir: dict) -> None:
        yeni = not os.path.exists(yol) or os.path.getsize(yol) == 0
        with open(yol, "a", newline="", encoding="utf-8") as fh:
            yazici = csv.DictWriter(fh, fieldnames=alanlar, extrasaction="ignore")
            if yeni:
                yazici.writeheader()
            yazici.writerow(satir)
            fh.flush()
            os.fsync(fh.fileno())

    def _akis_sinyal_yaz(self, s: Sinyal, durum: str, ts_utc: str) -> None:
        if self.akis is None:
            return
        try:
            alanlar = ["ts_utc", "exchange", "symbol", "side", "entry_price",
                       "signal_ret_pct", "signal_rvol", "signal_volume_usd",
                       "durum"] + akis_csv_alanlari()
            satir = {"ts_utc": ts_utc, "exchange": s.exchange, "symbol": s.symbol,
                     "side": s.yon, "entry_price": s.fiyat,
                     "signal_ret_pct": s.ret_pct, "signal_rvol": s.rvol,
                     "signal_volume_usd": s.hacim_usd, "durum": durum}
            satir.update(self.akis.alanlar(s.exchange, s.symbol, s.ts_ms))
            self._akis_dosya_yaz(AKIS_SINYAL_CSV, alanlar, satir)
            self.akis_sinyal_kayitlari += 1
        except Exception:  # noqa: BLE001
            self.akis_kayit_hatalari += 1
            log.exception("akış sinyali yazılamadı: %s:%s", s.exchange, s.symbol)

    def _akis_kapanis_yaz(self, rec, simdi: int) -> None:
        if self.akis is None:
            return
        anahtar = (rec.exchange, rec.symbol)
        try:
            giris = self.akis_giris.pop(anahtar, {})
            alanlar = ["exchange", "symbol", "side", "opened_at", "closed_at",
                       "entry_price", "exit_price", "reason", "realized_pnl"]
            alanlar += akis_csv_alanlari("giris_") + akis_csv_alanlari("cikis_")
            satir = {"exchange": rec.exchange, "symbol": rec.symbol, "side": rec.side,
                     "opened_at": rec.opened_at, "closed_at": rec.closed_at,
                     "entry_price": rec.entry_price, "exit_price": rec.exit_price,
                     "reason": rec.reason, "realized_pnl": rec.realized_pnl}
            satir.update(giris)
            satir.update(self.akis.alanlar(rec.exchange, rec.symbol, simdi, "cikis_"))
            self._akis_dosya_yaz(AKIS_KAPANIS_CSV, alanlar, satir)
            self.akis_kapanis_kayitlari += 1
        except Exception:  # noqa: BLE001
            self.akis_kayit_hatalari += 1
            log.exception("akış kapanışı yazılamadı: %s:%s", *anahtar)

    def _akis_golge_olay_yaz(self, row: dict) -> None:
        try:
            satir = dict(row)
            satir["ts_utc"] = datetime.fromtimestamp(
                row["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            alanlar = ["ts_utc", "ts", "tur", "exchange", "symbol", "side", "fiyat", "detay"]
            self._akis_dosya_yaz(AKIS_GOLGE_OLAY_CSV, alanlar, satir)
        except Exception:  # noqa: BLE001
            self.akis_golge_hatalari += 1
            log.exception("akış gölge olayı yazılamadı")

    def _akis_golge_kapanis_yaz(self, row: dict) -> None:
        try:
            alanlar = ["exchange", "symbol", "side", "signal_ts", "entry_ts", "exit_ts",
                       "entry_delay_s", "entry_price", "exit_price", "reason",
                       "gross_pnl", "fees", "realized_pnl", "mfe_pct", "mae_pct",
                       "close_ret_pct", "giveback_pct", "initial_stop", "stop_price",
                       "atr_at_exit", "hold_s"]
            self._akis_dosya_yaz(AKIS_GOLGE_KAPANIS_CSV, alanlar, row)
        except Exception:  # noqa: BLE001
            self.akis_golge_hatalari += 1
            log.exception("akış gölge kapanışı yazılamadı")

    async def _akis_mum_yukle(self, exchange: str, sembol: str) -> None:
        key = (exchange, sembol)
        try:
            mumlar = await tamamlanmis_mumlar(self._oturum, exchange, sembol)
            if self.akis_motor is not None:
                self.akis_motor.teknik_hazirla(exchange, sembol, mumlar)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            self.akis_golge_mum_hatalari += 1
            log.warning("akış gölge ATR mumları alınamadı: %s:%s", exchange, sembol)
        finally:
            self._akis_mum_indirilen.discard(key)

    def _akis_golge_sinyal(self, s: Sinyal) -> None:
        if self.akis_motor is None or s.exchange not in ("okx", "binance"):
            return
        key = (s.exchange, s.symbol)
        try:
            self.akis_motor.sinyal(s.exchange, s.symbol, s.yon, s.ts_ms, s.fiyat)
            if (key not in self.akis_motor.teknik
                    and key not in self._akis_mum_indirilen
                    and self._oturum is not None):
                self._akis_mum_indirilen.add(key)
                gorev = asyncio.create_task(self._akis_mum_yukle(s.exchange, s.symbol))
                self._akis_gorevler.add(gorev)
                gorev.add_done_callback(self._akis_gorevler.discard)
        except Exception:  # noqa: BLE001
            self.akis_golge_hatalari += 1
            log.exception("akış gölge sinyali işlenemedi: %s", s.symbol)

    # ------------------------------------------------------------------
    async def _sinyal_dispatch(self, s: Sinyal) -> None:
        """WebSocket okuyucusunu REST zenginleştirmesinde bloke etmeden kuyruğa al."""
        # Hazırlık anındaki adayları kuyruğa taşımamak, sonradan kapı açıldığında
        # warm-up sinyalinin ölçüme girmesini engeller.
        if self.indikator_aktif and not self.indikator_hazir:
            self.indikator_hazirlik_sinyal_red += 1
            return
        if self.yeni_giris_kapali:
            self.drenaj_sinyal_red += 1
            return
        task = asyncio.create_task(self.sinyal(s), name=f"sinyal:{s.exchange}:{s.symbol}")
        self._akis_gorevler.add(task)

        def _bitince(done):
            self._akis_gorevler.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                self.reddedilen += 1
                self.signal_filter_counts["entry_blocked"] += int(self.signal_enrichment_active)
                log.exception("sinyal görevi başarısız: %s:%s", s.exchange, s.symbol,
                              exc_info=(type(exc), exc, exc.__traceback__))

        task.add_done_callback(_bitince)

    async def _zengin_sinyali_degerlendir(self, raw: Sinyal, s: Sinyal) -> dict:
        if not self.signal_enrichment_active or self.signal_enricher is None:
            return {"accepted": True, "reasons": [], "mtf": {}, "derivatives": {}, "flow": {}}
        key = (s.exchange, s.symbol)
        lock = self._signal_key_locks.setdefault(key, asyncio.Lock())
        async with lock:
            binance_base = getattr(self._bnc, "BASE", BINANCE_PUBLIC_BASE)
            try:
                return await self.signal_enricher.evaluate(
                    self._oturum, exchange=s.exchange, symbol=s.symbol, side=s.yon,
                    ret_pct=raw.ret_pct, price=s.fiyat, flow_book=self.akis,
                    okx_contract_size=self._defter_kontratlar.get(s.symbol),
                    binance_base=binance_base, now_ms=int(time.time() * 1000),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.signal_enricher.fetch_errors += 1
                self.signal_enricher.last_error = (
                    f"{s.exchange}:{s.symbol} {type(exc).__name__}: {str(exc)[:140]}"
                )
                return {"accepted": False, "reasons": ["signal_intel_eval_failed"],
                        "error": self.signal_enricher.last_error, "flow": {},
                        "mtf": {"available": False},
                        "derivatives": {"available": False}}

    def _zengin_sinyal_yaz(self, raw: Sinyal, s: Sinyal, result: dict) -> None:
        mtf = result.get("mtf") or {}
        deriv = result.get("derivatives") or {}
        flow = result.get("flow") or {}
        reasons = result.get("reasons") or []
        fields = ["ts_utc", "exchange", "symbol", "raw_side", "paper_side", "ret_pct",
                  "accepted", "reasons", "mtf_trend", "mtf_score", "mtf_1h_score",
                  "mtf_4h_score", "funding_rate", "funding_crowding", "oi_usd",
                  "oi_change_pct", "oi_signal", "cvd15_usd", "cvd60_usd",
                  "taker_buy_sell_ratio_15s", "flow_total15_usd", "flow_trades15",
                  "flow_age_ms", "decision_age_ms", "error"]
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "ts_utc": now, "exchange": s.exchange, "symbol": s.symbol,
            "raw_side": raw.yon, "paper_side": s.yon, "ret_pct": raw.ret_pct,
            "accepted": int(bool(result.get("accepted"))),
            "reasons": ";".join(str(x) for x in reasons),
            "mtf_trend": mtf.get("trend"), "mtf_score": mtf.get("score"),
            "mtf_1h_score": (mtf.get("1h") or {}).get("score"),
            "mtf_4h_score": (mtf.get("4h") or {}).get("score"),
            "funding_rate": deriv.get("funding_rate"),
            "funding_crowding": deriv.get("funding_crowding"),
            "oi_usd": deriv.get("oi_usd"), "oi_change_pct": deriv.get("oi_change_pct"),
            "oi_signal": deriv.get("oi_signal"), "cvd15_usd": flow.get("cvd15_usd"),
            "cvd60_usd": flow.get("cvd60_usd"),
            "taker_buy_sell_ratio_15s": flow.get("taker_buy_sell_ratio"),
            "flow_total15_usd": flow.get("total15_usd"),
            "flow_trades15": flow.get("trades15"), "flow_age_ms": flow.get("age_ms"),
            "decision_age_ms": result.get("decision_age_ms"),
            "error": result.get("error", ""),
        }
        try:
            self._akis_dosya_yaz(self.signal_intel_csv, fields, row)
            self.signal_intel_events += 1
        except Exception:  # noqa: BLE001
            self.kayit_hatalari += 1
            log.exception("sinyal zenginleştirme CSV yazılamadı: %s:%s", s.exchange, s.symbol)

    def _zengin_sinyal_say(self, result: dict) -> None:
        if not self.signal_enrichment_active:
            return
        counts = self.signal_filter_counts
        counts["candidate"] += 1
        counts["fade_applied"] += int(self.strateji == "fade")
        mtf = result.get("mtf") or {}
        deriv = result.get("derivatives") or {}
        flow = result.get("flow") or {}
        reasons = set(result.get("reasons") or [])
        if not mtf.get("available"):
            counts["mtf_unavailable"] += 1
        elif "mtf_opposes_entry" in reasons:
            counts["mtf_block"] += 1
        else:
            counts["mtf_pass"] += 1
        funding_available = deriv.get("funding_rate") is not None
        oi_available = deriv.get("oi_usd") is not None
        if not deriv.get("available"):
            counts["funding_or_oi_unavailable"] += 1
        if not funding_available:
            counts["funding_unavailable"] += 1
        elif "funding_crowding_opposes_fade" in reasons:
            counts["funding_block"] += 1
        else:
            counts["funding_pass"] += 1
        if oi_available:
            counts["oi_available"] += 1
        else:
            counts["oi_unavailable"] += 1
        if deriv.get("oi_change_pct") is not None:
            counts["oi_delta_known"] += 1
        if "oi_price_matrix_opposes_entry" in reasons:
            counts["oi_conflict"] += 1
        if "signal_stale_at_confirmation" in reasons:
            counts["stale_at_decision"] += 1
        if flow.get("accepted"):
            counts["orderflow_pass"] += 1
        else:
            counts["orderflow_block"] += 1
            if str(flow.get("reason", "")).startswith("orderflow_"):
                counts["orderflow_unavailable"] += 1
        if result.get("accepted"):
            counts["entry_eligible"] += 1
        else:
            counts["entry_blocked"] += 1

    # ------------------------------------------------------------------
    async def sinyal(self, s: Sinyal) -> None:
        # Ön-dolgu/canlı akış hazırlığında gelen adaylar test örneklemine girmez;
        # sayacı ve paper portföyünü yalnızca global hazır kapısından sonra aç.
        if self.indikator_aktif and not self.indikator_hazir:
            self.indikator_hazirlik_sinyal_red += 1
            return
        if self.yeni_giris_kapali:
            self.drenaj_sinyal_red += 1
            return
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

        # strateji: momentum = ani hareketin yönünde, fade = tersine.
        # Ham yön korunur; MTF/funding/OI/taker-CVD onayı final paper yönünde yapılır.
        raw_s = s
        if self.strateji == "fade":
            s = Sinyal(ts_ms=s.ts_ms, exchange=s.exchange, symbol=s.symbol,
                       yon="SHORT" if s.yon == "LONG" else "LONG",
                       etiket=s.etiket, fiyat=s.fiyat, ret_pct=s.ret_pct,
                       rvol=s.rvol, hacim_usd=s.hacim_usd, gecen_ms=s.gecen_ms,
                       baglam_ret=s.baglam_ret, baglam_vratio=s.baglam_vratio,
                       baglam_vratio3=s.baglam_vratio3)
        enrichment = await self._zengin_sinyali_degerlendir(raw_s, s)
        if self.signal_enrichment_active:
            decision_age_ms = max(0, int(time.time() * 1000) - int(raw_s.ts_ms))
            enrichment["decision_age_ms"] = decision_age_ms
            if (decision_age_ms > MAX_SIGNAL_DECISION_AGE_MS
                    and enrichment.get("accepted")):
                enrichment["accepted"] = False
                enrichment["reasons"] = list(enrichment.get("reasons") or []) + [
                    "signal_stale_at_confirmation"
                ]
            self._zengin_sinyal_say(enrichment)
            self._zengin_sinyal_yaz(raw_s, s, enrichment)
        if enrichment.get("accepted", False):
            if self.defter_golge and self._oturum is not None:
                gore = asyncio.create_task(self._defter_golge_olc(s))
                self._akis_gorevler.add(gore)
                gore.add_done_callback(self._akis_gorevler.discard)
            durum = self._pozisyon_ac(s)
        else:
            self.reddedilen += 1
            nedenler = ",".join(enrichment.get("reasons") or ["onay_yok"])
            durum = "engel:sinyal_zenginlestirme:" + nedenler
        if self._hacim_shadow is not None and s.exchange == 'binance':
            try:
                d = self.detektor.durum(s.exchange, s.symbol)
                self._regime_yaz({'kind':'volume_shadow','exchange':s.exchange,
                    'symbol':s.symbol,'signal_ts':s.ts_ms,
                    'proxy_rvol':d.rvol,'proxy_son_hacim_ts':d.son_hacim_ts,
                    'aggtrade':self._hacim_shadow.snapshot(s.symbol,s.ts_ms)})
            except Exception:
                self.regime_yazma_hata += 1
                log.exception('gercek hacim shadow kaydi basarisiz')

        self.olay_csv.writerow([ts_utc, s.exchange, s.symbol, s.yon, s.etiket,
                                s.fiyat, s.ret_pct, s.rvol, s.hacim_usd, s.gecen_ms,
                                gecikme, durum, s.baglam_ret, s.baglam_vratio,
                                s.baglam_vratio3])
        self.olay_yazici.flush()
        self._akis_sinyal_yaz(s, durum, ts_utc)
        self._akis_golge_sinyal(s)

        self.son_sinyaller.append({
            "ts": ts_utc[11:], "exchange": s.exchange, "symbol": s.symbol,
            "yon": s.yon, "etiket": s.etiket, "fiyat": s.fiyat,
            "ret": s.ret_pct, "rvol": s.rvol, "gecikme_ms": gecikme,
            "baglam_ret": s.baglam_ret, "vratio3": s.baglam_vratio3,
        })
        self.son_sinyaller = self.son_sinyaller[-40:]

    def _regime_yaz(self, data: dict) -> None:
        path = os.path.join(TABAN, 'logs', 'indikator_shadow.jsonl')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n")
            fh.flush()

    def _regime_baslat(self, s: Sinyal) -> None:
        identity = {'exchange':s.exchange,'symbol':s.symbol,'side':s.yon,'opened_at':s.ts_ms}
        self._regime_yaz({'kind':'entry',**identity,'price':s.fiyat,'ret_pct':s.ret_pct})
        if self._oturum is None:
            self.regime_hata += 1
            self._regime_yaz({'kind':'features',**identity,'error':'network_session_unavailable'})
            return
        if len(self._regime_tasks) >= 32:
            self.regime_hata += 1
            self._regime_yaz({'kind':'features',**identity,'error':'shadow_queue_full'})
            return
        task = asyncio.create_task(self._regime_hesapla(s,identity))
        self._regime_tasks.add(task)
        task.add_done_callback(self._regime_tasks.discard)
        self._akis_gorevler.add(task)
        task.add_done_callback(self._akis_gorevler.discard)

    async def _regime_mum_al(self, s: Sinyal, interval: str):
        # Public REST kotasını korumak için paylaşılan sınırlı hız; borsanın
        # dinamik limitleri hakkında garanti değildir.
        async with self._regime_rate_lock:
            await asyncio.sleep(max(0.0, self._regime_next_request - time.monotonic()))
            self._regime_next_request = time.monotonic() + 1.5
        return await regime_fetch(self._oturum,s.exchange,s.symbol,s.ts_ms,interval)

    async def _regime_hesapla(self, s: Sinyal, identity: dict) -> None:
        try:
            async with self._regime_limit:
                errors = {}
                one, fifteen = [], []
                try:
                    one = await self._regime_mum_al(s,'1m')
                except Exception as exc:
                    errors['1m'] = f'{type(exc).__name__}: {str(exc)[:120]}'
                try:
                    fifteen = await self._regime_mum_al(s,'15m')
                except Exception as exc:
                    errors['15m'] = f'{type(exc).__name__}: {str(exc)[:120]}'
                result = regime_evaluate(one,fifteen,s.exchange,s.ts_ms,s.fiyat,s.ret_pct)
                result['data_errors'] = errors
                if errors: self.regime_hata += 1
            self._regime_yaz({'kind':'features',**identity,**result})
            self.regime_olcum += 1
        except asyncio.CancelledError:
            try: self._regime_yaz({'kind':'features',**identity,'error':'cancelled_before_completion'})
            except Exception: self.regime_yazma_hata += 1
            raise
        except Exception as exc:
            self.regime_hata += 1
            try: self._regime_yaz({'kind':'features',**identity,'error':f'{type(exc).__name__}: {str(exc)[:160]}'})
            except Exception: self.regime_yazma_hata += 1

    async def _defter_golge_olc(self, s: Sinyal) -> None:
        """Sadece gözlem: sinyaldeki defter snapshot'u, portföy dolumunu değiştirmez."""
        try:
            factor = 1.0 if s.exchange == "binance" else self._defter_kontratlar.get(s.symbol)
            if factor is None:
                raise ValueError("OKX kontrat carpani yok")
            async with self._defter_limit:
                result = await orderbook_snapshot(self._oturum, s.exchange, s.symbol, s.yon,
                                                  MARJ * KALDIRAC, factor=factor)
            path = os.path.join(TABAN, "logs", "defter_golge.csv")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            new = not os.path.exists(path)
            fields = ["signal_ts", "exchange", "symbol", "side", "notional_usd", "ts_ms",
                      "age_ms", "bid", "ask", "mid", "spread_pct", "target_qty", "filled_qty",
                      "fill_fraction", "vwap", "adverse_pct", "complete"]
            row = {"signal_ts": s.ts_ms, "exchange": s.exchange, "symbol": s.symbol,
                   "side": s.yon, "notional_usd": MARJ * KALDIRAC, **result}
            with open(path, "a", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields)
                if new: w.writeheader()
                w.writerow(row)
            self.defter_olcum += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.defter_hata += 1
            log.warning("defter gölge ölçümü başarısız %s:%s %s", s.exchange, s.symbol, exc)

    def _kaymali_giris(self, fiyat: float, yon: str) -> float:
        # v18 kayma modeli: gorevli (adverse) yonde uygula; limit dolumda 0.
        k = self.kayma_pct / 100.0
        return fiyat * (1 + k) if yon == "LONG" else fiyat * (1 - k)

    def _kaymali_cikis(self, fiyat: float, yon: str) -> float:
        k = self.kayma_pct / 100.0
        return fiyat * (1 - k) if yon == "LONG" else fiyat * (1 + k)

    def _limit_fiyati(self, fiyat: float, yon: str) -> float:
        """Fade yönünde, cari fiyatın `limit_payi` kadar ÖNÜNDEKİ fiyat."""
        if yon == "LONG":
            return fiyat * (1 - self.limit_payi / 100)
        return fiyat * (1 + self.limit_payi / 100)

    def _pozisyon_ac(self, s: Sinyal, limit_doldu: bool = False, teyitli: bool = False) -> str:
        """Pozisyon açar; her durumda insan-okur bir sebep döndürür."""
        if self.sadece_kayit:
            return "kayit_modu"
        if self.yeni_giris_kapali:
            self.reddedilen += 1
            return "engel:yeni_giris_kapali"

        # Aktif kapıyı nihai giriş/teyit/dolum yönünde yeniden doğrula.
        if getattr(self.detektor, 'ind_aktif', False):
            d = self.detektor.durum(s.exchange, s.symbol)
            uygun, neden, _ = giris_karari(d, s.ts_ms, s.fiyat, s.yon)
            if not uygun:
                self.detektor._kapi('giris_' + neden, s.exchange)
                self.reddedilen += 1
                return 'engel:' + neden

        # v20 GIRIS TEYIDI: sinyal aninda girme; fiyat, sinyal ucundan
        # teyit_pct kadar fade yonunde geri cekilene kadar bekle.
        # Dusen bicak / devam eden pompa, geri cekilme olmazsa hic girilmez.
        if self.teyit_aktif and not limit_doldu and not teyitli:
            if (s.exchange, s.symbol) in self.teyit_bekleyen:
                return "engel:teyit_bekliyor"
            self.teyit_bekleyen[(s.exchange, s.symbol)] = (
                s.ts_ms + int(self.teyit_bekle_sn * 1000), s.fiyat, s)
            return "bekliyor:teyit"

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
        for (b_exc, b_sym) in list(self.portfoy.positions.keys()) + list(self.bekleyen.keys()) + list(self.teyit_bekleyen.keys()):
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

        # v19 anti-churn: 10 dk'da acilis kapisi (0 = kapali)
        _simdi = int(time.time() * 1000)
        self._acilis_10dk = [t for t in self._acilis_10dk if _simdi - t <= 600_000]
        if self.acilis_kap_10dk > 0 and len(self._acilis_10dk) >= self.acilis_kap_10dk:
            self.reddedilen += 1
            return "engel:acilis_kapi_10dk"
        # v19 konsantrasyon: borsalar arasi ayni yonde toplam kap (0 = kapali)
        if self.ayni_yon_kap > 0:
            ayni = sum(1 for x in self.portfoy.positions.values() if x.side == s.yon)
            if ayni >= self.ayni_yon_kap:
                self.reddedilen += 1
                return "engel:ayni_yon_kap"
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

        giris_fiyat = s.fiyat if limit_doldu else self._kaymali_giris(s.fiyat, s.yon)
        if self.izole:
            # İZOLE MARJ: stop YOK. Pozisyon ancak marj bittiğinde kapanır.
            # Marjın bitmesi = fiyatın 100/kaldıraç kadar ters gitmesi.
            marj_bitis = 100.0 / KALDIRAC          # 10x → %10
            stop = (giris_fiyat * (1 - marj_bitis / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + marj_bitis / 100))
        else:
            stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + self.sl_pct / 100))
        tp = (giris_fiyat * (1 + self.tp_pct / 100) if s.yon == "LONG"
              else giris_fiyat * (1 - self.tp_pct / 100))

        giris_ucreti = config.MAKER_FEE_RATE if limit_doldu else config.TAKER_FEE_RATE
        sonuc = self.portfoy.open_position(
            s.exchange, s.symbol, s.yon, giris_fiyat, MARJ,
            leverage=KALDIRAC,
            now_ms=_simdi if self.signal_enrichment_active else s.ts_ms,
            price_ts=s.ts_ms if self.signal_enrichment_active else None,
            poll_interval_ms=5_000 if self.signal_enrichment_active else 2_000,
            entry_fee_rate=giris_ucreti,
            stop_price=stop, take_profit_price=tp,
        )
        if sonuc.ok:
            self.acilan += 1
            self._acilis_10dk.append(simdi_ms)
            self._acilis_gecmisi.append(simdi_ms)
            self._telemetri_baslat(s, anahtar)
            self._golge_baslat(anahtar)
            if self.indikator_golge:
                try:
                    self._regime_baslat(s)
                except Exception:
                    self.regime_hata += 1
                    log.exception('indikatör shadow baslatilamadi')
            if self.akis is not None:
                self.akis_giris[anahtar] = self.akis.alanlar(
                    s.exchange, s.symbol, simdi_ms, "giris_")
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

    def _golge_baslat(self, anahtar: tuple[str, str]) -> None:
        if not self.golge_cikis or self.izole:
            return
        try:
            pos = self.portfoy.positions[anahtar]
            self.golge[anahtar] = ShadowPosition(
                pos.exchange, pos.symbol, pos.side, pos.entry_price, pos.qty_base,
                pos.entry_fee, pos.opened_at, fee_rate=config.TAKER_FEE_RATE,
                variants=default_variants(self.tp_pct, self.sl_pct),
            )
        except Exception:  # noqa: BLE001
            self.golge_hatalari += 1
            self.golge.pop(anahtar, None)
            log.exception("gölge çıkış başlatılamadı: %s:%s", *anahtar)

    def _fiyat_guncelle(self, exchange: str, symbol: str, fiyat: float,
                        ts_ms: int | None = None) -> None:
        """Portföy mark'ı, salt-izleme telemetrisi ve bekleyen limitler."""
        simdi = ts_ms if ts_ms else int(time.time() * 1000)
        self.portfoy.mark_price(exchange, symbol, fiyat, simdi)
        self._teyit_isle(exchange, symbol, fiyat, simdi)
        self._telemetri_guncelle(exchange, symbol, fiyat, simdi)
        golge = self.golge.get((exchange, symbol))
        if golge is not None:
            try:
                golge.mark(fiyat, simdi)
            except Exception:  # noqa: BLE001
                self.golge_hatalari += 1
                self.golge.pop((exchange, symbol), None)
                log.exception("gölge fiyat güncellemesi yapılamadı: %s:%s", exchange, symbol)
        self._bekleyenleri_isle(exchange, symbol, fiyat)

    def _teyit_isle(self, exchange: str, symbol: str, fiyat: float, simdi: int) -> None:
        anahtar = (exchange, symbol)
        kayit = self.teyit_bekleyen.get(anahtar)
        if not kayit:
            return
        bitis_ms, uc, s0 = kayit
        if simdi > bitis_ms:
            self.teyit_bekleyen.pop(anahtar, None); self.teyit_iptal += 1; return
        # uc fiyat: LONG (dip alim) icin en dusuk, SHORT icin en yuksek
        uc = min(uc, fiyat) if s0.yon == "LONG" else max(uc, fiyat)
        self.teyit_bekleyen[anahtar] = (bitis_ms, uc, s0)
        onay = (fiyat >= uc * (1 + self.teyit_pct / 100) if s0.yon == "LONG"
                else fiyat <= uc * (1 - self.teyit_pct / 100))
        if not onay:
            return
        self.teyit_bekleyen.pop(anahtar, None)
        # Giris ve risk saatleri sinyal zamani degil, teyidin gerceklestigi andir.
        s = Sinyal(ts_ms=simdi, exchange=s0.exchange, symbol=s0.symbol,
                   yon=s0.yon, etiket=s0.etiket, fiyat=fiyat,
                   ret_pct=s0.ret_pct, rvol=s0.rvol, hacim_usd=s0.hacim_usd,
                   gecen_ms=s0.gecen_ms, baglam_ret=s0.baglam_ret,
                   baglam_vratio=s0.baglam_vratio, baglam_vratio3=s0.baglam_vratio3)
        if self._pozisyon_ac(s, teyitli=True) == "acildi":
            self.teyit_acilan += 1

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

    def _golge_kapat_yaz(self, exchange: str, symbol: str, fiyat: float,
                         simdi: int, sebep: str) -> None:
        tracker = self.golge.pop((exchange, symbol), None)
        if tracker is None:
            return
        try:
            tracker.finish(fiyat, simdi, sebep)
            rows = tracker.rows()
            for row in rows:
                for k, v in list(row.items()):
                    if isinstance(v, float):
                        row[k] = round(v, 10)
            os.makedirs(os.path.dirname(GOLGE_CSV), exist_ok=True)
            yeni = not os.path.exists(GOLGE_CSV) or os.path.getsize(GOLGE_CSV) == 0
            with open(GOLGE_CSV, "a", newline="", encoding="utf-8") as fh:
                yaz = csv.DictWriter(fh, fieldnames=list(rows[0]))
                if yeni:
                    yaz.writeheader()
                yaz.writerows(rows)
                fh.flush()
                os.fsync(fh.fileno())
            self.golge_kayitlari += len(rows)
        except Exception:  # noqa: BLE001
            self.golge_hatalari += 1
            log.exception("gölge çıkışlar yazılamadı: %s:%s", exchange, symbol)

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
        s = Sinyal(ts_ms=simdi, exchange=s0.exchange, symbol=s0.symbol,
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
        poz = self.portfoy.positions.get((exchange, symbol))
        cikis_fiyat = self._kaymali_cikis(fiyat, poz.side) if poz is not None else fiyat
        # v20 STOP ASMASI: stop tetiklendiyse kapanis, gozlenen fiyatin da
        # otesinde kotu fiyatlanir (dikey harekette stop seviyesinden dolum yok).
        if poz is not None and sebep == "stop_loss" and self.stop_asma_pct > 0:
            a = self.stop_asma_pct / 100.0
            cikis_fiyat = cikis_fiyat * (1 - a) if poz.side == "LONG" else cikis_fiyat * (1 + a)
        onceki_bakiye = self.portfoy.balance
        rec = self.portfoy.close_position(
            exchange, symbol, cikis_fiyat, now_ms=simdi, reason=sebep,
        )
        if rec is None:
            return None
        self.kapanan += 1
        self.pnl += rec.realized_pnl
        try:
            self._durum_kaydet(strict=True)
        except Exception:
            self.kapanan -= 1
            self.pnl -= rec.realized_pnl
            self.portfoy.balance = onceki_bakiye
            self.portfoy.closed_trades.pop()
            self.portfoy.positions[(exchange, symbol)] = poz
            raise
        if self.indikator_golge:
            try:
                self._regime_yaz({'kind':'close','exchange':rec.exchange,
                    'symbol':rec.symbol,'side':rec.side,'opened_at':rec.opened_at,
                    'closed_at':rec.closed_at,'realized_pnl':rec.realized_pnl,
                    'reason':rec.reason,'funding_label':rec.funding_label})
            except Exception:
                self.regime_yazma_hata += 1
                log.exception('indikatör shadow kapanis kaydi basarisiz')
        try:
            self.ticaret.sync_trades([rec])
            self.csv_kapanan += 1
        except Exception:  # noqa: BLE001
            self.kayit_hatalari += 1
            log.exception("kapanan işlem CSV'ye yazılamadı: %s:%s", exchange, symbol)
        self._akis_kapanis_yaz(rec, simdi)
        telemetri = self.telemetri.pop((exchange, symbol), None)
        if telemetri is not None:
            try:
                self._telemetri_yaz(telemetri, rec)
            except Exception:  # noqa: BLE001
                self.telemetri_hatalari += 1
                log.exception("çıkış telemetrisi yazılamadı: %s:%s", exchange, symbol)
        self._golge_kapat_yaz(exchange, symbol, fiyat, simdi, sebep)
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

    def _kar_kilidi_olay_yaz(self, pos, simdi: int, event: str, result: dict) -> None:
        fields = ["ts_ms", "exchange", "symbol", "side", "event", "price",
                  "profit_lock_stage", "mfe_usdt", "mfe_lock_active", "target_net_usdt",
                  "stop_price", "entry_fee", "funding_fee"]
        row = {
            "ts_ms": int(simdi), "exchange": pos.exchange, "symbol": pos.symbol,
            "side": pos.side, "event": event, "price": pos.last_price,
            "profit_lock_stage": pos.profit_lock_stage, "mfe_usdt": pos.mfe_usdt,
            "mfe_lock_active": int(pos.mfe_lock_active),
            "target_net_usdt": result.get("target_net_usdt"),
            "stop_price": pos.stop_price, "entry_fee": pos.entry_fee,
            "funding_fee": pos.funding_fee,
        }
        try:
            self._akis_dosya_yaz(self.profit_protection_csv, fields, row)
            self.kar_kilidi_olaylari += 1
        except Exception:  # noqa: BLE001
            self.kayit_hatalari += 1
            log.exception("kâr kilidi olayı yazılamadı: %s:%s", pos.exchange, pos.symbol)

    def _cikisleri_kontrol_et(self, simdi: int) -> int:
        """Tek çıkış turu; kapatılan pozisyon sayısını döndürür."""
        kapanan_once = self.kapanan
        for (ex, sym), pos in list(self.portfoy.positions.items()):
            fiyat = pos.last_price
            if not fiyat:
                continue
            golge = self.golge.get((ex, sym))
            if golge is not None:
                try:
                    golge.evaluate(fiyat, simdi)
                except Exception:  # noqa: BLE001
                    self.golge_hatalari += 1
                    self.golge.pop((ex, sym), None)
                    log.exception("gölge çıkış turu yapılamadı: %s:%s", ex, sym)
            yon = pos.side
            giris = pos.entry_price
            degisim = (fiyat - giris) / giris * 100
            if yon == "SHORT":
                degisim = -degisim

            # v19 cikis iyilestirmeleri: erken hata, basabas+trailing
            yas_sn = (simdi - pos.opened_at) / 1000.0
            # v20: kademeli — ilk erken_hata_ilk_sn saniyede daha dar esik
            _eh_esik = (self.erken_hata_ilk_pct if yas_sn <= self.erken_hata_ilk_sn
                        else self.erken_hata_pct)
            _eh_aktif = (yas_sn <= self.erken_hata_ilk_sn) or (self.erken_hata_sn > 0 and yas_sn >= self.erken_hata_sn)
            if (not self.izole and _eh_aktif and degisim <= -abs(_eh_esik)):
                sebep = "erken_hata"
                self.erken_hata_kapanan += 1
            else:
                sebep = None
                yeni_stop = None
                if degisim >= self.trail_tetik_pct:
                    yeni_stop = (fiyat * (1 - self.trail_mesafe_pct / 100) if yon == "LONG"
                                 else fiyat * (1 + self.trail_mesafe_pct / 100))
                elif degisim >= self.be_tetik_pct:
                    yeni_stop = (giris * (1 + self.be_kilit_pct / 100) if yon == "LONG"
                                 else giris * (1 - self.be_kilit_pct / 100))
                if yeni_stop is not None and not self.izole:
                    if pos.stop_price is None or (yon == "LONG" and yeni_stop > pos.stop_price) or (yon == "SHORT" and yeni_stop < pos.stop_price):
                        pos.stop_price = yeni_stop
                        if degisim >= self.trail_tetik_pct: self.trail_tetiklenen += 1
                        else: self.be_tetiklenen += 1
                if self.kar_kilidi_aktif:
                    old_stage = int(pos.profit_lock_stage)
                    old_mfe = bool(pos.mfe_lock_active)
                    protection = self.portfoy.update_profit_protection(
                        ex, sym,
                        market_slippage_pct=self.kayma_pct,
                        stop_overshoot_pct=self.stop_asma_pct,
                    )
                    if protection.get("stage_activated"):
                        new_stage = int(protection.get("stage", old_stage))
                        if old_stage < 1 <= new_stage:
                            self.kar_kilidi_kademe1 += 1
                            self._kar_kilidi_olay_yaz(pos, simdi, "stage1", protection)
                        if old_stage < 2 <= new_stage:
                            self.kar_kilidi_kademe2 += 1
                            self._kar_kilidi_olay_yaz(pos, simdi, "stage2", protection)
                    if protection.get("mfe_activated") and not old_mfe:
                        self.mfe_kalkan_aktivasyon += 1
                        self._kar_kilidi_olay_yaz(pos, simdi, "mfe_shield", protection)
            if sebep is None and pos.stop_price is not None:
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

    def _cikis_tamamlama_baslat(self) -> None:
        """Yeni girişi kes; açık pozisyonların doğal çıkışlarını beklemeye geç."""
        self.asama = "cikis_tamamlama"
        self.yeni_giris_kapali = True
        self.drain_baslatildi = True
        self.drain_deadline = time.time() + self.cikis_tamamlama_dk * 60
        self.bekleyen.clear()
        self.teyit_iptal += len(self.teyit_bekleyen)
        self.teyit_bekleyen.clear()
        if self.akis_motor is not None:
            self.akis_motor.adaylari_iptal_et(int(time.time() * 1000), "drain_start")
        log.info("tarama bitti — yeni giriş yok; doğal çıkış bekleme (%.1f dk)",
                 self.cikis_tamamlama_dk)

    def _acik_islem_var(self) -> bool:
        return bool(self.portfoy.positions or
                    (self.akis_motor is not None and self.akis_motor.pozisyonlar))

    # -- v18: kalıcı durum (cokme/yeniden baslatma kurtarma) -----------------
    def _durum_kaydet(self, *, strict: bool = False) -> None:
        try:
            os.makedirs(os.path.dirname(self.durum_dosya), exist_ok=True)
            veri = {"surum": 30, "balance": self.portfoy.balance,
                    "day_start_balance": self.portfoy.day_start_balance,
                    "funding_outbox": self.portfoy.funding_outbox,
                    "closed_trades": [asdict(x) for x in self.portfoy.closed_trades],
                    "acilan": self.acilan, "kapanan": self.kapanan, "pnl": self.pnl,
                    "positions": [
                        {"exchange": x.exchange, "symbol": x.symbol, "side": x.side,
                         "entry_price": x.entry_price, "qty_base": x.qty_base,
                         "margin": x.margin, "leverage": x.leverage,
                         "entry_fee": x.entry_fee, "opened_at": x.opened_at,
                         "stop_price": x.stop_price, "take_profit_price": x.take_profit_price,
                         "funding_fee": x.funding_fee, "funding_label": x.funding_label,
                         "last_funding_ts": x.last_funding_ts,
                         "funding_event_ts": x.funding_event_ts,
                         "funding_legacy_cursor": x.funding_legacy_cursor,
                         "last_price": x.last_price, "last_price_ts": x.last_price_ts,
                         "peak_price": x.peak_price, "mfe_usdt": x.mfe_usdt,
                         "profit_lock_stage": x.profit_lock_stage,
                         "mfe_lock_active": x.mfe_lock_active}
                        for x in self.portfoy.positions.values()]}
            atomic_json(self.durum_dosya, veri)
        except Exception:  # noqa: BLE001
            log.exception("durum kaydedilemedi")
            if strict:
                raise

    def _durum_yukle(self) -> int:
        if not os.path.exists(self.durum_dosya):
            return 0
        with open(self.durum_dosya, encoding="utf-8") as fh:
            veri = json.load(fh)
        from portfolio.paper_futures import Position, TradeRecord
        if "closed_trades" not in veri and int(veri.get("kapanan", 0)) > 0:
            raise ValueError("eski state kapanan-islem funding defteri icermiyor; guvenli migration gerekiyor")
        self.portfoy.balance = float(veri.get("balance", self.portfoy.balance))
        self.portfoy.day_start_balance = float(veri.get("day_start_balance", self.portfoy.day_start_balance))
        self.portfoy.funding_outbox = veri.get("funding_outbox", [])
        if not isinstance(self.portfoy.funding_outbox, list):
            raise ValueError("gecersiz funding outbox")
        self.portfoy.closed_trades = [TradeRecord(**d) for d in veri.get("closed_trades", [])]
        self.acilan = int(veri.get("acilan", self.acilan))
        self.kapanan = int(veri.get("kapanan", self.kapanan))
        self.pnl = float(veri.get("pnl", self.pnl))
        n = 0
        for d in veri.get("positions", []):
            poz = Position(exchange=d["exchange"], symbol=d["symbol"], side=d["side"],
                           entry_price=float(d["entry_price"]), qty_base=float(d["qty_base"]),
                           margin=float(d["margin"]), leverage=float(d["leverage"]),
                           entry_fee=float(d["entry_fee"]), opened_at=int(d["opened_at"]),
                           stop_price=d.get("stop_price"), take_profit_price=d.get("take_profit_price"),
                           funding_fee=float(d.get("funding_fee", 0.0)),
                           funding_label=d.get("funding_label", "funding hariç / bilinmiyor"),
                           last_funding_ts=int(d.get("last_funding_ts", 0)),
                           funding_event_ts=[int(x) for x in d.get("funding_event_ts", [])],
                           funding_legacy_cursor=int(d.get("funding_legacy_cursor", d.get("last_funding_ts", 0) if "funding_event_ts" not in d else 0)),
                           last_price=d.get("last_price"), last_price_ts=int(d.get("last_price_ts", 0)),
                           peak_price=d.get("peak_price", d.get("last_price", d.get("entry_price"))),
                           mfe_usdt=float(d.get("mfe_usdt", 0.0)),
                           profit_lock_stage=int(d.get("profit_lock_stage", 0)),
                           mfe_lock_active=bool(d.get("mfe_lock_active", False)))
            self.portfoy.positions[poz.key] = poz; n += 1
        if self.portfoy.closed_trades:
            self.ticaret.sync_trades(self.portfoy.closed_trades)
            self.csv_kapanan = len(self.portfoy.closed_trades)
        return n

    def _funding_state_kaydet(self) -> None:
        eski = self.pnl
        self.pnl = sum(r.realized_pnl for r in self.portfoy.closed_trades)
        try:
            self._durum_kaydet(strict=True)
        except Exception:
            self.pnl = eski
            raise

    def _funding_csv_mutabakat(self) -> None:
        self.ticaret.sync_trades(self.portfoy.closed_trades)

    # ------------------------------------------------------------------
    def durum_yaz(self) -> None:
        simdi_ts = time.time()
        evrenler = self.indikator_evrenleri if self.indikator_evrenleri else None
        indikator_kapsam = kapsam(self.detektor, int(simdi_ts * 1000), evrenler)
        self.indikator_kapsam_son = indikator_kapsam
        self._durum_kaydet()
        # v19 alarm: yalniz durum degisiminde logs/ws_alarm.jsonl'ye yaz
        alarm = ""
        if getattr(self, "binance_hata", None):
            alarm = f"binance_hata:{self.binance_hata}"
        elif self.portfoy.positions and (time.time() * 1000 - min(x.last_price_ts for x in self.portfoy.positions.values())) > 300_000:
            alarm = "bayat_fiyat:5dk"
        if alarm and alarm != self._alarm_son:
            self._alarm_son = alarm
            try:
                with open(os.path.join(TABAN, "logs", "ws_alarm.jsonl"), "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "alarm": alarm}) + "\n")
            except Exception:  # noqa: BLE001
                log.exception("alarm yazilamadi")
        elif not alarm:
            self._alarm_son = ""
        # v20: giris teyidi + stop asmasi + kademeli erken hata

        d = {
            "simdi": datetime.now().strftime("%H:%M:%S"),
            "pid": os.getpid(),
            "process_identity": self.proses_identity,
            "son_heartbeat_utc": datetime.now(timezone.utc).isoformat(),
            "baslama_utc": self.proses_baslama_utc,
            "surum": 37,
            "argv": sys.argv[1:],
            "calisiyor": not self.durdu,
            "kapanis_nedeni": self.kapanis_nedeni,
            "risk_limitleri": self.risk_limitleri,
            "v20": {"teyit_aktif": self.teyit_aktif, "teyit_bekleyen": len(self.teyit_bekleyen), "teyit_acilan": self.teyit_acilan, "teyit_iptal": self.teyit_iptal, "stop_asma_pct": self.stop_asma_pct},
            "signal_enrichment": {"active": self.signal_enrichment_active,
                                  "events": self.signal_intel_events,
                                  "filters": dict(self.signal_filter_counts),
                                  "engine": self.signal_enricher.status() if self.signal_enricher else {"active": False}},
            "profit_lock": {"active": self.kar_kilidi_aktif,
                            "stage1_trigger_pct": 0.50, "stage1_net_lock_pct": 0.12,
                            "stage2_trigger_pct": 0.90, "stage2_net_lock_pct": 0.30,
                            "mfe_min_usdt": 1.75, "mfe_keep_ratio": 0.48,
                            "net_buffer_usdt": 0.05,
                            "stage1_activations": self.kar_kilidi_kademe1,
                            "stage2_activations": self.kar_kilidi_kademe2,
                            "mfe_shield_activations": self.mfe_kalkan_aktivasyon,
                            "events_written": self.kar_kilidi_olaylari},
            "v19": {"erken_hata_kapanan": self.erken_hata_kapanan, "be_tetiklenen": self.be_tetiklenen, "trail_tetiklenen": self.trail_tetiklenen, "acilis_kap_10dk": self.acilis_kap_10dk, "ayni_yon_kap": self.ayni_yon_kap, "acilis_10dk_sayisi": len(self._acilis_10dk)},
            "kayma_pct": self.kayma_pct,
            "sure_sn": int(max(0.0, simdi_ts - self.baslangic)) if self.baslangic is not None else 0,
            "sure_dk_hedef": self.sure_dk,
            "hazirlik_sure_sn": int(max(0.0, simdi_ts - self.proses_baslama_ts)),
            "tarama_baslangic_utc": getattr(self, "tarama_baslangic_utc", None),
            "mod": "websocket",
            "asama": self.asama,
            "yeni_giris_kapali": self.yeni_giris_kapali,
            "cikis_tamamlama_dk": self.cikis_tamamlama_dk,
            "cikis_tamamlama_kalan_sn": (max(0, int(self.drain_deadline - time.time()))
                                          if self.drain_baslatildi and not self.durdu else 0),
            "drenaj_sinyal_red": self.drenaj_sinyal_red,
            "strateji": self.strateji,
            "tp": self.tp_pct,
            "sl": self.sl_pct,
            "bakiye": round(self.portfoy.equity, 4),
            "baslangic_bakiye": config.STARTING_BALANCE_USDT,
            "acik_pozisyon": self.portfoy.open_count(),
            "acik_pozisyonlar": [
                {"sembol": f"{ex}:{sym}", "yon": p.side, "giris": p.entry_price,
                 "fiyat": p.last_price, "marj": p.margin, "zirve_fiyat": p.peak_price,
                 "mfe_usdt": round(p.mfe_usdt, 6),
                 "profit_lock_stage": p.profit_lock_stage,
                 "mfe_lock_active": p.mfe_lock_active, "stop": p.stop_price,
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
            "golge_cikis": self.golge_cikis,
            "golge_kayitlari": self.golge_kayitlari,
            "golge_hatalari": self.golge_hatalari,
            "akis_olcum": self.akis_olcum,
            "akis_trade_sayisi": self.akis.trade_sayisi if self.akis is not None else 0,
            "akis_veri_hatalari": self.akis.hata_sayisi if self.akis is not None else 0,
            "akis_sinyal_kayitlari": self.akis_sinyal_kayitlari,
            "akis_kapanis_kayitlari": self.akis_kapanis_kayitlari,
            "akis_kayit_hatalari": self.akis_kayit_hatalari,
            "akis_golge_aktif": self.akis_golge_aktif,
            "akis_golge_aday": len(self.akis_motor.adaylar) if self.akis_motor else 0,
            "akis_golge_acik": len(self.akis_motor.pozisyonlar) if self.akis_motor else 0,
            "akis_golge_acilan": self.akis_motor.acilan if self.akis_motor else 0,
            "akis_golge_kapanan": self.akis_motor.kapanan if self.akis_motor else 0,
            "akis_golge_pnl": round(self.akis_motor.toplam_pnl, 8) if self.akis_motor else 0.0,
            "akis_golge_reddedilen": self.akis_motor.reddedilen if self.akis_motor else 0,
            "akis_golge_suresi_dolan": self.akis_motor.suresi_dolan if self.akis_motor else 0,
            "akis_golge_hatalari": self.akis_golge_hatalari,
            "akis_golge_mum_hatalari": self.akis_golge_mum_hatalari,
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
                        "onbellek_dolu": getattr(getattr(self, "_bnc", None), "onbellek_dolu", None),
                        "sembol": len(getattr(getattr(self, "_bnc", None), "semboller", ()) or ())},
            "binance_akis": ({"aktif": self._bnc_akis.aktif,
                               "trade": self._bnc_akis.trade_sayisi,
                               "baglanti": self._bnc_akis.baglanti_sayisi,
                               "hata": self._bnc_akis.hata_sayisi,
                               "callback_hata": self._bnc_akis.callback_hata_sayisi,
                               "supheli_id_boslugu": self._bnc_akis.supheli_id_boslugu,
                               "supheli_id_boslugu_sembol_ilkleri": [
                                   {"symbol": s, "count": n}
                                   for s, n in getattr(self._bnc_akis,
                                       'supheli_id_boslugu_sembol', {}).most_common(10)],
                               "son_hata": self._bnc_akis.son_hata,
                               "son_trade_ts": self._bnc_akis.son_trade_ts}
                              if self._bnc_akis is not None else None),
            "sembol_filtreleri": self.sembol_filtre_raporu,
            "defter_golge": {"aktif": self.defter_golge, "olcum": self.defter_olcum, "hata": self.defter_hata},
            "indikator_aktif": {"aktif":getattr(self.detektor,'ind_aktif',False),
                                "vwap":"son_60_tam_dakika_quote_base", "atr":"1m_wilder_14",
                                "atr_min_pct":0.10, "eksik_veri":"giris_kapali",
                                "hazirlik": {
                                    "aktif": self.indikator_aktif,
                                    "hazir": (not self.indikator_aktif or self._indikator_kapsam_hazir(indikator_kapsam)),
                                    "kapidan_gecti": self.indikator_hazir,
                                    "esik_yuzde": self.indikator_hazirlik_oran,
                                    "karsilastirma": "her_borsada_hazir_yuzde_esikten_buyuk",
                                    "zamanasimi_dk": self.indikator_hazirlik_zamanasimi_dk,
                                    "baslangic_utc": self.indikator_hazirlik_baslangic_utc,
                                    "bitis_utc": self.indikator_hazirlik_bitis_utc,
                                    "hata": self.indikator_hazirlik_hata,
                                    "hazirlikta_engellenen_sinyal": self.indikator_hazirlik_sinyal_red,
                                    "evren_toplamlari": {ex: len(sym)
                                        for ex, sym in self.indikator_evrenleri.items()},
                                },
                                "kapsam":indikator_kapsam},
            "indikator_golge": {"aktif":self.indikator_golge,"olcum":self.regime_olcum,
                                  "hata":self.regime_hata,"kayit_hata":self.regime_yazma_hata},
            "binance_hacim_kaynagi": self.binance_hacim_kaynagi,
            "binance_aggtrade_giris": ({"bagli_sembol":len(self._real_volume.connected),
                "kabul":self._real_volume.accepted,"bayat":self._real_volume.stale,
                "bayat_tani":self._real_volume.stale_summary(),
                "gecersiz":self._real_volume.invalid,"reset":self._real_volume.resets,
                "reset_nedenleri":self._real_volume.reset_summary(),
                "kismi_reset":self._real_volume.partial_reset_summary(),
                "sinyal_hata":self._real_volume.signal_errors}
                if self._real_volume is not None else None),
            "gercek_hacim_golge": {"aktif":self.binance_gercek_hacim_golge,
                                  "kapsam":"gozlenen_aggtrade_kesintisizlik_dogrulanmadi"},
            "funding": {"aktif": self.funding_aktif,
                        "kapsam": "kismi_acik_ve_kapanmis_pozisyon",
                        "uygulanan": getattr(self.funding_izleyici, "applied", 0),
                        "kapanmis_uygulanan": getattr(self.funding_izleyici, "closed_applied", 0),
                        "hata": getattr(self.funding_izleyici, "errors", 0),
                        "son_hata": getattr(self.funding_izleyici, "last_error", None),
                        "son_tarama_ms": getattr(self.funding_izleyici, "last_poll_ms", 0)},
            "kapi_sayaclari": getattr(self.detektor, "kapi_sayaclari", {}),
            "kapi_borsa": getattr(self.detektor, "kapi_borsa", {}),
            "genislik_aday": _genislik_aday_ozet(getattr(self.detektor, "genislik_aday", [])),
            "izlenen_sembol": len(self.detektor.durumlar),
            "hacim_hazir": sum(1 for d in self.detektor.durumlar.values() if d.hiz_uzun > 0),
            "son_gecikme_ms": self.son_sinyaller[-1].get("gecikme_ms") if self.son_sinyaller else None,
            "son_sinyaller": self.son_sinyaller[-20:],
        }
        atomic_json(DURUM_JSON, d)

    def _indikator_kapsam_hazir(self, rapor: dict) -> bool:
        """Her iki borsada da beklenen evrenin eşiğin ÜZERİNDE olması gerekir."""
        borsalar = rapor.get('borsalar', {})
        for exchange in ('binance', 'okx'):
            b = borsalar.get(exchange) or {}
            toplam = int(b.get('toplam', 0) or 0)
            hazir = int(b.get('mum_ve_fiyat_hazir', 0) or 0)
            if toplam <= 0 or (100.0 * hazir / toplam) <= self.indikator_hazirlik_oran:
                return False
        return True

    async def _indikator_hazirligini_bekle(self, okx, bnc, gorevler,
                                            binance_evreni=None) -> None:
        """REST ön-dolgu ve canlı akış sonrasında gerçek kapsam kapısını bekle."""
        if not self.indikator_aktif:
            return
        okx_evreni = set(getattr(okx, 'semboller', ()) or ())
        bnc_evreni = set(getattr(bnc, 'semboller', ()) or ())
        if not bnc_evreni and binance_evreni is not None:
            bnc_evreni = set(binance_evreni)
        if not bnc_evreni and getattr(self, '_bnc_akis', None) is not None:
            bnc_evreni = set(getattr(self._bnc_akis, 'semboller', ()) or ())
        if not okx_evreni or not bnc_evreni:
            raise RuntimeError('Indikator hazirlik kapisi icin OKX/Binance sembol evreni bos')

        self.indikator_evrenleri = {'okx': okx_evreni, 'binance': bnc_evreni}
        self.indikator_hazir = False
        self.indikator_hazirlik_hata = None
        self.indikator_hazirlik_baslangic_utc = datetime.now(timezone.utc).isoformat()
        self.asama = 'indikator_hazirlik'
        timeout_sn = self.indikator_hazirlik_zamanasimi_dk * 60.0
        deadline = time.monotonic() + timeout_sn
        binance_rest = bnc if isinstance(bnc, BinanceRestAkisi) else None
        sonraki_log = 0.0
        sonraki_mum_onarimi = 0.0

        while True:
            for gorev in gorevler:
                if not gorev.done():
                    continue
                if gorev.cancelled():
                    raise RuntimeError(f'{gorev.get_name()} gorevi hazirlik sirasinda iptal edildi')
                hata = gorev.exception()
                if hata is not None:
                    raise RuntimeError(f'{gorev.get_name()} gorevi hazirlik sirasinda basarisiz') from hata
                raise RuntimeError(f'{gorev.get_name()} gorevi hazirlik sirasinda beklenmedik sekilde bitti')

            rapor = kapsam(self.detektor, int(time.time() * 1000), self.indikator_evrenleri)
            self.indikator_kapsam_son = rapor
            if self._indikator_kapsam_hazir(rapor):
                self.indikator_hazir = True
                self.indikator_hazirlik_bitis_utc = datetime.now(timezone.utc).isoformat()
                bnc = rapor['borsalar']['binance']
                okx = rapor['borsalar']['okx']
                log.info(
                    'indikatör kapsamı hazır — Binance %s/%s (%%%.2f), OKX %s/%s (%%%.2f); '
                    'her ikisi de >%%%.1f. %g dakikalık test sayacı başlatılacak',
                    bnc['mum_ve_fiyat_hazir'], bnc['toplam'], bnc['hazir_yuzde'],
                    okx['mum_ve_fiyat_hazir'], okx['toplam'], okx['hazir_yuzde'],
                    self.indikator_hazirlik_oran, self.sure_dk)
                self.durum_yaz()
                return

            simdi_mono = time.monotonic()
            if simdi_mono >= deadline:
                parts = []
                for exchange in ('binance', 'okx'):
                    b = rapor.get('borsalar', {}).get(exchange, {})
                    parts.append(
                        f"{exchange} {b.get('mum_ve_fiyat_hazir', 0)}/{b.get('toplam', 0)}"
                        f" (%{b.get('hazir_yuzde', 0.0):.2f})")
                self.indikator_hazirlik_hata = 'zamanasimi'
                self.indikator_hazirlik_bitis_utc = datetime.now(timezone.utc).isoformat()
                self.asama = 'indikator_hazirlik_zamanasimi'
                self.durum_yaz()
                raise RuntimeError(
                    f"Indikator hazirlik zamanasimi ({self.indikator_hazirlik_zamanasimi_dk:g} dk): "
                    + ', '.join(parts))

            # REST ön-dolgu akıştan önce/akışla beraber bitmiş olabilir. AggTrade
            # bağlantısının ilk kısmi dakikası güvenli biçimde atıldığından,
            # göstergenin son 60 tam dakika penceresinde kalan boşlukları yalnız
            # Binance'in kapanmış klines verisiyle onar; stale paket/reset yoluna
            # dokunma. Yardımcı yalnız ind_mum'u yazar, bağlam/hacim deque'lerini
            # ikinci kez doldurmaz.
            if (self._real_volume is not None
                    and binance_rest is not None
                    and self._oturum is not None
                    and simdi_mono >= sonraki_mum_onarimi):
                try:
                    onarim = await binance_indikator_mum_eksiklerini_doldur(
                        self._oturum, self.detektor, bnc_evreni, taban=binance_rest.BASE)
                    delay = 15.0 if onarim["mum_eklenen"] else 60.0
                    sonraki_mum_onarimi = time.monotonic() + delay
                    if onarim["sembol_bosluklu"]:
                        log.info(
                            "Binance gösterge mum boşluğu onarımı — eksik sembol=%d, "
                            "eklenen mum=%d, tamamlanan sembol=%d, hata=%d",
                            onarim["sembol_bosluklu"], onarim["mum_eklenen"],
                            onarim["sembol_tamamlanan"], onarim["hata"])
                except Exception as exc:  # noqa: BLE001
                    sonraki_mum_onarimi = time.monotonic() + 60.0
                    log.warning("Binance gösterge mum onarımı atlandı: %s", exc)

            if simdi_mono >= sonraki_log:
                self.durum_yaz()
                bnc = rapor.get('borsalar', {}).get('binance', {})
                okx = rapor.get('borsalar', {}).get('okx', {})
                log.info(
                    'indikatör hazır olma bekleniyor — Binance %s/%s (%%%.2f), '
                    'OKX %s/%s (%%%.2f); her ikisi de >%%%.1f olmalı',
                    bnc.get('mum_ve_fiyat_hazir', 0), bnc.get('toplam', 0), bnc.get('hazir_yuzde', 0.0),
                    okx.get('mum_ve_fiyat_hazir', 0), okx.get('toplam', 0), okx.get('hazir_yuzde', 0.0),
                    self.indikator_hazirlik_oran)
                sonraki_log = simdi_mono + 10.0
            await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    async def calistir(self) -> None:
        async with aiohttp.ClientSession() as oturum:
            self._oturum = oturum
            # Etkin evrenleri bir kez al; OKX, Binance'te de bulunan aynı base
            # varlıkları taramaz. OKX fonksiyonu varsayılan olarak yalnız
            # instCategory=1 (kripto) döndürür; hisse/emtia kategorileri dışarıda.
            semboller, spot_bazlar = await okx_enstrumanlari(oturum)
            okx_ilk_sayisi = len(set(semboller))
            binance_tum = set(await binance_sembolleri(oturum))
            if not binance_tum:
                raise RuntimeError("Binance perpetual USDT evreni boş; sembol filtresi kurulamadı")
            secili_bnc = None
            binance_evreni = set(binance_tum)
            if self.sembol_limit:
                secili_bnc = set(sorted(binance_tum)[:self.sembol_limit])
                binance_evreni = set(secili_bnc)
                if not secili_bnc:
                    raise RuntimeError("Binance sembol evreni boş; limitli çalışma başlatılmadı")

            semboller = sorted(set(semboller))
            okx_stocklike = [s for s in semboller if is_stock_like(s)]
            semboller = [s for s in semboller if not is_stock_like(s)]
            semboller, bnc_ortak_okx = split_okx_binance_overlap(semboller, binance_evreni)
            if self.sembol_limit:
                semboller = semboller[:self.sembol_limit]
            if not semboller:
                raise RuntimeError("TradFi/ortak semboller çıkarıldıktan sonra OKX benzersiz evreni boş")
            self.sembol_filtre_raporu = {
                "okx_kategori": "instCategory=1 (kripto; hisse/emtia kategorileri dışarıda)",
                "okx_stocklike_denylist_cikarilan": okx_stocklike,
                "okx_ilk": okx_ilk_sayisi,
                "okx_binance_ortak_cikarilan": len(bnc_ortak_okx),
                "okx_son": len(semboller),
                "binance_aktif_evren": len(binance_evreni),
                "esleme": "normalize_base; ortaklarda Binance tutulur",
            }
            self.okx_sembol = len(semboller)
            if self.indikator_aktif:
                self.indikator_evrenleri = {'okx': set(semboller)}
            log.info(
                "sembol filtresi: OKX %d -> %d (TradFi denylist %d, Binance ortak %d çıkarıldı); "
                "Binance %d | OKX spot baz %d",
                okx_ilk_sayisi, len(semboller), len(okx_stocklike), len(bnc_ortak_okx),
                len(binance_evreni), len(spot_bazlar))

            # Bağlam filtresi 33 tamamlanmış dakika ister. REST ön-dolgusu
            # olmadan bot açılıştan sonra ~33 dk HİÇ sinyal üretmez.
            if getattr(self.detektor, "baglam_aktif", False):
                log.info("dakika geçmişi REST'ten dolduruluyor (%d sembol)...", len(semboller))
                t_0 = time.time()
                if getattr(self.detektor, 'ind_aktif', False):
                    dolu = await okx_dakika_onbellegi(oturum, self.detektor, semboller, adet=65)
                else:
                    dolu = await okx_dakika_onbellegi(oturum, self.detektor, semboller)
                log.info("dakika önbelleği: %d/%d sembol dolu (%.0f sn)",
                         dolu, len(semboller), time.time() - t_0)

            def fiyat_kontrol(exchange: str, symbol: str, fiyat: float,
                              ts_ms: int | None = None) -> None:
                """Canlı fiyat: portföy mark'ı + telemetri + limit dolumu."""
                self._fiyat_guncelle(exchange, symbol, fiyat, ts_ms)

            kontratlar = {}
            if self.akis_olcum or self.defter_golge:
                try:
                    kontratlar = await okx_kontrat_carpanlari(oturum)
                except Exception as exc:
                    log.warning("OKX kontrat carpanlari alinamadi: %s", exc)
            self._defter_kontratlar = kontratlar
            if self.akis_olcum:
                log.info("gerçek taker akışı: %d OKX kontrat çarpanı", len(kontratlar))
            okx = OKXAkisi(self.detektor, semboller, self._sinyal_dispatch, fiyat_kontrol,
                           akis_cb=self._akis_trade if self.akis_olcum else None,
                           kontrat_carpanlari=kontratlar)
            # Binance fiyat/ön-dolgu/aggTrade ve hazır kapsam aynı seçilmiş
            # evreni kullanır; Binance sembol kümesi yukarıda bir kez alındı.
            izin = {"sembol_izin": secili_bnc} if secili_bnc is not None else {}
            if self.binance_mod == "ws":
                bnc = BinanceAkisi(self.detektor, self._sinyal_dispatch, fiyat_kontrol, **izin)
            else:
                # WebSocket bu ortamda engelli → REST akışı
                bnc = BinanceRestAkisi(self.detektor, self._sinyal_dispatch, fiyat_kontrol,
                                       onbellek=self.binance_onbellek,
                                       hacim_kaynagi=self.binance_hacim_kaynagi, **izin)

            if self.indikator_aktif and binance_evreni is not None:
                self.indikator_evrenleri['binance'] = set(binance_evreni)
            self._bnc = bnc
            if self.akis_olcum or self.binance_gercek_hacim_golge or self._real_volume is not None:
                try:
                    bnc_semboller = sorted(binance_evreni)
                    self._bnc_akis = BinanceAggTradeFlow(
                        bnc_semboller, self._binance_akis_trade,
                        state_cb=self._real_volume.connection if self._real_volume is not None else None,
                        gap_cb=self._real_volume.connection_gap if self._real_volume is not None else None)
                    log.info("binance üretim aggTrade akışı: %d sembol", len(bnc_semboller))
                except Exception as exc:  # noqa: BLE001
                    log.warning("binance aggTrade akışı başlatılamadı: %s", exc)
            gorevler = [
                asyncio.create_task(okx.calistir(oturum), name="okx"),
                asyncio.create_task(bnc.calistir(oturum), name="binance"),
                asyncio.create_task(self.cikis_yonetimi(), name="cikis"),
                asyncio.create_task(self._sayac_dongusu(okx, bnc), name="sayac"),
            ]
            if self._bnc_akis is not None:
                async def binance_agg_akisi():
                    # Ön-dolgu ile canlı hacim dakikaları yarışmasın.
                    if self._real_volume is not None and isinstance(bnc, BinanceRestAkisi):
                        await bnc.hazir.wait()
                    await self._bnc_akis.calistir(oturum)
                gorevler.append(asyncio.create_task(binance_agg_akisi(), name="binance-akis"))
            if self.funding_aktif:
                self.funding_izleyici = FundingWatcher(self.portfoy,
                    journal_path=os.path.join(TABAN, 'logs', 'funding_olaylari.csv'),
                    on_change=self._funding_state_kaydet,
                    on_materialize=self._funding_csv_mutabakat)
                gorevler.append(asyncio.create_task(self.funding_izleyici.run(oturum), name='funding'))

            try:
                # Binance REST ön-dolgusu bitmeden hazırlık kapısı çalıştırılmaz.
                if isinstance(bnc, BinanceRestAkisi):
                    hazir_gorev = asyncio.create_task(bnc.hazir.wait())
                    tamam, _ = await asyncio.wait(
                        {hazir_gorev, gorevler[1]}, timeout=240,
                        return_when=asyncio.FIRST_COMPLETED)
                    if not hazir_gorev.done():
                        hazir_gorev.cancel()
                        await asyncio.gather(hazir_gorev, return_exceptions=True)
                        if gorevler[1] in tamam:
                            await gorevler[1]
                        raise RuntimeError("Binance REST 240 saniyede hazir olmadi")

                # Asıl süre; REST ön-dolgu + canlı fiyat/mum akışı sonrası,
                # iki borsanın da beklenen sembollerinde >%90 hazır kapsamda başlar.
                if self.indikator_aktif:
                    await self._indikator_hazirligini_bekle(
                        okx, bnc, gorevler, binance_evreni=binance_evreni)

                baslangic = time.time()
                self.baslangic = baslangic
                self.tarama_baslangic_utc = datetime.now(timezone.utc).isoformat()
                self.asama = "tarama"
                if self.indikator_aktif:
                    log.info("%.2f dakikalik asıl test sayaci indikatör hazirligi tamamlandiktan sonra basladi",
                             self.sure_dk)
                else:
                    log.info("%.2f dakikalik tarama Binance on-dolgusundan sonra basladi", self.sure_dk)
                self.durum_yaz()
                while not self.durdu:
                    await asyncio.sleep(1)
                    # Akislardan biri sessizce sonlanirsa bot saglikliymis gibi
                    # 15 dk saymak yerine tum oturumu hatayla sonlandirir.
                    for gorev in gorevler:
                        if gorev.done():
                            if not gorev.cancelled() and gorev.exception() is not None:
                                raise RuntimeError(f"{gorev.get_name()} gorevi basarisiz") from gorev.exception()
                            raise RuntimeError(f"{gorev.get_name()} gorevi beklenmedik sekilde bitti")
                    tarama_doldu = (self.sure_dk and
                                    (time.time() - baslangic) >= self.sure_dk * 60)
                    if tarama_doldu and not self.drain_baslatildi:
                        if self.cikis_tamamlama_dk > 0:
                            self._cikis_tamamlama_baslat()
                        else:
                            log.info("süre doldu (%.2f dk) — kapanıyor", self.sure_dk)
                            break
                    if self.drain_baslatildi:
                        if not self._acik_islem_var():
                            log.info("bütün pozisyonlar doğal çıkışla kapandı — kapanıyor")
                            break
                        if time.time() >= self.drain_deadline:
                            log.info("çıkış tamamlama süresi doldu — kalanlar drain_end ile kapatılacak")
                            break
            finally:
                self.durdu = True
                for g in gorevler:
                    g.cancel()
                await asyncio.gather(*gorevler, return_exceptions=True)
                if self._real_volume is not None:
                    for g in list(self._real_volume.tasks): g.cancel()
                    if self._real_volume.tasks:
                        await asyncio.gather(*list(self._real_volume.tasks), return_exceptions=True)
                for g in list(self._akis_gorevler):
                    g.cancel()
                if self._akis_gorevler:
                    await asyncio.gather(*list(self._akis_gorevler), return_exceptions=True)
                self._tumunu_kapat("drain_end" if self.drain_baslatildi else "session_end")
                self.asama = "tamamlandi"
                self.durum_yaz()
                self.olay_yazici.close()

    async def _sayac_dongusu(self, okx: OKXAkisi, bnc: BinanceAkisi) -> None:
        sonraki_tani = 0.0
        while not self.durdu:
            if getattr(self, 'diagnostics', None) is not None:
                self.diagnostics.thread_snapshot()
                simdi_tani = time.monotonic()
                if simdi_tani >= sonraki_tani:
                    self.diagnostics.ws_ping(okx, bnc, self._bnc_akis)
                    self.diagnostics.event_yuk(self)
                    sonraki_tani = simdi_tani + 5.0
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
            await asyncio.sleep(1)

    def _tumunu_kapat(self, sebep: str = "session_end") -> None:
        self.bekleyen.clear()
        simdi = int(time.time() * 1000)
        for (ex, sym), pos in list(self.portfoy.positions.items()):
            fiyat = pos.last_price or pos.entry_price
            self._kapat_ve_kaydet(ex, sym, fiyat, simdi, sebep)
        if self.akis_motor is not None:
            try:
                self.akis_motor.session_end(simdi, sebep)
            except Exception:  # noqa: BLE001
                self.akis_golge_hatalari += 1
                log.exception("akış gölge session-end hatası")
        self._kayit_mutabakati()


# ---------------------------------------------------------------------------
def _negatif_olmayan_tam_sayi(text: str) -> int:
    try:
        n = int(text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("negatif olmayan tam sayı gerekli") from exc
    if n < 0:
        raise argparse.ArgumentTypeError("negatif olmayan tam sayı gerekli")
    return n


def _main(argv=None) -> int:
    # SIGINT yok sayılarak başlatılmışsa, kullanıcı iptalini işleyebilmek
    # için varsayılan Python davranışını geri getir. Özel handler'a dokunma.
    import signal as _sig
    if _sig.getsignal(_sig.SIGINT) is _sig.SIG_IGN:
        _sig.signal(_sig.SIGINT, _sig.default_int_handler)
    ap = argparse.ArgumentParser(description="Sürekli WebSocket tarama botu",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--sure-dk", type=float, default=0, help="0 = süresiz")
    ap.add_argument("--sembol-limit", type=_negatif_olmayan_tam_sayi, default=0,
                    help="0 = tümü; pozitif değer = her borsada en fazla N sıralı sembol")
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
    ap.add_argument("--tp", type=float, default=0.8,
                    help="kâr al eşiği (yüzde)")
    ap.add_argument("--sl", type=float, default=0.5,
                    help="zarar durdur eşiği (yüzde)")
    ap.add_argument("--tut-dk", type=float, default=5.0,
                    help="azami pozisyon tutma süresi (dakika)")
    ap.add_argument("--sadece-kayit", action="store_true",
                    help="işlem açma, yalnızca sinyal kaydet (veri toplama)")
    ap.add_argument("--giris", choices=("market", "limit"), default="limit",
                    help="Paper varsayılanı limit/maker-model giriş; dolmayan limit iptal edilir. Çıkış ücreti taker olarak kalır.")
    ap.add_argument("--limit-payi", type=float, default=0.05,
                    help="limit fiyatı cari fiyatın %% kaç önüne konur")
    ap.add_argument("--limit-bekle-sn", type=float, default=30.0,
                    help="limit emrin geçerlilik süresi (saniye)")
    ap.add_argument("--yon", choices=("hepsi", "long", "short"), default="hepsi",
                    help="işlem yönü filtresi")
    ap.add_argument("--baglam", action=argparse.BooleanOptionalAction, default=True,
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
    ap.add_argument("--cascade-esik", type=int, default=1,
                    help="son 60 sn'de bu kadar sinyal yoksa işlem açma (0/1 = kapalı)")
    ap.add_argument("--acilis-freni", type=int, default=OLAY_AZAMI_ACILIS,
                    help="10 sn içinde en fazla N yeni pozisyon; 0 = kapalı (v12 varsayılanı)")
    ap.add_argument("--golge-cikis", action="store_true",
                    help="alternatif çıkışları aynı tiklerde salt-izleme yarıştır; ana stratejiyi değiştirmez")
    ap.add_argument("--akis-olcum", action="store_true",
                    help="OKX+Binance gerçek taker akışını ölç; ana stratejiyi değiştirmez")
    ap.add_argument("--akis-golge", action="store_true",
                    help="ARAŞTIRMA: OKX+Binance CVD15+VWAP60 ve ATR runner gölgesi")
    ap.add_argument("--cikis-tamamlama-dk", type=float, default=0.0,
                    help="Tarama bitince yeni girişleri kesip doğal çıkışları bekle; 0 = eski session-end")
    ap.add_argument("--risk-limitleri-kapali", action="store_true", help="v18: risk limitlerini kapat (v13 davranisi; onerilmez)")
    ap.add_argument("--kayma-pct", type=float, default=0.05, help="v18: market giris/cikista olumsuz kayma %% (vars. 0.05)")
    ap.add_argument("--durum-devam", action="store_true", help="v18: logs/ws_state.json varsa acik pozisyonlari kurtar")
    ap.add_argument("--erken-hata-sn", type=float, default=90.0, help="v19: bu surede -%%erken-hata-pct altina inen pozisyonu kapat (0=kapali)")
    ap.add_argument("--erken-hata-pct", type=float, default=0.8)
    ap.add_argument("--be-tetik-pct", type=float, default=0.6, help="v19: bu kara ulasinca stopu giris+maliyete cek")
    ap.add_argument("--trail-tetik-pct", type=float, default=1.0, help="v19: trailing stop tetik %%")
    ap.add_argument("--trail-mesafe-pct", type=float, default=0.5)
    ap.add_argument("--acilis-kap-10dk", type=int, default=20, help="v19: 10 dk'da azami yeni acilis (0=kapali)")
    ap.add_argument("--ayni-yon-kap", type=int, default=20, help="v19: borsalar arasi ayni yonde azami pozisyon (0=kapali)")
    ap.add_argument("--giris-teyit", action=argparse.BooleanOptionalAction, default=True, help="v20: fade girisi oncesi geri cekilme teyidi bekle (kapatmak icin --no-giris-teyit)")
    ap.add_argument("--sinyal-zenginlestirme", action=argparse.BooleanOptionalAction, default=True,
                    help="Paper girişinde 1h/4h MTF + same-venue funding/OI + gerçek taker/CVD onayı (varsayılan açık; veri yoksa giriş engellenir)")
    ap.add_argument("--kar-kilidi", action=argparse.BooleanOptionalAction, default=True,
                    help="PaperPortfolio'da iki kademe net kâr kilidi ve MFE zirve kalkanı (varsayılan açık)")
    ap.add_argument("--teyit-pct", type=float, default=0.15, help="v20: teyit icin ucten geri cekilme %%")
    ap.add_argument("--teyit-bekle-sn", type=float, default=30.0, help="v20: teyit bekleme suresi sn")
    ap.add_argument("--stop-asma-pct", type=float, default=0.10, help="v20: stop kapanisinda ek asma/kayma %%")
    ap.add_argument("--defter-golge", action=argparse.BooleanOptionalAction, default=True,
                    help="Sinyalde 50 seviye spread/derinlik/kayma GOLGE olcumu; dolumu degistirmez")
    ap.add_argument("--binance-hacim-kaynagi", choices=("proxy","aggtrade"), default="proxy",
                    help="Deneysel aggtrade: gerçek USD; kopma/ısınma fail-closed; sessiz proxy fallback yok")
    ap.add_argument("--indikator-golge", action="store_true", help="Yalnız gözlem: kapalı mumlardan bağımsız indikatör ölçümü; kararları değiştirmez")
    ap.add_argument("--indikator-hazirlik-oran", type=float, default=90.0,
                    help="Asıl süre sayacı için her borsada aşılması gereken hazır kapsam yüzdesi (varsayılan: >90)")
    ap.add_argument("--indikator-hazirlik-zamanasimi-dk", type=float, default=75.0,
                    help="Kapsam eşiği aşılmazsa güvenli duruş (dakika; varsayılan: 75)")
    ap.add_argument("--binance-gercek-hacim-golge", action="store_true", help="aggTrade hacmini bağımsız gölge ölç; ana sinyali değiştirmez")
    ap.add_argument("--funding-izle", action=argparse.BooleanOptionalAction, default=True,
                    help="Acik paper pozisyonlarda kismi gerceklesen funding mutabakati (tam kapsama garantisi yok)")
    ap.add_argument("--binance-onbellek", action=argparse.BooleanOptionalAction, default=True,
                    help="v21: Binance 1m geçmişini REST'ten ön-doldur (kapatmak için --no-binance-onbellek)")
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
    # Yalnız bu deneysel paper adayında: kullanıcı seçimi doğrultusunda aktif.
    detektor.ind_aktif = True
    detektor.ind_strateji = args.strateji
    bot = Bot(detektor, sure_dk=args.sure_dk, binance_mod=args.binance,
              sembol_limit=args.sembol_limit,
              sadece_kayit=args.sadece_kayit, strateji=args.strateji,
              tp=args.tp, sl=args.sl, tut_dk=args.tut_dk,
              giris_modu=args.giris, limit_payi=args.limit_payi,
              limit_bekle_sn=args.limit_bekle_sn,
              cascade_esik=args.cascade_esik,
              min_genislik=args.min_genislik,
              izole=args.izole,
              acilis_freni=args.acilis_freni,
              golge_cikis=args.golge_cikis,
              akis_olcum=args.akis_olcum,
              akis_golge=args.akis_golge,
              cikis_tamamlama_dk=args.cikis_tamamlama_dk,
              risk_limitleri=not args.risk_limitleri_kapali,
              kayma_pct=args.kayma_pct, durum_devam=args.durum_devam,
              erken_hata_sn=args.erken_hata_sn, erken_hata_pct=args.erken_hata_pct,
              be_tetik_pct=args.be_tetik_pct, trail_tetik_pct=args.trail_tetik_pct,
              trail_mesafe_pct=args.trail_mesafe_pct,
              acilis_kap_10dk=args.acilis_kap_10dk, ayni_yon_kap=args.ayni_yon_kap,
              teyit_aktif=args.giris_teyit, teyit_pct=args.teyit_pct,
              teyit_bekle_sn=args.teyit_bekle_sn, stop_asma_pct=args.stop_asma_pct,
              binance_onbellek=args.binance_onbellek, funding_aktif=args.funding_izle,
              defter_golge=args.defter_golge, indikator_golge=args.indikator_golge,
              binance_gercek_hacim_golge=args.binance_gercek_hacim_golge,
              binance_hacim_kaynagi=args.binance_hacim_kaynagi,
              indikator_hazirlik_oran=args.indikator_hazirlik_oran,
              indikator_hazirlik_zamanasimi_dk=args.indikator_hazirlik_zamanasimi_dk,
              sinyal_zenginlestirme=args.sinyal_zenginlestirme,
              kar_kilidi_aktif=args.kar_kilidi)
    bot.yon_filtre = args.yon

    def kapanis_yaz(durum, neden, cikis_kodu, hata=None):
        path = os.path.join(TABAN, 'logs', 'ws_kapanis.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        body = {'durum':durum, 'kapanis_nedeni':neden, 'cikis_kodu':cikis_kodu,
                'pid':os.getpid(), 'process_identity':bot.proses_identity,
                'baslama_utc':bot.proses_baslama_utc,
                'son_guncelleme_utc':datetime.now(timezone.utc).isoformat(),
                'hata_turu':hata}
        atomic_json(path,body)

    diag = Diagnostics(TABAN)
    bot.diagnostics = diag
    diag.start()
    kapanis_yaz('baslatildi', 'bilinmiyor', None)

    async def izlenen_calistir():
        loop = asyncio.get_running_loop()
        diag.attach_loop(loop)
        stop_signal = loop.create_future()
        registered = []
        fallback = []

        def durdurma_iste(sig_no):
            if not stop_signal.done():
                diag.emit('signal', signal=_sig.Signals(sig_no).name)
                stop_signal.set_result(sig_no)

        # Sinyal istisnası coroutine'in rastgele bir noktasında yükselmez;
        # event loop bot görevini kontrollü iptal edip JSON kapanışını yazar.
        for sig_no in (_sig.SIGTERM, _sig.SIGINT, _sig.SIGHUP):
            old = _sig.getsignal(sig_no)
            try:
                loop.add_signal_handler(sig_no, durdurma_iste, sig_no)
                registered.append((sig_no, old))
            except (NotImplementedError, RuntimeError):
                _sig.signal(sig_no, lambda n, _frame: loop.call_soon_threadsafe(durdurma_iste, n))
                fallback.append((sig_no, old))

        async def heartbeat():
            sayac = 0
            while True:
                await asyncio.sleep(5)
                bot.durum_yaz()
                sayac += 1
                if sayac % 2 == 0:
                    diag.sample(bot)
        hb = asyncio.create_task(heartbeat(), name='süreç-heartbeat')
        task = asyncio.create_task(bot.calistir(), name='bot')
        try:
            done, _ = await asyncio.wait({hb, task, stop_signal},
                                         return_when=asyncio.FIRST_COMPLETED)
            if stop_signal in done:
                sig_no = stop_signal.result()
                bot.durdu = True
                bot.kapanis_nedeni = ('kullanici_iptal' if sig_no == _sig.SIGINT
                                      else 'sinyal_' + str(sig_no))
                log.info('kontrollü kapanış istendi: %s', _sig.Signals(sig_no).name)
                return sig_no
            if hb in done:
                await hb
                raise RuntimeError('heartbeat beklenmedik biçimde bitti')
            await task
            return None
        finally:
            hb.cancel()
            if not task.done():
                task.cancel()
            await asyncio.gather(hb, task, return_exceptions=True)
            for sig_no, old in registered:
                loop.remove_signal_handler(sig_no)
                _sig.signal(sig_no, old)
            for sig_no, old in fallback:
                _sig.signal(sig_no, old)

    def bitis_yaz(neden,kod,hata=None):
        bot.durdu=True
        bot.kapanis_nedeni=neden
        try: bot.durum_yaz()
        except Exception: log.exception('son durum kaydı yazılamadı')
        kapanis_yaz('tamamlandi',neden,kod,hata)
        diag.emit('process_exit',neden=neden,exit_code=kod,hata_turu=hata)
        diag.finish()

    try:
        bot.durum_yaz()
        sinyal_no = asyncio.run(izlenen_calistir())
        if sinyal_no is not None:
            kod = 128 + int(sinyal_no)
            neden = ('kullanici_iptal' if sinyal_no == _sig.SIGINT
                     else 'sinyal_' + str(int(sinyal_no)))
            bitis_yaz(neden, kod)
            return kod
    except KeyboardInterrupt:
        diag.emit('signal', signal='SIGINT')
        bitis_yaz('kullanici_iptal', 130)
        return 130
    except ProcessSignal as exc:
        kod = 128 + exc.number
        neden = ('kullanici_iptal' if exc.number == _sig.SIGINT
                 else 'sinyal_' + str(exc.number))
        bitis_yaz(neden, kod)
        return kod
    except BaseException as exc:
        bitis_yaz('hata',1,type(exc).__name__)
        raise
    else:
        bitis_yaz('normal',0)

    print(f"\n  Sinyal   : {bot.sinyal_sayisi}")
    print(f"  Açılan   : {bot.acilan}")
    print(f"  Kapanan  : {bot.kapanan}")
    print(f"  PnL      : {bot.pnl:+.4f} USDT")
    print(f"  Bakiye   : {bot.portfoy.equity:.2f} USDT")
    print("\n  Funding kısmi/bilinmiyor olabilir · paper simülasyon · yatırım tavsiyesi değil")
    return 0


def main(argv=None) -> int:
    try:
        with instance_lock(os.path.join(TABAN,'logs','ws_bot.instance.lock')):
            return _main(argv)
    except InstanceBusy as exc:
        print(str(exc),file=sys.stderr,flush=True)
        return 2


if __name__ == "__main__":
    try:
        _exit_code = main()
    except BaseException:
        print("PROCESS_EXIT_CODE=1", flush=True)
        raise
    print(f"PROCESS_EXIT_CODE={_exit_code}", flush=True)
    raise SystemExit(_exit_code)
