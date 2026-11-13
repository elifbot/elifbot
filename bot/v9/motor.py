# -*- coding: utf-8 -*-
"""motor.py — v9 ORTAK AKIL: rejim kapılı sinyaller, portföy sıralaması.

v8'den farkı üç yerde:
  1. Giriş sıralıdır: adaylar skora göre sıralanır, serbest teminat kadar en iyiler girilir.
     "Sınırsız işlem" kuralı bozulmaz — sınır emir sayısı değil, kasadır.
  2. Rejim kapısı: sıkışmada dönüş, trendde kırılım sinyali çalışır.
  3. Rejim dönüşü çıkışı: pozisyon rejimle çelişip zarardaysa beklenmez.

Stop yine borsada duran reduceOnly emirdir; Python tick kontrolü değil.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bot.v8.broker import SimuleBorsa
from bot.v8.config import KasaKurallari
from bot.v8.sizing import boyut_hesapla
from bot.v8.types import EmirIstegi, EmirTipi, Tick, Yon

from .rejim import Hafiza, Rejim, rejim_sinifla
from .sinyaller import Aday, komite


@dataclass
class V9Ayarlari:
    min_skor: float = 0.58
    aday_omru_sn: float = 20.0
    flush_araligi_sn: float = 5.0
    be_esik_usd: float = 4.50
    trail_esik_usd: float = 8.00
    trail_oran: float = 0.70
    zombi_sn: float = 1200.0
    sogutma_sn: float = 90.0
    rejim_karsi_cikis_sn: float = 120.0
    kayma_tamponu: float = 0.0005


@dataclass
class Poz:
    sembol: str
    baz: str
    yon: Yon
    adet: float
    giris_fiyati: float
    notional_usd: float
    acilis_ts: float
    stop_fiyati: float
    stop_emir_id: str = ""
    en_iyi_pnl: float = 0.0
    komisyon_giris: float = 0.0
    skor: float = 0.0
    motor: str = ""


@dataclass
class Kapanan:
    sembol: str
    baz: str
    yon: Yon
    giris: float
    cikis: float
    net_usd: float
    ts: float
    acilis_ts: float
    neden: str
    motor: str


@dataclass
class MotorV9:
    borsa: SimuleBorsa
    kurallar: KasaKurallari = field(default_factory=KasaKurallari)
    ayar: V9Ayarlari = field(default_factory=V9Ayarlari)

    hafizalar: dict[str, Hafiza] = field(default_factory=dict)
    pozlar: dict[str, Poz] = field(default_factory=dict)
    kapananlar: list[Kapanan] = field(default_factory=list)
    adaylar: list[Aday] = field(default_factory=list)
    red: dict[str, int] = field(default_factory=dict)
    rejim_sayaci: dict[str, int] = field(default_factory=dict)
    son_flush: float = 0.0
    son_islem_ts: dict[str, float] = field(default_factory=dict)
    emir_sayaci: int = 0

    # ------------------------------------------------------------------ yardım
    def _red(self, neden: str) -> None:
        self.red[neden] = self.red.get(neden, 0) + 1

    def _enstruman(self, sembol: str):
        return self.borsa.enstrumanlar[sembol]

    # ------------------------------------------------------------------- tick
    def tick(self, t: Tick) -> None:
        sim = self.borsa
        sim.tick_islet(t.sembol, t.fiyat, getattr(t, "hacim24_usd", 0.0))
        for sembol in list(self.pozlar):
            if sembol not in sim.pozisyonlar:          # stop doldu → borsa kapattı
                self._kaydet(sembol, t.ts, "STOP")

        h = self.hafizalar.get(t.baz)
        if h is None:
            h = self.hafizalar[t.baz] = Hafiza(t.baz)
        h.ekle(t)
        r = rejim_sinifla(h)
        self.rejim_sayaci[r.rejim.value] = self.rejim_sayaci.get(r.rejim.value, 0) + 1

        self._bakim(t, r)

        if t.sembol not in self.pozlar and h.hazir:
            karar = komite(h, r, t.ts, self.ayar.min_skor)
            if karar.celiski:
                self._red("CELISKI")
            elif karar.aday is not None:
                self.adaylar.append(karar.aday)

        if t.ts - self.son_flush >= self.ayar.flush_araligi_sn:
            self._flush(t)

    # --------------------------------------------------------------- pozisyon
    def _bakim(self, t: Tick, r) -> None:
        poz = self.pozlar.get(t.sembol)
        if poz is None:
            return
        pnl = poz.yon.value * (t.fiyat / poz.giris_fiyati - 1.0) * poz.notional_usd
        poz.en_iyi_pnl = max(poz.en_iyi_pnl, pnl)

        if poz.en_iyi_pnl >= self.ayar.trail_esik_usd:
            self._stop_tasi(poz, self._pnl_stop(poz, poz.en_iyi_pnl * self.ayar.trail_oran),
                            t.ts, "TRAILING")
        elif poz.en_iyi_pnl >= self.ayar.be_esik_usd:
            self._stop_tasi(poz, self._be_stop(poz), t.ts, "BE_KILIDI")

        if t.ts - poz.acilis_ts > self.ayar.zombi_sn and poz.en_iyi_pnl < 1.0:
            self._kapat(poz, t.fiyat, t.ts, "ZOMBI")
            return

        ters = (poz.yon is Yon.LONG and r.rejim is Rejim.TREND_ASAGI) or \
               (poz.yon is Yon.SHORT and r.rejim is Rejim.TREND_YUKARI)
        # Rejim dönerse erken çık — ama zarar -10 $ bütçesinin %70'ini geçtiyse dokunma,
        # onu stop emri kapatır (market çıkış kayma+komisyonla bütçeyi aşabilir).
        if ters and pnl < 0 and pnl > -self.kurallar.stop_net_usd * 0.70 \
                and t.ts - poz.acilis_ts > self.ayar.rejim_karsi_cikis_sn:
            self._kapat(poz, t.fiyat, t.ts, "REJIM_DONUS")

    def _be_stop(self, poz: Poz) -> float:
        pay = self.kurallar.basabas_fiyat_mesafesi + 0.0002
        px = poz.giris_fiyati * (1 + pay) if poz.yon is Yon.LONG else poz.giris_fiyati * (1 - pay)
        return self._enstruman(poz.sembol).fiyat_yuvarla(px)

    def _pnl_stop(self, poz: Poz, hedef_usd: float) -> float:
        oran = (hedef_usd + self.kurallar.gidis_donus_komisyon_usd) / max(1e-9, poz.notional_usd)
        px = poz.giris_fiyati * (1 + oran) if poz.yon is Yon.LONG else poz.giris_fiyati * (1 - oran)
        return self._enstruman(poz.sembol).fiyat_yuvarla(px)

    @staticmethod
    def _daha_iyi(poz: Poz, yeni: float) -> bool:
        return yeni > poz.stop_fiyati if poz.yon is Yon.LONG else yeni < poz.stop_fiyati

    def _stop_tasi(self, poz: Poz, yeni: float, ts: float, neden: str) -> None:
        if not self._daha_iyi(poz, yeni):
            return
        if poz.stop_emir_id and self.borsa.emir_degistir(poz.stop_emir_id, yeni):
            poz.stop_fiyati = yeni
            return
        if poz.stop_emir_id:
            self.borsa.emir_iptal(poz.stop_emir_id)
        self._stop_koy(poz, yeni, ts)

    def _stop_koy(self, poz: Poz, fiyat: float, ts: float) -> None:
        s = self.borsa.emir_gonder(EmirIstegi(
            borsa=self.borsa.ad, sembol=poz.sembol, yon=poz.yon, tip=EmirTipi.STOP_MARKET,
            adet=poz.adet, fiyat=fiyat, reduce_only=True,
            istemci_id=f"v9sl-{poz.sembol}-{int(ts)}", meta={"baz": poz.baz},
        ), ts)
        if s.basarili:
            poz.stop_emir_id, poz.stop_fiyati = s.emir_id, fiyat
        else:
            self._red("STOP_KONULAMADI")
            self._kapat(poz, self.borsa.son_fiyat.get(poz.sembol, poz.giris_fiyati), ts,
                        "STOP_KONULAMADI")

    def _kapat(self, poz: Poz, fiyat: float, ts: float, neden: str) -> None:
        if poz.stop_emir_id:
            self.borsa.emir_iptal(poz.stop_emir_id)
        s = self.borsa.emir_gonder(EmirIstegi(
            borsa=self.borsa.ad, sembol=poz.sembol, yon=poz.yon, tip=EmirTipi.MARKET,
            adet=poz.adet, reduce_only=True, istemci_id=f"v9kapat-{poz.sembol}-{int(ts)}",
            meta={"baz": poz.baz},
        ), ts)
        if s.basarili:
            self._kaydet(poz.sembol, ts, neden, cikis=s.ort_fiyat)
        else:
            self._red(f"KAPATILAMADI:{s.hata}")

    def _kaydet(self, sembol: str, ts: float, neden: str, cikis: float = 0.0) -> None:
        poz = self.pozlar.pop(sembol, None)
        if poz is None:
            return
        if cikis <= 0:
            cikis = self.borsa.son_fiyat.get(sembol, poz.giris_fiyati)
        # Net, bu pozisyonun kendi fiyat hareketinden ve iki komisyondan hesaplanır.
        # (Eskiden borsa.realize_usd farkı kullanılıyordu; eşzamanlı pozisyonlarda
        #  birbirinin kâr/zararını yazıyordu — ölçüm bozuluyordu.)
        brut = poz.yon.value * (cikis / poz.giris_fiyati - 1.0) * poz.notional_usd
        komisyon_cikis = poz.adet * cikis * self.kurallar.taker_fee_orani
        net = brut - poz.komisyon_giris - komisyon_cikis
        self.kapananlar.append(Kapanan(sembol, poz.baz, poz.yon, poz.giris_fiyati, round(cikis, 10),
                                       round(net, 4), ts, poz.acilis_ts, neden, poz.motor))
        self.son_islem_ts[poz.baz] = ts

    # ------------------------------------------------------------------ giriş
    def _flush(self, t: Tick) -> None:
        self.son_flush = t.ts
        taze = [a for a in self.adaylar if t.ts - a.ts <= self.ayar.aday_omru_sn]
        self.adaylar = []
        if not taze:
            return
        en_iyi: dict[str, Aday] = {}
        for a in taze:
            if a.baz not in en_iyi or a.skor > en_iyi[a.baz].skor:
                en_iyi[a.baz] = a
        for a in sorted(en_iyi.values(), key=lambda x: -x.skor):
            sembol = self._sembol_bul(a.baz)
            if sembol is None or sembol in self.pozlar:
                continue
            if t.ts - self.son_islem_ts.get(a.baz, -1e18) < self.ayar.sogutma_sn:
                self._red("SOGUTMA")
                continue
            if self.borsa.serbest_teminat() < self.kurallar.teminat_per_pozisyon_usd:
                self._red("TEMINAT_YETERSIZ")
                break
            self._gir(sembol, a, t)

    def _sembol_bul(self, baz: str) -> str | None:
        for sembol, e in self.borsa.enstrumanlar.items():
            if e.baz == baz:
                return sembol
        return None

    def _gir(self, sembol: str, a: Aday, t: Tick) -> None:
        enstruman = self._enstruman(sembol)
        fiyat = self.borsa.son_fiyat.get(sembol, t.fiyat)
        b = boyut_hesapla(enstruman, fiyat, a.yon, self.kurallar, self.ayar.kayma_tamponu)
        if not b.gecerli:
            self._red(f"BOYUT:{b.neden[:40]}")
            return
        self.emir_sayaci += 1
        s = self.borsa.emir_gonder(EmirIstegi(
            borsa=self.borsa.ad, sembol=sembol, yon=a.yon, tip=EmirTipi.MARKET,
            adet=b.adet, istemci_id=f"v9-{self.emir_sayaci}", meta={"baz": a.baz},
        ), t.ts)
        if not s.basarili:
            self._red(f"BORSA:{s.hata[:40]}")
            return
        poz = Poz(sembol=sembol, baz=a.baz, yon=a.yon, adet=s.dolen_adet,
                  giris_fiyati=s.ort_fiyat, notional_usd=round(s.dolen_adet * s.ort_fiyat, 4),
                  acilis_ts=t.ts, stop_fiyati=b.stop_fiyati,
                  komisyon_giris=round(s.dolen_adet * s.ort_fiyat
                                       * self.kurallar.taker_fee_orani, 6),
                  skor=a.skor, motor=a.motor)
        self.pozlar[sembol] = poz
        self._stop_koy(poz, b.stop_fiyati, t.ts)

    # ------------------------------------------------------------------- özet
    def ozet(self) -> dict:
        sim = self.borsa
        netler = [k.net_usd for k in self.kapananlar]
        kazanan = [n for n in netler if n > 0]
        kaybeden = [n for n in netler if n <= 0]
        brut_kaz, brut_kay = sum(kazanan), -sum(kaybeden)
        equity = sim.kasa_usd + sim.acik_pnl()
        return {
            "motor": "v9_ortak_akil",
            "kasa_usd": round(equity, 2),
            "realize_usd": round(sim.realize_usd, 2),
            "acik_pnl_usd": round(sim.acik_pnl(), 2),
            "acik_pozisyon": len(sim.pozisyonlar),
            "kapanan": len(netler),
            "wr": round(len(kazanan) / len(netler), 4) if netler else 0.0,
            "pf": round(brut_kaz / brut_kay, 3) if brut_kay > 0 else (99.0 if kazanan else 0.0),
            "ort_kazanc": round(brut_kaz / len(kazanan), 2) if kazanan else 0.0,
            "ort_kayip": round(-brut_kay / len(kaybeden), 2) if kaybeden else 0.0,
            "en_iyi": round(max(netler), 2) if netler else 0.0,
            "en_kotu": round(min(netler), 2) if netler else 0.0,
            "teminat_usd": round(sim.kullanilan_teminat(), 2),
            "hesap_kaldirac": round(sim.kullanilan_teminat() * 10 / max(1.0, equity), 2),
            "komisyon_usd": round(sim.komisyonlar_usd, 2),
            "tasfiye": sim.tasfiye_sayisi,
            "red": dict(sorted(self.red.items(), key=lambda kv: -kv[1])[:8]),
            "rejim": dict(sorted(self.rejim_sayaci.items(), key=lambda kv: -kv[1])),
            "cikis_nedeni": _say(k.neden for k in self.kapananlar),
        }


def _say(it) -> dict:
    d: dict[str, int] = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return dict(sorted(d.items(), key=lambda kv: -kv[1]))
