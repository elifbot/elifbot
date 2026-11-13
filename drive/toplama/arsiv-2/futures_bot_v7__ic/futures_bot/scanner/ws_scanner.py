#!/usr/bin/env python3
"""
scanner/ws_scanner.py — SÜREKLİ, TÜM SEMBOLLERİ tarayan WebSocket tarayıcı.

NEDEN WEBSOCKET
---------------
REST ile 500 sembolün mumunu çekmek tur başına ~500 istek demek: yavaş,
rate-limit sınırında ve saniyeler mertebesinde. WebSocket'te borsa veriyi
KENDİSİ iter; tarayıcı her tik geldiğinde anında hesap yapar. Tur yoktur.

KAPSAM (doğrulandı)
-------------------
OKX tickers    : wss://ws.okx.com:443/ws/v5/public    · 100 ms itme · FİYAT
OKX candle1m   : wss://ws.okx.com:443/ws/v5/business  · HACİM (monoton)
Binance !ticker@arr : wss://fstream.binance.com/ws/!ticker@arr · tek akışta tüm semboller
                 (bu ortamda 451 bölgesel engel — kod hazır, engelsiz IP gerekir)

ÖLÇÜLEN GERÇEK YÜK
------------------
511 USDT-SWAP tickers → ~1.600 mesaj/sn, 3 bağlantı
511 USDT-SWAP candle1m → ~230 mesaj/sn, 3 bağlantı

NEDEN candle1m?
---------------
tickers kanalındaki volCcy24h KAYAN 24 saatlik sayaçtır — monoton DEĞİL.
Ölçüm: 2 sn'lik delta medyanı −$18, p75 = $0. Hacim ölçümü buna dayanamaz.
candle1m ise dakika başına sıfırlanan KÜMÜLATİF hacim verir; dakika içinde
monotondur ve para birimi cinsinden (volCcyQuote) doğrudan USD'dir.

HESAP
-----
ret_2s  = (son fiyat − 2 sn önceki fiyat) / 2 sn önceki fiyat × 100
hız_kısa= son 10 sn'deki USD hacim / 10      (candle1m'den)
hız_uzun= son 120 sn'deki USD hacim / 120
rvol    = hız_kısa / hız_uzun

ANI  =  |ret_2s| >= RET_MIN  VE  rvol >= RVOL_MIN  VE  hacim_10s >= MIN_USD

Eşik aşıldığı ANDA sinyal üretilir; bir sonraki tura beklenmez.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import aiohttp

log = logging.getLogger("ws_scanner")

OKX_PUBLIC = "wss://ws.okx.com:443/ws/v5/public"
OKX_BUSINESS = "wss://ws.okx.com:443/ws/v5/business"
OKX_INSTR = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
OKX_SPOT = "https://www.okx.com/api/v5/public/instruments?instType=SPOT"
BINANCE_WS = "wss://fstream.binance.com/ws/!ticker@arr"

OKX_SUB_PER_REQUEST = 100          # tek istekte abone edilecek enstrüman
OKX_MAX_PER_CONN = 200             # bağlantı başına enstrüman (limit ~240)


# ---------------------------------------------------------------------------
@dataclass
class Sinyal:
    ts_ms: int
    exchange: str
    symbol: str
    yon: str                  # LONG | SHORT
    etiket: str               # ANI_YUKSELIS | ANI_DUSUS
    fiyat: float
    ret_pct: float
    rvol: float
    hacim_usd: float
    gecen_ms: int
    baglam_ret: float = 0.0        # 3 dakikalık getiri (%)
    baglam_vratio: float = 0.0     # cari dakikanın tek-dakika hacim oranı
    baglam_vratio3: float = 0.0    # 3 dakikalık ORTALAMA hacim oranı (geri testle aynı)


@dataclass
class SembolDurum:
    """Bir sembolün fiyat penceresi + hacim sayaçları."""
    exchange: str
    symbol: str

    # --- fiyat ---
    son_fiyat: float = 0.0
    son_fiyat_ts: int = 0
    tik_sayisi: int = 0
    # (ts_ms, fiyat) — son PEN_MAX örnek
    fiyatlar: deque = field(default_factory=lambda: deque(maxlen=4000))  # 60 sn pencere icin
    ret_2s: float = 0.0

    # --- hacim (candle1m) ---
    dakika_id: int = -1
    dakika_qv: float = 0.0            # cari dakikada biriken USD hacim
    tamamlanan_qv: float = 0.0        # kapanmış dakikaların toplamı
    hacim_tik: int = 0
    # (ts_ms, toplam_qv) — monoton küresel sayaç
    hacimler: deque = field(default_factory=lambda: deque(maxlen=900))
    hiz_kisa: float = 0.0
    hiz_uzun: float = 0.0
    rvol: float = 0.0
    son_hacim_ts: int = 0

    # --- likidite ---
    hacim_24s_usd: float = 0.0

    # --- 1 dakikalık bağlam ---
    dakika_kapanis: deque = field(default_factory=lambda: deque(maxlen=90))
    dakika_hacim: deque = field(default_factory=lambda: deque(maxlen=90))
    baglam_ret: float = 0.0
    baglam_vratio: float = 0.0
    baglam_vratio3: float = 0.0
    baglam_hazir: bool = False

    # --- durum ---
    son_sinyal_ts: int = 0
    max_rvol: float = 0.0
    max_ret: float = 0.0


# ---------------------------------------------------------------------------
class SpikeDetector:
    """
    Her tikte çalışır. Fiyat ve hacim ayrı kanallardan gelir; hangisi
    güncellenirse güncellensin ikisi de tazeyse değerlendirilir.
    """

    def __init__(
        self,
        *,
        ret_pencere_ms: int = 2000,
        ret_min_pct: float = 0.35,
        rvol_min: float = 2.0,
        min_hacim_usd: float = 1_000.0,
        kisa_ms: int = 10_000,
        uzun_ms: int = 120_000,
        soguma_ms: int = 30_000,
        tazelik_ms: int = 8_000,
        min_hacim_24s_usd: float = 0.0,
        isinma_ms: int = 30_000,
        # ---- 1 dakikalık bağlam filtresi (geçmişte doğrulanmış katman) ----
        baglam_aktif: bool = True,
        baglam_geri_dk: int = 3,
        baglam_min_ret: float = 1.2,
        baglam_maks_ret: float = 2.0,
        baglam_min_vratio: float = 1.0,
        baglam_min_vratio3: float = 10.0,
        baglam_onbellek_dk: int = 35,
        baglam_ayni_yon: bool = False,
        # ---- PİYASA GENİŞLİĞİ (breadth) ----
        min_genislik_oran: float = 0.0,   # 0 = kapalı; 0.45 = sembollerin %45'i
    ) -> None:
        self.ret_pencere_ms = ret_pencere_ms
        self.ret_min = ret_min_pct
        self.rvol_min = rvol_min
        self.min_hacim_usd = min_hacim_usd
        self.kisa_ms = kisa_ms
        self.uzun_ms = uzun_ms
        self.soguma_ms = soguma_ms
        self.tazelik_ms = tazelik_ms
        self.min_hacim_24s_usd = min_hacim_24s_usd
        self.isinma_ms = isinma_ms
        self.baglam_aktif = baglam_aktif
        self.baglam_geri_dk = baglam_geri_dk
        self.baglam_min_ret = baglam_min_ret
        self.baglam_maks_ret = baglam_maks_ret
        self.baglam_min_vratio = baglam_min_vratio
        self.baglam_min_vratio3 = baglam_min_vratio3
        self.baglam_onbellek_dk = baglam_onbellek_dk
        self.baglam_ayni_yon = baglam_ayni_yon
        self.min_genislik_oran = min_genislik_oran
        self.genislik = 0            # |3dk hareket| >= esik olan sembol sayısı
        self.genislik_oran = 0.0     # aynı sayının izlenen sembollere oranı
        self._genislik_esik_pct = 0.5
        self.durumlar: dict[tuple[str, str], SembolDurum] = {}

    def durum(self, exchange: str, symbol: str) -> SembolDurum:
        key = (exchange, symbol)
        d = self.durumlar.get(key)
        if d is None:
            d = SembolDurum(exchange=exchange, symbol=symbol)
            self.durumlar[key] = d
        return d

    # -- hacim yardımcıları ------------------------------------------------
    @staticmethod
    def _geri(d: SembolDurum, simdi: int, geri_ms: int):
        """Simdi'den geri_ms önceki (ts, kümülatif_hacim); yoksa None."""
        esik = simdi - geri_ms
        for ts, qv in d.hacimler:
            if ts >= esik:
                return (ts, qv)
        return None

    def _hacim_guncelle(self, d: SembolDurum, qv_dakika: float, dakika_id: int, ts: int) -> None:
        if dakika_id == d.dakika_id:
            d.dakika_qv = max(d.dakika_qv, qv_dakika)
        elif dakika_id > d.dakika_id:
            if d.dakika_id >= 0:
                d.tamamlanan_qv += d.dakika_qv
                # KAPANAN dakikayı bağlam filtresi için sakla.
                d.dakika_hacim.append((d.dakika_id, d.dakika_qv))
                if d.son_fiyat > 0:
                    d.dakika_kapanis.append((d.dakika_id, d.son_fiyat))
            d.dakika_id = dakika_id
            d.dakika_qv = qv_dakika
        else:
            return                                  # eski dakika — yok say
        d.hacimler.append((ts, d.tamamlanan_qv + d.dakika_qv))

    def baglam_guncelle(self, d: SembolDurum, simdi: int) -> bool:
        """
        1 dakikalık bağlam: 3 dk getiri + hacim oranları.

        NEDEN: canlı dedektörün 2 saniyelik penceresi geçmişte test edilemez
        (2 sn'lik veri yok). 111.303 olaylık tarihsel çalışma, 3 dakikalık
        hareket + hacim filtresinin kenarlı olduğunu gösterdi. Bu katman
        doğrulanmış filtreyi canlıya taşır.

        İKİ FARKLI ORAN:
          baglam_vratio  — cari (yarım) dakikanın tam dakikaya ölçeklenmiş oranı
          baglam_vratio3 — son 3 TAM dakika / önceki 30 dakikanın medyanı
        Tek-dakika oranı bir sıçramanın büyüklüğünü 3 katına kadar şişirir;
        geri testteki eşikler yalnızca vratio3 ile karşılaştırılabilir.
        """
        d.baglam_hazir = False
        gecmis = list(d.dakika_kapanis)
        hacimler = list(d.dakika_hacim)
        if len(gecmis) < self.baglam_geri_dk + 1:
            return False
        if len(hacimler) < self.baglam_onbellek_dk:
            return False

        gecmis_kapanis = gecmis[-self.baglam_geri_dk][1]
        if gecmis_kapanis <= 0 or d.son_fiyat <= 0:
            return False
        d.baglam_ret = (d.son_fiyat - gecmis_kapanis) / gecmis_kapanis * 100.0

        med = statistics.median(q for _, q in hacimler[-self.baglam_onbellek_dk:])
        if med <= 0:
            return False
        gecen_dk = (simdi - d.dakika_id * 60_000) / 60_000.0
        gecen_dk = min(max(gecen_dk, 1.0 / 6.0), 1.0)     # 10 sn – 60 sn
        d.baglam_vratio = (d.dakika_qv / gecen_dk) / med

        if len(hacimler) >= 3 + self.baglam_onbellek_dk:
            son3 = sum(q for _, q in hacimler[-3:])
            gecmis3 = [q for _, q in hacimler[-(3 + self.baglam_onbellek_dk):-3]]
            med3 = statistics.median(gecmis3)
            if med3 > 0:
                d.baglam_vratio3 = son3 / (med3 * 3.0)

        d.baglam_hazir = True
        return True

    def _oranlari_hesapla(self, d: SembolDurum, simdi: int) -> bool:
        if not d.hacimler:
            return False
        son_qv = d.hacimler[-1][1]
        ilk_ts = d.hacimler[0][0]
        kisa_bas = self._geri(d, simdi, self.kisa_ms)
        uzun_bas = self._geri(d, simdi, self.uzun_ms)
        if kisa_bas is None or uzun_bas is None:
            return False
        kisa = son_qv - kisa_bas[1]
        uzun = son_qv - uzun_bas[1]
        if kisa < 0 or uzun < 0:
            return False

        # ÖNEMLİ: nominal pencereye değil GERÇEK geçen süreye böl.
        # Aksi hâlde açılışta elde 10 sn veri varken 120 sn'ye bölünür ve
        # rvol yapay olarak ~12 kat şişer.
        kisa_dt = (simdi - kisa_bas[0]) / 1000.0
        uzun_dt = (simdi - uzun_bas[0]) / 1000.0
        if kisa_dt < self.kisa_ms / 1000.0 * 0.8:
            return False
        if uzun_dt < self.isinma_ms / 1000.0:
            return False

        d.hiz_kisa = kisa / kisa_dt
        d.hiz_uzun = uzun / uzun_dt
        d.rvol = (d.hiz_kisa / d.hiz_uzun) if d.hiz_uzun > 1e-9 else 0.0
        return True

    def genislik_guncelle(self) -> float:
        """
        PİYASA GENİŞLİĞİ: aynı anda kaç sembol |3 dakikalık getiri| >= %0,5?

        7 gün kanıtı (289 sembol, 1.593 sıkı sinyal, TP2/SL3/5dk, ücret dahil):
            genişlik   0-9   211 sinyal  %45,0 isabet  -0,066%
            genişlik  10-19  551 sinyal  %49,7 isabet  -0,037%
            genişlik  20-39  230 sinyal  %50,0 isabet  -0,182%
            genişlik  40-79   44 sinyal  %59,1 isabet  +0,002%
            genişlik 80-139   50 sinyal  %58,0 isabet  +0,013%
            genişlik  140+   507 sinyal  %86,0 isabet  +0,693%   <-- KENAR BURADA

        Yani piyasa geneli çökmedikçe fade'in kenarı YOK. Genişlik, tek tek
        sinyallerin toplamından daha keskin bir rejim göstergesi.

        Oran kullanılıyor (sayı değil) çünkü izlenen sembol sayısı borsaya
        göre değişiyor (OKX 289, Binance 523).
        """
        toplam = 0
        hareketli = 0
        for d in self.durumlar.values():
            if not d.baglam_hazir:
                continue
            toplam += 1
            if abs(d.baglam_ret) >= self._genislik_esik_pct:
                hareketli += 1
        self.genislik = hareketli
        self.genislik_oran = (hareketli / toplam) if toplam else 0.0
        return self.genislik_oran

    # -- ana girişler ------------------------------------------------------
    def besle_fiyat(self, exchange: str, symbol: str, fiyat: float,
                    hacim_24s_usd: float, ts_ms: int) -> Sinyal | None:
        if not (fiyat > 0):
            return None
        d = self.durum(exchange, symbol)
        d.son_fiyat = fiyat
        d.son_fiyat_ts = ts_ms
        d.tik_sayisi += 1
        if hacim_24s_usd > 0:
            d.hacim_24s_usd = hacim_24s_usd
        d.fiyatlar.append((ts_ms, fiyat))

        # 2 sn önceki fiyat
        esik = ts_ms - self.ret_pencere_ms
        eski = None
        for ts, f in d.fiyatlar:
            if ts >= esik:
                eski = (ts, f)
                break
        if eski is None:
            return None
        dt_ms = ts_ms - eski[0]
        if dt_ms < self.ret_pencere_ms * 0.5:
            return None
        d.ret_2s = (fiyat - eski[1]) / eski[1] * 100.0
        return self._degerlendir(d, ts_ms)

    def besle_hacim(self, exchange: str, symbol: str, qv_dakika: float,
                    dakika_id: int, ts_ms: int) -> Sinyal | None:
        d = self.durum(exchange, symbol)
        d.hacim_tik += 1
        d.son_hacim_ts = ts_ms
        self._hacim_guncelle(d, qv_dakika, dakika_id, ts_ms)
        if not self._oranlari_hesapla(d, ts_ms):
            return None
        return self._degerlendir(d, ts_ms)

    def besle_hacim_kumulatif(self, exchange: str, symbol: str,
                              kumulatif_usd: float, ts_ms: int):
        """
        Sürekli artan (monoton) kümülatif USD hacim besler.

        candle1m erişimi olmayan kaynaklar (ör. Binance REST) için kullanılır.

        ÖNEMLİ: sayacı GERÇEK dakika kimliğiyle dilimliyoruz. Eskiden
        dakika_id sabit 0'dı; dakika_hacim hiç dolmuyordu, dolayısıyla
        1 dakikalık bağlam filtresi Binance sembollerinde ASLA sağlanamıyor
        ve Binance tarafı tamamen ölü kalıyordu.
        """
        d = self.durum(exchange, symbol)
        d.hacim_tik += 1
        d.son_hacim_ts = ts_ms

        dk = ts_ms // 60_000
        onceki = getattr(d, "_kum_onceki", None)
        delta = 0.0 if (onceki is None or kumulatif_usd < onceki) else (kumulatif_usd - onceki)
        d._kum_onceki = kumulatif_usd
        if dk != getattr(d, "_kum_dk", None):
            d._kum_dk = dk
            d._kum_birikim = 0.0
        d._kum_birikim = getattr(d, "_kum_birikim", 0.0) + delta

        self._hacim_guncelle(d, d._kum_birikim, dk, ts_ms)
        if not self._oranlari_hesapla(d, ts_ms):
            return None
        return self._degerlendir(d, ts_ms)

    # -- ortak değerlendirme ----------------------------------------------
    def _degerlendir(self, d: SembolDurum, ts_ms: int) -> Sinyal | None:
        # iki akış da taze olmalı
        if ts_ms - d.son_fiyat_ts > self.tazelik_ms:
            return None
        if d.son_hacim_ts and ts_ms - d.son_hacim_ts > self.tazelik_ms:
            return None
        if not d.hiz_uzun:
            return None

        ret = d.ret_2s
        rvol = d.rvol
        hacim_kisa = d.hiz_kisa * (self.kisa_ms / 1000.0)

        d.max_rvol = max(d.max_rvol, rvol)
        d.max_ret = max(d.max_ret, abs(ret))

        if abs(ret) < self.ret_min:
            return None
        if rvol < self.rvol_min:
            return None
        if hacim_kisa < self.min_hacim_usd:
            return None
        if self.min_hacim_24s_usd and d.hacim_24s_usd < self.min_hacim_24s_usd:
            return None
        if ts_ms - d.son_sinyal_ts < self.soguma_ms:
            return None

        # ---- AŞAMA 2: 1 dakikalık bağlam (geçmişte doğrulanmış katman) ----
        yon_isaret = 1.0 if ret > 0 else -1.0
        if self.baglam_aktif:
            if not self.baglam_guncelle(d, ts_ms):
                return None                      # ısınma / veri eksik
            b_ret = d.baglam_ret
            if abs(b_ret) < self.baglam_min_ret:
                return None
            if self.baglam_maks_ret and abs(b_ret) > self.baglam_maks_ret:
                return None                      # gerçek momentum — fade edilmez
            if self.baglam_min_vratio and d.baglam_vratio < self.baglam_min_vratio:
                return None
            if self.baglam_min_vratio3 and d.baglam_vratio3 < self.baglam_min_vratio3:
                return None                      # geri testle birebir eşleşen eşik
            if self.baglam_ayni_yon and (b_ret > 0) != (yon_isaret > 0):
                return None                      # 2 sn'lik kıpırtı 3 dk ile çelişiyor
            if self.min_genislik_oran > 0 and self.genislik_oran < self.min_genislik_oran:
                return None                      # piyasa geneli sakin — fade edilmez
            # YÖN: doğrulanmış çalışmada yön 3 dakikalık getiriden alınır
            yon_isaret = 1.0 if b_ret > 0 else -1.0

        d.son_sinyal_ts = ts_ms
        # SÖZLEŞME: dedektör PİYASANIN gittiği yönü döndürür. Strateji katmanı
        # (ws_bot.sinyal) fade için tersini alır. Burada çevirme YAPILMAZ.
        return Sinyal(
            ts_ms=ts_ms,
            exchange=d.exchange,
            symbol=d.symbol,
            yon="LONG" if yon_isaret > 0 else "SHORT",
            etiket="ANI_YUKSELIS" if yon_isaret > 0 else "ANI_DUSUS",
            fiyat=d.son_fiyat,
            ret_pct=round(ret, 3),
            rvol=round(rvol, 2),
            hacim_usd=round(hacim_kisa, 0),
            gecen_ms=self.ret_pencere_ms,
            baglam_ret=round(d.baglam_ret, 3),
            baglam_vratio=round(d.baglam_vratio, 2),
            baglam_vratio3=round(d.baglam_vratio3, 2),
        )

    # -- temizlik / özet ---------------------------------------------------
    def temizle(self, simdi_ms: int) -> int:
        olu = [k for k, d in self.durumlar.items() if simdi_ms - d.son_fiyat_ts > 600_000]
        for k in olu:
            del self.durumlar[k]
        return len(olu)

    def ozet(self) -> dict:
        return {
            "sembol": len(self.durumlar),
            "tik": sum(d.tik_sayisi for d in self.durumlar.values()),
            "hacim_hazir": sum(1 for d in self.durumlar.values() if d.hiz_uzun > 0),
        }


