# -*- coding: utf-8 -*-
"""botlar.py — üç bot sürümü, tek dosyada.

v1 (MotorV1)  : EMA9/21 kesişimi + hacim onayı. Basit referans.
v2 (MotorV2)  : repodaki v8/v9 mantığının bar karşılığı — rejim (sıkışma/trend/panik),
                hacim kırılımı, VWAP dönüş, RSI tükeniş, soğuma.
v3 (MotorV3)  : kanıta dayalı eşikler (gerçek paper işlemlerinden ölçülmüş):
                ADX >= 30 · BB genişliği >= %0,50 · |RSI-50| >= 12 (yön lehine)
                6 bileşen uyumu >= 5 · karşıt bileşen <= 1 · giriş açısı (EMA9'a <= 1,2 ATR)
                çıkış: -10 $ sert stop + tepe kârın %50'si kâr kilidi + süre + soğuma.

Ortak kurallar (değişmez): kasa 1.000 $ · teminat 50 $ · kaldıraç 10x (500 $ notional) ·
CROSS · pozisyon limiti yok · pozisyon başına net -10 $ stop.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


# ------------------------------------------------------------------ ortak
@dataclass
class Taban:
    kasa_usd: float = 1000.0
    teminat_usd: float = 50.0
    kaldirac: float = 10.0
    stop_net_usd: float = -10.0
    komisyon_oran: float = 0.0005
    soguma_bar: int = 5
    azami_bar: int = 240
    azami_poz: int = 0                      # 0 = sınırsız

    @property
    def notional_usd(self) -> float:
        return self.teminat_usd * self.kaldirac

    @property
    def komisyon(self) -> float:
        return self.notional_usd * self.komisyon_oran * 2

    @property
    def stop_yuzde(self) -> float:
        return (abs(self.stop_net_usd) - self.komisyon) / self.notional_usd


def ema(d: list[float], n: int) -> float:
    if not d:
        return 0.0
    k = 2.0 / (n + 1.0)
    e = d[0]
    for x in d[1:]:
        e = x * k + e * (1 - k)
    return e


def atr(h: list[float], l: list[float], c: list[float], n: int = 14) -> float:
    if len(c) < 2:
        return 0.0
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
          for i in range(1, len(c))]
    return ema(tr[-n:], n)


def rsi(c: list[float], n: int = 14) -> float:
    if len(c) < n + 1:
        return 50.0
    f = [c[i] - c[i - 1] for i in range(1, len(c))]
    k = ema([max(0.0, x) for x in f][-n:], n)
    z = ema([max(0.0, -x) for x in f][-n:], n)
    return 100.0 if z == 0 else 100 - 100 / (1 + k / z)


def adx(h: list[float], l: list[float], c: list[float], n: int = 14) -> float:
    if len(c) < n + 2:
        return 0.0
    arti, eksi, tr = [], [], []
    for i in range(1, len(c)):
        yuk = h[i] - h[i - 1]
        asa = l[i - 1] - l[i]
        arti.append(yuk if (yuk > asa and yuk > 0) else 0.0)
        eksi.append(asa if (asa > yuk and asa > 0) else 0.0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    a = ema(tr[-n:], n)
    if a <= 0:
        return 0.0
    dp = 100 * ema(arti[-n:], n) / a
    dm = 100 * ema(eksi[-n:], n) / a
    return 100 * abs(dp - dm) / (dp + dm) if (dp + dm) else 0.0


def bb_gen(c: list[float], n: int = 20, k: float = 2.0) -> float:
    if len(c) < n:
        return 0.0
    d = c[-n:]
    o = sum(d) / n
    sd = math.sqrt(sum((x - o) ** 2 for x in d) / n)
    return (2 * k * sd) / o if o else 0.0


def vwap(h, l, c, v, n: int = 30) -> float:
    h, l, c, v = h[-n:], l[-n:], c[-n:], v[-n:]
    tv = sum(v)
    return (sum(((h[i] + l[i] + c[i]) / 3) * v[i] for i in range(len(c))) / tv) if tv else (
        c[-1] if c else 0.0)


def obv_egim(c: list[float], v: list[float], n: int = 20) -> float:
    if len(c) < 2:
        return 0.0
    toplam = 0.0
    for i in range(max(1, len(c) - n), len(c)):
        toplam += v[i] if c[i] > c[i - 1] else (-v[i] if c[i] < c[i - 1] else 0.0)
    return toplam


def supertrend_yon(h, l, c, n: int = 10) -> int:
    if len(c) < n + 2:
        return 0
    orta = (max(h[-n:]) + min(l[-n:])) / 2
    return 1 if c[-1] > orta else -1


def poc(c: list[float], v: list[float], n: int = 40) -> float:
    if len(c) < n:
        return c[-1] if c else 0.0
    kova: dict[float, float] = {}
    for f, hac in zip(c[-n:], v[-n:]):
        k = round(f, 4)
        kova[k] = kova.get(k, 0.0) + hac
    return max(kova, key=kova.get)


def rvol(v: list[float], n: int = 20) -> float:
    if len(v) < 2:
        return 1.0
    gecmis = v[-n - 1:-1] or v[:-1]
    ort = sum(gecmis) / max(1, len(gecmis))
    return v[-1] / ort if ort else 1.0


@dataclass
class Poz:
    yon: int
    giris: float
    miktar: float
    stop: float
    tepe: float
    bar: int
    atr: float = 0.0


class MotorTaban:
    """Ortak pozisyon/hesap defteri. Alt sınıflar `_karar` yazar."""

    def __init__(self, ayar: Taban):
        self.ayar = ayar
        self.c: dict[str, list[float]] = {}
        self.h: dict[str, list[float]] = {}
        self.l: dict[str, list[float]] = {}
        self.v: dict[str, list[float]] = {}
        self.pozlar: dict[str, Poz] = {}
        self.soguma: dict[str, int] = {}
        self.kapanan: list[float] = []
        self.neden: dict[str, int] = {}
        self.red: dict[str, int] = {}
        self.bar = 0

    # --- alt sınıf yazar
    def _karar(self, s: str, C, H, L, V) -> int:
        raise NotImplementedError

    # --- ortak
    def tick(self, s: str, o: float, hi: float, lo: float, cl: float, vo: float) -> None:
        self.bar += 1
        C = self.c.setdefault(s, [])
        H = self.h.setdefault(s, [])
        L = self.l.setdefault(s, [])
        V = self.v.setdefault(s, [])
        C.append(cl)
        H.append(hi)
        L.append(lo)
        V.append(vo)
        for d in (C, H, L, V):
            if len(d) > 400:
                del d[:-400]

        p = self.pozlar.get(s)
        if p is not None:
            p.bar += 1
            p.tepe = max(p.tepe, cl) if p.yon > 0 else min(p.tepe, cl)
            if (p.yon > 0 and lo <= p.stop) or (p.yon < 0 and hi >= p.stop):
                self._kapat(s, p.stop, "stop")
                return
            self._takip(p, cl)
            if p.bar >= self.ayar.azami_bar:
                self._kapat(s, cl, "sure")
                return

        if p is not None or self.soguma.get(s, 0) > self.bar:
            return
        if self.ayar.azami_poz and len(self.pozlar) >= self.ayar.azami_poz:
            self.red["tavan"] = self.red.get("tavan", 0) + 1
            return

        yon = self._karar(s, C, H, L, V)
        if yon == 0:
            return
        miktar = self.ayar.notional_usd / cl
        stop = (cl * (1 - self.ayar.stop_yuzde) if yon > 0
                else cl * (1 + self.ayar.stop_yuzde))
        self.pozlar[s] = Poz(yon, cl, miktar, stop, cl, 0, atr(H, L, C))

    # --- kancalar
    def _takip(self, p: Poz, cl: float) -> None:
        """v1/v2: sabit stop. v3 kâr kilidi uygular."""

    def _kapat(self, s: str, fiyat: float, neden: str) -> None:
        p = self.pozlar.pop(s)
        net = (fiyat - p.giris) * p.miktar * p.yon - self.ayar.komisyon
        if neden == "stop" and net > 0:
            neden = "izli_kar"
        self.kapanan.append(net)
        self.neden[neden] = self.neden.get(neden, 0) + 1
        self.soguma[s] = self.bar + self.ayar.soguma_bar

    def ozet(self) -> dict:
        n = len(self.kapanan)
        k = sum(1 for x in self.kapanan if x > 0)
        kar = sum(x for x in self.kapanan if x > 0)
        zar = abs(sum(x for x in self.kapanan if x < 0))
        return {
            "islem": n,
            "kazanma_orani": round(k / n, 4) if n else 0.0,
            "realize_usd": round(sum(self.kapanan), 2),
            "komisyon_usd": round(n * self.ayar.komisyon, 2),
            "kar_faktoru": round(kar / zar, 3) if zar else (99.0 if kar else 0.0),
            "ortalama_islem": round(sum(self.kapanan) / n, 2) if n else 0.0,
            "cikis_nedenleri": self.neden,
            "red_nedenleri": dict(sorted(self.red.items(), key=lambda t: -t[1])[:6]),
        }


# ------------------------------------------------------------------ v1
class MotorV1(MotorTaban):
    """EMA9/21 kesişimi + hacim onayı."""

    def _karar(self, s, C, H, L, V) -> int:
        if len(C) < 23:
            self.red["veri"] = self.red.get("veri", 0) + 1
            return 0
        hizli_now, yavas_now = ema(C, 9), ema(C, 21)
        hizli_prev, yavas_prev = ema(C[:-1], 9), ema(C[:-1], 21)
        hacim_ort = sum(V[-21:]) / 21
        if V[-1] < hacim_ort * 1.2:
            self.red["hacim"] = self.red.get("hacim", 0) + 1
            return 0
        if hizli_now > yavas_now and hizli_prev <= yavas_prev:
            return 1
        if hizli_now < yavas_now and hizli_prev >= yavas_prev:
            return -1
        self.red["kesisme_yok"] = self.red.get("kesisme_yok", 0) + 1
        return 0


# ------------------------------------------------------------------ v2
class MotorV2(MotorTaban):
    """Rejim + komite (v8/v9'un bar karşılığı)."""

    def _karar(self, s, C, H, L, V) -> int:
        if len(C) < 60:
            self.red["veri"] = self.red.get("veri", 0) + 1
            return 0
        a = atr(H, L, C)
        vm = vwap(H, L, C, V)
        if a <= 0 or not vm:
            return 0
        gen = bb_gen(C)
        tg = abs(ema(C, 9) - ema(C, 21)) / a
        gecmis = [bb_gen(C[:i]) for i in range(max(21, len(C) - 40), len(C) + 1)]
        ort = sum(gecmis) / len(gecmis) if gecmis else gen
        rv = rvol(V)
        fiyat = C[-1]
        r = rsi(C)
        rejim = ("panik" if gen > ort * 1.5 else
                 "sikisma" if gen < ort * 0.7 else
                 "trend" if tg > 0.8 else "notr")
        adaylar = []
        if rejim == "trend" and rv >= 1.5:
            yon = 1 if ema(C, 9) > ema(C, 21) else -1
            adaylar.append((yon, min(1.0, 0.5 + (rv - 1) * 0.05)))
        if rejim == "sikisma" and abs(fiyat - vm) > 0.5 * a:
            adaylar.append((-1 if fiyat > vm else 1, 0.6))
        if rejim == "panik" and abs(fiyat - vm) > 2.0 * a and (r > 75 or r < 25):
            adaylar.append((-1 if r > 75 else 1, 0.7))
        if not adaylar:
            self.red[rejim] = self.red.get(rejim, 0) + 1
            return 0
        adaylar.sort(key=lambda t: -t[1])
        yon, skor = adaylar[0]
        if skor < 0.55:
            return 0
        return yon


# ------------------------------------------------------------------ v3
class MotorV3(MotorTaban):
    """Kanıta dayalı eşikler + %50 kâr kilidi."""

    adx_esik: float = 30.0
    bb_esik: float = 0.005
    rsi_ayrim: float = 12.0
    min_uyum: int = 5
    azami_karsit: int = 1
    kar_kilit: float = 0.5
    giris_atr: float = 1.2

    def _karar(self, s, C, H, L, V) -> int:
        if len(C) < 60:
            self.red["veri"] = self.red.get("veri", 0) + 1
            return 0
        a = atr(H, L, C)
        fiyat = C[-1]
        ad = adx(H, L, C)
        gen = bb_gen(C)
        r = rsi(C)
        vm = vwap(H, L, C, V)
        pk = poc(C, V)
        e9, e21 = ema(C[-40:], 9), ema(C[-60:], 21)
        if ad < self.adx_esik:
            self.red["ADX"] = self.red.get("ADX", 0) + 1
            return 0
        if gen < self.bb_esik:
            self.red["BB"] = self.red.get("BB", 0) + 1
            return 0
        yon = 1 if e9 > e21 else -1
        if yon > 0 and r < 50 + self.rsi_ayrim:
            self.red["RSI"] = self.red.get("RSI", 0) + 1
            return 0
        if yon < 0 and r > 50 - self.rsi_ayrim:
            self.red["RSI"] = self.red.get("RSI", 0) + 1
            return 0
        bilesen = (
            e9 > e21 if yon > 0 else e9 < e21,
            supertrend_yon(H, L, C) == yon,
            (ema(C[-26:], 12) - ema(C[-26:], 26)) * yon > 0,
            fiyat > vm if yon > 0 else fiyat < vm,
            obv_egim(C, V) * yon > 0,
            fiyat > pk if yon > 0 else fiyat < pk,
        )
        uyum = sum(bilesen)
        if uyum < self.min_uyum or (6 - uyum) > self.azami_karsit:
            self.red["uyum"] = self.red.get("uyum", 0) + 1
            return 0
        if a and abs(fiyat - e9) / a > self.giris_atr:
            self.red["giris_acisi"] = self.red.get("giris_acisi", 0) + 1
            return 0
        return yon

    def _takip(self, p: Poz, cl: float) -> None:
        r1 = abs(p.giris * self.ayar.stop_yuzde)
        if p.yon > 0 and p.tepe >= p.giris + r1:
            p.stop = max(p.stop, p.giris + (p.tepe - p.giris) * self.kar_kilit)
        elif p.yon < 0 and p.tepe <= p.giris - r1:
            p.stop = min(p.stop, p.giris - (p.giris - p.tepe) * self.kar_kilit)


# ------------------------------------------------------------------ veri
def uret(sembol: str, adet: int, tohum: int = 42, trendli: bool = True):
    """Sentetik 5 sn bar: rejim değişimli rastgele yürüyüş."""
    toh = tohum + sum(ord(ch) * (i + 1) for i, ch in enumerate(sembol))
    r = random.Random(toh)
    fiyat = 100.0 * r.uniform(0.5, 3.0)
    drift, sayac = 0.0, 0
    seri = []
    for _ in range(adet):
        if sayac <= 0:
            drift = r.choice([-1.0, -0.5, 0.0, 0.5, 1.0]) * (0.00055 if trendli else 0.00004)
            sayac = r.randint(150, 700)
        sayac -= 1
        ac = fiyat
        fiyat *= 1.0 + drift + r.gauss(0, 0.0014)
        yuk = max(ac, fiyat) * (1 + abs(r.gauss(0, 0.0006)))
        alc = min(ac, fiyat) * (1 - abs(r.gauss(0, 0.0006)))
        seri.append((ac, yuk, alc, fiyat, r.uniform(0.5, 2.0) * (3.0 if r.random() < 0.02 else 1.0)))
    return seri