# ---------------------------------------------------------------------------
# OKX enstrüman sınıfları (instCategory alanı):
#   "1" = kripto   ·   "3" = hisse senedi tokeni   ·   "4" = emtia (XAU, CL, NG...)
KRIPTO = ("1",)
HISSE = ("3",)
EMTIA = ("4",)


async def okx_enstrumanlari(
    session: aiohttp.ClientSession,
    kategoriler: tuple[str, ...] = KRIPTO,
) -> tuple[list[str], set[str]]:
    """
    USDT-SWAP enstrümanları + spot paritelerin baz adları.

    Varsayılan olarak YALNIZCA kripto (instCategory="1") döner. Hisse tokeni
    (AAPL, SOXL...) ve emtia (XAU, CL...) 7/24 kripto likiditesine sahip
    değildir; ABD seansı dışında bayat kotasyon üretir ve tek bir makro
    hareketle topluca tetiklenir. Bu yüzden varsayılan evren dışındadır.
    """
    async with session.get(OKX_INSTR, timeout=aiohttp.ClientTimeout(total=25)) as r:
        govde = await r.json()
    swap = [i["instId"] for i in govde.get("data", [])
            if i.get("settleCcy") == "USDT"
            and i.get("state") == "live"
            and str(i.get("instCategory", "")) in kategoriler]

    bazlar: set[str] = set()
    try:
        async with session.get(OKX_SPOT, timeout=aiohttp.ClientTimeout(total=25)) as r:
            govde = await r.json()
        for i in govde.get("data", []):
            inst = i.get("instId", "")
            if inst.endswith("-USDT"):
                bazlar.add(inst[:-5])
    except Exception as exc:                      # noqa: BLE001
        log.warning("spot pariteleri alınamadı: %s", exc)
    return swap, bazlar


# ---------------------------------------------------------------------------
class _AkisTemel:
    """Ortak: bağlantı kur, abone ol, koparsa yeniden bağlan, mesajı işle."""

    def __init__(self, detektor: SpikeDetector,
                 sinyal_cb: Callable[[Sinyal], Awaitable[None]],
                 fiyat_cb: Callable[[str, str, float, int], None] | None = None):
        self.detektor = detektor
        self.sinyal_cb = sinyal_cb
        self.fiyat_cb = fiyat_cb      # canlı fiyat → açık pozisyonların mark'ı
        self.baglanti_sayisi = 0
        self.mesaj_sayisi = 0

    async def _baglanti(self, oturum, url: str, kanal: str, semboller: list[str], no: int) -> None:
        while True:
            try:
                async with oturum.ws_connect(url, heartbeat=20, max_msg_size=16 << 20) as ws:
                    self.baglanti_sayisi += 1
                    log.info("%s #%d bağlandı (%d enstrüman)", kanal, no, len(semboller))
                    await self._abone(ws, kanal, semboller)
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            continue
                        await self._isle(msg.data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:                                  # noqa: BLE001
                log.warning("%s #%d koptu: %s — 2 sn sonra tekrar", kanal, no, exc)
            await asyncio.sleep(2)

    async def _abone(self, ws, kanal: str, semboller: list[str]) -> None:
        for i in range(0, len(semboller), OKX_SUB_PER_REQUEST):
            parti = semboller[i:i + OKX_SUB_PER_REQUEST]
            await ws.send_json({
                "op": "subscribe",
                "args": [{"channel": kanal, "instId": s} for s in parti],
            })
            await asyncio.sleep(0.12)

    async def _isle(self, ham: str) -> None:      # pragma: no cover - alt sınıf
        raise NotImplementedError


class OKXAkisi(_AkisTemel):
    """OKX public WebSocket — tickers (fiyat) + business candle1m (hacim)."""

    def __init__(self, detektor, semboller, sinyal_cb, fiyat_cb=None):
        super().__init__(detektor, sinyal_cb, fiyat_cb)
        self.semboller = semboller

    async def calistir(self, oturum: aiohttp.ClientSession) -> None:
        partiler = [self.semboller[i:i + OKX_MAX_PER_CONN]
                    for i in range(0, len(self.semboller), OKX_MAX_PER_CONN)]
        gorevler = []
        for i, p in enumerate(partiler):
            gorevler.append(self._baglanti(oturum, OKX_PUBLIC, "tickers", p, i))
            gorevler.append(self._baglanti(oturum, OKX_BUSINESS, "candle1m", p, i))
        await asyncio.gather(*gorevler)

    async def _isle(self, ham: str) -> None:
        if '"event"' in ham and '"data"' not in ham:
            return
        try:
            paket = json.loads(ham)
        except json.JSONDecodeError:
            return
        data = paket.get("data")
        if not data:
            return
        kanal = paket.get("arg", {}).get("channel")

        if kanal == "tickers":
            for satir in data:
                self.mesaj_sayisi += 1
                try:
                    sembol = satir["instId"]
                    fiyat = float(satir["last"])
                    ts = int(satir["ts"])
                    hacim_coin = float(satir.get("volCcy24h") or 0.0)
                except (KeyError, TypeError, ValueError):
                    continue
                if self.fiyat_cb is not None:
                    self.fiyat_cb("okx", sembol, fiyat, ts)
                s = self.detektor.besle_fiyat("okx", sembol, fiyat, hacim_coin * fiyat, ts)
                if s:
                    await self.sinyal_cb(s)

        elif kanal == "candle1m":
            for satir in data:
                self.mesaj_sayisi += 1
                try:
                    sembol = paket["arg"]["instId"]
                    mum_ts = int(satir[0])
                    qv = float(satir[7])            # volCcyQuote = USD hacim
                except (KeyError, TypeError, ValueError, IndexError):
                    continue
                s = self.detektor.besle_hacim("okx", sembol, qv, mum_ts // 60000, int(time.time() * 1000))
                if s:
                    await self.sinyal_cb(s)


# ---------------------------------------------------------------------------
class BinanceAkisi(_AkisTemel):
    """
    Binance USDⓈ-M — tek akışta tüm semboller (!ticker@arr).
    NOT: Binance bu ortamda 451 döner; kod hazır, engelsiz IP'de çalışır.
    """

    def __init__(self, detektor, sinyal_cb, fiyat_cb=None):
        super().__init__(detektor, sinyal_cb, fiyat_cb)
        self.aktif = False
        self.hata: str | None = None

    async def calistir(self, oturum: aiohttp.ClientSession) -> None:
        while True:
            try:
                async with oturum.ws_connect(BINANCE_WS, heartbeat=20, max_msg_size=16 << 20) as ws:
                    self.hata = None
                    log.info("binance ws açıldı — veri bekleniyor")
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            continue
                        await self._isle(msg.data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:                                  # noqa: BLE001
                self.aktif = False
                self.hata = str(exc)[:120]
                log.warning("binance ws koptu/engelli: %s — 10 sn sonra tekrar", self.hata)
            await asyncio.sleep(10)

    async def _isle(self, ham: str) -> None:
        try:
            liste = json.loads(ham)
        except json.JSONDecodeError:
            return
        if not isinstance(liste, list):
            return
        for satir in liste:
            sembol = satir.get("s", "")
            if not sembol.endswith("USDT"):
                continue
            try:
                fiyat = float(satir["c"])
                hacim_usd = float(satir["q"])           # quoteVolume = USD
                ts = int(satir["E"])
            except (KeyError, TypeError, ValueError):
                continue
            self.mesaj_sayisi += 1
            self.aktif = True          # ancak gerçek veri gelince "bağlı"
            if self.fiyat_cb is not None:
                self.fiyat_cb("binance", sembol, fiyat, ts)
            s = self.detektor.besle_fiyat("binance", sembol, fiyat, hacim_usd, ts)
            if s:
                await self.sinyal_cb(s)


# ---------------------------------------------------------------------------
class BinanceRestAkisi:
    """
    Binance USD-S-M - REST akisi.

    NEDEN REST: Binance WebSocket'i bu ortamda hicbir yoldan acilmiyor
    (fstream/stream.binance.com -> 451, www.binance.com/ws -> 202 WAF sayfasi).
    Ancak REST `www.binance.com/fapi/v1/*` uzerinden tam calisiyor.

    VERI KAYNAKLARI
        /fapi/v1/ticker/price   -> tum sembollerin son fiyati (agirlik ~2)
        /fapi/v1/ticker/24hr    -> 24s quoteVolume, count, lastId (agirlik ~40)

    HACIM: 24s quoteVolume KAYAN sayactir, deltasi negatif cikabilir.
    Bunun yerine lastId kullanilir - sembol basina MONOTON artan islem kimligi.
        islem basina ortalama USD = quoteVolume / count
        kumulatif USD tahmini     = lastId * (quoteVolume / count)
    Bu deger monotondur ve gercek islem hacmini yakindan izler.

    COZUNURLUK: fiyat ~600 ms, hacim ~3 sn.
    """

    # Birden fazla uc nokta denenir; ilk calisan secilir.
    # Engel olmayan sunucularda fapi.binance.com (kanonik, en hizli),
    # bolgesel engel varsa www.binance.com devreye girer.
    ADAY_TABANLAR = (
        "https://fapi.binance.com/fapi/v1",
        "https://fapi1.binance.com/fapi/v1",
        "https://www.binance.com/fapi/v1",
    )
    BASE = ADAY_TABANLAR[0]
    # AĞIRLIK BÜTÇESİ (Binance ~1200/dk):
    #   ticker/price ağırlık 2  × 60/dk = 120
    #   ticker/24hr  ağırlık 40 ×  6/dk = 240
    #   toplam ~360/dk = bütçenin %30'u
    # Eski 0,6 sn + 3 sn kombinasyonu TEK botta 1000/dk (%83) yiyordu → IP banı.
    FIYAT_ARALIK = 0.5      # 28.10: 1,0 -> 0,5 sn (ağırlık 240/dk = bütçenin %20'si)
    HACIM_ARALIK = 10.0     # 10 sn'de 1 hacim turu

    def __init__(self, detektor, sinyal_cb, fiyat_cb=None):
        self.detektor = detektor
        self.sinyal_cb = sinyal_cb
        self.fiyat_cb = fiyat_cb
        self.aktif = False
        self.hata: str | None = None
        self.mesaj_sayisi = 0
        self.semboller: set[str] = set()
        self._son_fiyat: dict[str, float] = {}

    @staticmethod
    def _liste_dogrula(govde, ne: str) -> list:
        """
        Binance ban/limit yediğinde JSON bir NESNE döner:
            {"code":-1003,"msg":"Way too many requests; IP ... banned until ..."}
        Eskiden bu doğrudan döngüye giriyor ve her turda
        "'str' object has no attribute 'get'" hatası basıyordu — gerçek neden
        (IP banı) görünmüyordu. Şimdi açık hata fırlatılır; çağıran taraf
        üstel geri çekilme uygular.
        """
        if isinstance(govde, list):
            return govde
        kod = govde.get("code") if isinstance(govde, dict) else "?"
        mesaj = govde.get("msg") if isinstance(govde, dict) else str(govde)[:120]
        raise RuntimeError(f"{ne}: yanıt liste değil (kod={kod}) {str(mesaj)[:120]}")

    async def _taban_sec(self, oturum: aiohttp.ClientSession) -> str:
        """Calisan ilk Binance REST tabanini dener ve secer."""
        ortam = os.environ.get("BINANCE_BASE")
        if ortam:
            self.BASE = ortam.rstrip("/")
            log.info("binance REST tabani (BINANCE_BASE): %s", self.BASE)
            return self.BASE
        for aday in self.ADAY_TABANLAR:
            try:
                async with oturum.get(f"{aday}/ping",
                                      timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        self.BASE = aday
                        log.info("binance REST tabani secildi: %s", aday)
                        return aday
            except Exception:                                  # noqa: BLE001
                continue
        log.warning("binance REST: hicbir uc nokta yanit vermedi")
        return self.BASE

    def _hata_bildir(self, ne: str, mesaj: str) -> None:
        """Aynı hatayı 10 kez/sn basmak yerine: 1. seferde, sonra 1 dk'da bir."""
        simdi = time.time()
        if mesaj != getattr(self, "_son_hata", None) or simdi - getattr(self, "_son_hata_ts", 0) > 60:
            log.warning("binance REST %s hatasi: %s", ne, mesaj)
            self._son_hata = mesaj
            self._son_hata_ts = simdi
        self._hata_sayaci = getattr(self, "_hata_sayaci", 0) + 1

    def _ceza_bekle(self) -> float:
        """
        Hata durumunda geri çekilme.

        28.10 DÜZELTME: eski sürüm HER hatayı ban sayıp 2→4→8→16→32→60 sn
        bekliyordu. Oysa canlıda görülen hata "Connection reset by peer" —
        geçici bir TCP kopması, IP banı DEĞİL. 60 sn beklemek Binance'i
        botun gözünden 1 dakika boyunca tamamen düşürüyordu (ws_durum.json:
        binance.aktif=false, sembol 523 ama tik yok).
        Artık hata sınıfına göre bekleniyor:
            bağlantı kopması / zaman aşımı -> 1,5 sn (hemen tekrar dene)
            HTTP 418/429/ban (kod -1003)   -> üstel 2→60 sn (banı uzatma)
        """
        son = getattr(self, "_son_hata", "") or ""
        gecici = any(x in son.lower() for x in (
            "reset", "timeout", "cannot connect", "disconnected",
            "server disconnected", "connection", "clientconnector", "eof"))
        if gecici:
            return 1.5
        n = min(getattr(self, "_hata_sayaci", 1), 6)
        return min(2.0 ** n, 60.0)

    def _taban_dondur(self) -> None:
        """Kopan tabanı bırak, sıradaki adaya geç (kalıcı kopmada kurtarır)."""
        try:
            i = self.ADAY_TABANLAR.index(self.BASE)
        except ValueError:
            i = 0
        yeni = self.ADAY_TABANLAR[(i + 1) % len(self.ADAY_TABANLAR)]
        if yeni != self.BASE:
            log.warning("binance REST taban degistiriliyor: %s -> %s", self.BASE, yeni)
            self.BASE = yeni

    async def sembolleri_yukle(self, oturum: aiohttp.ClientSession) -> int:
        async with oturum.get(f"{self.BASE}/exchangeInfo",
                              timeout=aiohttp.ClientTimeout(total=25)) as r:
            govde = await r.json()
        if not isinstance(govde, dict):
            raise RuntimeError(f"exchangeInfo: beklenmeyen yanıt ({type(govde).__name__})")
        self.semboller = {
            x["symbol"] for x in govde.get("symbols", [])
            if x.get("contractType") == "PERPETUAL"
            and x.get("quoteAsset") == "USDT"
            and x.get("status") == "TRADING"
        }
        return len(self.semboller)

    async def calistir(self, oturum: aiohttp.ClientSession) -> None:
        await self._taban_sec(oturum)
        n = await self.sembolleri_yukle(oturum)
        log.info("binance REST - %d USDT surekli vade sembolu", n)
        await asyncio.gather(
            self._fiyat_dongusu(oturum),
            self._hacim_dongusu(oturum),
        )

    # -- fiyat: 600 ms ------------------------------------------------------
    async def _fiyat_dongusu(self, oturum) -> None:
        while True:
            t0 = time.time()
            try:
                async with oturum.get(f"{self.BASE}/ticker/price",
                                      timeout=aiohttp.ClientTimeout(total=6)) as r:
                    liste = await r.json()
                liste = self._liste_dogrula(liste, "ticker/price")
                ts = int(time.time() * 1000)
                sayi = 0
                for satir in liste:
                    sembol = satir.get("symbol", "")
                    if sembol not in self.semboller:
                        continue
                    try:
                        fiyat = float(satir["price"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    self._son_fiyat[sembol] = fiyat
                    self.mesaj_sayisi += 1
                    sayi += 1
                    if self.fiyat_cb is not None:
                        self.fiyat_cb("binance", sembol, fiyat, ts)
                    s = self.detektor.besle_fiyat("binance", sembol, fiyat, 0.0, ts)
                    if s:
                        await self.sinyal_cb(s)
                self.aktif = True
                self.hata = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:                              # noqa: BLE001
                self.aktif = False
                self.hata = str(exc)[:110]
                self._hata_bildir("fiyat", self.hata)
                self._arka_arka = getattr(self, "_arka_arka", 0) + 1
                if self._arka_arka % 3 == 0:      # 3 kopmada tabanı değiştir
                    self._taban_dondur()
                bekle = self._ceza_bekle()
            else:
                self._hata_sayaci = 0
                self._arka_arka = 0
                bekle = self.FIYAT_ARALIK - (time.time() - t0)
            await asyncio.sleep(max(0.05, bekle))

    # -- hacim / aktivite: 3 sn --------------------------------------------
    async def _hacim_dongusu(self, oturum) -> None:
        while True:
            t0 = time.time()
            try:
                async with oturum.get(f"{self.BASE}/ticker/24hr",
                                      timeout=aiohttp.ClientTimeout(total=15)) as r:
                    liste = await r.json()
                liste = self._liste_dogrula(liste, "ticker/24hr")
                ts = int(time.time() * 1000)
                for satir in liste:
                    sembol = satir.get("symbol", "")
                    if sembol not in self.semboller:
                        continue
                    try:
                        qv = float(satir["quoteVolume"])
                        adet = float(satir["count"])
                        son_id = float(satir["lastId"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if adet <= 0 or son_id <= 0:
                        continue
                    # islem basina ortalama USD x monoton islem sayaci
                    kumulatif_usd = son_id * (qv / adet)
                    self.mesaj_sayisi += 1
                    s = self.detektor.besle_hacim_kumulatif("binance", sembol, kumulatif_usd, ts)
                    if s:
                        await self.sinyal_cb(s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:                              # noqa: BLE001
                self.hata = str(exc)[:110]
                self._hata_bildir("hacim", self.hata)
                bekle = self._ceza_bekle()
            else:
                self._hata_sayaci = 0
                bekle = self.HACIM_ARALIK - (time.time() - t0)
            await asyncio.sleep(max(0.2, bekle))


# ----------------------------------------------------------------------
# Açılışta dakika geçmişini REST'ten doldur
# ----------------------------------------------------------------------
async def okx_dakika_onbellegi(oturum, detektor, semboller, adet: int = 35,
                               es_zamanli: int = 6) -> int:
    """
    1 dakikalık bağlam filtresi 33 tamamlanmış dakika ister. Bu olmadan bot
    açılıştan sonra ~33 dakika HİÇ sinyal üretmez. Son `adet` dakikayı REST'ten
    çekip dolduruyoruz; bot açılır açılmaz filtre çalışır.

    Dönen değer: başarıyla doldurulan sembol sayısı.
    """
    kilit = asyncio.Semaphore(es_zamanli)

    async def bir(sym: str) -> bool:
        try:
            async with kilit:
                async with oturum.get(
                        "https://www.okx.com/api/v5/market/candles",
                        params={"instId": sym, "bar": "1m", "limit": str(adet)},
                        timeout=aiohttp.ClientTimeout(total=15)) as r:
                    govde = await r.json()
                await asyncio.sleep(0.055)          # ~1200 istek/dk tavanı
        except Exception:
            return False
        satirlar = govde.get("data") if isinstance(govde, dict) else None
        if not satirlar:
            return False
        d = detektor.durum("okx", sym)
        try:
            for k in sorted(satirlar, key=lambda z: int(z[0])):
                mid = int(k[0]) // 60_000
                kap = float(k[4])
                qv = float(k[7])
                if k[8] == "1":                    # TAMAMLANMIŞ dakika
                    d.dakika_kapanis.append((mid, kap))
                    d.dakika_hacim.append((mid, qv))
                d.dakika_id = max(d.dakika_id, mid)
                if kap > 0:
                    d.son_fiyat = kap
            return True
        except (ValueError, IndexError, TypeError):
            return False

    sonuc = await asyncio.gather(*(bir(x) for x in semboller))
    # İlk turda dolmayanları BİR kez daha dene (hız sınırı / geçici hata)
    eksik = [s for s, ok in zip(semboller, sonuc) if not ok]
    if eksik:
        await asyncio.sleep(1.0)
        ikinci = await asyncio.gather(*(bir(x) for x in eksik))
        for s_, ok in zip(eksik, ikinci):
            if ok:
                sonuc[semboller.index(s_)] = True
    return sum(1 for q in sonuc if q)
