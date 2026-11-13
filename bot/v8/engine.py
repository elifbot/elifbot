# -*- coding: utf-8 -*-
"""engine.py — v8 motoru: tick → tape → sinyal → risk → emir → jurnal.

Tasarım kararları (her biri eski paketteki bir hatanın karşılığı):

1. **Stop borsada durur.** v1..v7 kâr tabanını her tick'te Python'da kontrol ediyordu;
   likit olmayan sembolde tek print'in boşluk bırakması "BE kâr koruma"yı -1.76 $'a
   çevirdi (maildeki 25 dk dökümünde 7 kez). v8, stop emrini giriş anında borsaya
   STOP_MARKET reduceOnly olarak koyar; boşluk olsa bile ilk uygun fiyattan kapanır.

2. **Kâr koruması stop emrini *değiştirir*, izlemez.** +4.50 $ görülünce stop
   başabaş+komisyon seviyesine çekilir (exchange-side amend). Böylece "kârdayken
   zarara dönme" durumu ancak tek işlemde stop'un altına gap olursa yaşanır.

3. **Teminat fiziği.** Yeni pozisyon, serbest teminat 50 $'ın altındaysa açılmaz.
   "Sınırsız" kuralı emir sayısını sınırlamaz; bakiye sınırlar. Borsa da bunu yapar.

4. **Tek yön, tek sembol.** Aynı sembolde ters yön varsa yeni giriş yok (v2'deki
   ters pozisyon kilidinin v8 karşılığı).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .broker import SimuleBorsa
from .config import KasaKurallari, MotorAyarlari, RiskProfili
from .risk import RiskYoneticisi
from .signals import SinyalKomitesi, Tape
from .sizing import boyut_hesapla
from .types import (EmirIstegi, EmirTipi, Enstruman, KapananIslem, Pozisyon,
                    Tick, Yon)


@dataclass
class MotorOlayi:
    ts: float
    tur: str
    mesaj: str


@dataclass
class Motor:
    borsa: SimuleBorsa
    profil: RiskProfili = field(default_factory=RiskProfili)
    risk: RiskYoneticisi | None = None
    komite: SinyalKomitesi | None = None
    tapes: dict[str, Tape] = field(default_factory=dict)
    pozisyonlar: dict[str, Pozisyon] = field(default_factory=dict)
    kapananlar: list[KapananIslem] = field(default_factory=list)
    olaylar: list[MotorOlayi] = field(default_factory=list)
    redler: dict[str, int] = field(default_factory=dict)
    sinyal_sayaci: dict[str, int] = field(default_factory=dict)
    son_islem_ts: dict[str, float] = field(default_factory=dict)
    kapali: bool = False

    def __post_init__(self) -> None:
        self.risk = self.risk or RiskYoneticisi(self.profil.motor, self.profil.kurallar)
        self.komite = self.komite or SinyalKomitesi(self.profil.motor)

    # ------------------------------------------------------------- yardımcı
    @property
    def kurallar(self) -> KasaKurallari:
        return self.profil.kurallar

    def _olay(self, ts: float, tur: str, mesaj: str) -> None:
        self.olaylar.append(MotorOlayi(ts, tur, mesaj))

    def _red(self, neden: str) -> None:
        anahtar = neden.split(" (")[0].split(":")[0]
        self.redler[anahtar] = self.redler.get(anahtar, 0) + 1

    # ------------------------------------------------------------------ tick
    def tick(self, t: Tick) -> None:
        if self.kapali:
            return
        baz = t.baz
        tape = self.tapes.get(baz)
        if tape is None:
            tape = self.tapes[baz] = Tape(baz)
        tape.ekle(t)
        self.risk.fiyat_besle(baz, t.ts, t.fiyat)
        self.risk.tick_gordu(t.ts)

        # borsa tarafı: fiyat, duran stop emirleri, tasfiye
        onceki = dict(self.borsa.pozisyonlar)
        dolumlar = self.borsa.tick_islet(t.sembol, t.fiyat, t.hacim24_usd)
        for d in dolumlar:
            self._stop_doldu(d.sembol, d.fiyat, d.ts, "STOP")

        # açık pozisyonların tepe kârı + kâr koruması (stop emri değiştirilir)
        self._pozisyon_bakimi(t)

        # yeni giriş
        if len(self.borsa.pozisyonlar) or True:
            self._giris_dene(t)
        _ = onceki

    # ------------------------------------------------------------- pozisyonlar
    def _pozisyon_bakimi(self, t: Tick) -> None:
        poz = self.pozisyonlar.get(t.sembol)
        if poz is None:
            return
        pnl = poz.guncel_pnl(t.fiyat)
        if pnl > poz.en_iyi_pnl_usd:
            poz.en_iyi_pnl_usd = round(pnl, 4)

        k = self.kurallar
        m = self.profil.motor

        # kademe 1: +4.50 $ -> stop başabaş + komisyon üstüne çekilir
        if poz.en_iyi_pnl_usd >= 4.50 and poz.stop_fiyati != self._be_stop(poz):
            self._stop_tasi(poz, self._be_stop(poz), t.ts, "BE_KILIDI")

        # kademe 2: tepe kârın %30'u kadar geri verilince kilit daraltılır
        elif poz.en_iyi_pnl_usd >= 8.0:
            taban = poz.en_iyi_pnl_usd * 0.70
            yeni = self._pnl_icin_stop(poz, taban)
            if self._daha_iyi_stop(poz, yeni):
                self._stop_tasi(poz, yeni, t.ts, "TRAILING")

        # zombi: 20 dk boyunca hiç ilerlemeyen pozisyon kapatılır
        if t.ts - poz.acilis_ts > m.zombi_sn and poz.en_iyi_pnl_usd < 1.0:
            self._kapat(poz, t.fiyat, t.ts, "ZOMBI")

    def _be_stop(self, poz: Pozisyon) -> float:
        """Başabaş + gidiş-dönüş komisyonunu karşılayan stop fiyatı."""
        k = self.kurallar
        pay = k.basabas_fiyat_mesafesi + 0.0002
        enstruman = self.borsa.enstrumanlar[poz.sembol]
        px = poz.giris_fiyati * (1 + pay) if poz.yon is Yon.LONG else poz.giris_fiyati * (1 - pay)
        return enstruman.fiyat_yuvarla(px)

    def _pnl_icin_stop(self, poz: Pozisyon, hedef_pnl: float) -> float:
        """Belirli bir net PnL'i kilitleyen fiyat."""
        k = self.kurallar
        gerekli_oran = (hedef_pnl + poz.komisyon_usd) / max(1e-9, poz.notional_usd)
        px = poz.giris_fiyati * (1 + gerekli_oran) if poz.yon is Yon.LONG \
            else poz.giris_fiyati * (1 - gerekli_oran)
        return self.borsa.enstrumanlar[poz.sembol].fiyat_yuvarla(px)

    def _daha_iyi_stop(self, poz: Pozisyon, yeni: float) -> bool:
        if poz.yon is Yon.LONG:
            return yeni > poz.stop_fiyati
        return yeni < poz.stop_fiyati

    def _stop_tasi(self, poz: Pozisyon, yeni: float, ts: float, neden: str) -> None:
        if poz.stop_emir_id and self.borsa.emir_degistir(poz.stop_emir_id, yeni):
            poz.stop_fiyati = yeni
            self._olay(ts, neden, f"{poz.sembol} stop -> {yeni:.8g}")
            return
        # amend başarısız: iptal + yeniden koy (borsa gerçeği)
        if poz.stop_emir_id:
            self.borsa.emir_iptal(poz.stop_emir_id)
        self._stop_koy(poz, yeni, ts)

    def _stop_koy(self, poz: Pozisyon, fiyat: float, ts: float) -> None:
        istek = EmirIstegi(
            borsa=self.borsa.ad, sembol=poz.sembol, yon=poz.yon, tip=EmirTipi.STOP_MARKET,
            adet=poz.adet, fiyat=fiyat, reduce_only=True,
            istemci_id=f"sl-{poz.kimlik}", meta={"baz": poz.baz},
        )
        sonuc = self.borsa.emir_gonder(istek, ts)
        if sonuc.basarili:
            poz.stop_emir_id = sonuc.emir_id
            poz.stop_fiyati = fiyat
        else:
            self._olay(ts, "STOP_KONULAMADI", f"{poz.sembol}: {sonuc.hata}")
            # stop konulamayan pozisyon taşınamaz: hemen kapat
            self._kapat(poz, self.borsa.son_fiyat.get(poz.sembol, poz.giris_fiyati),
                        ts, "STOP_KONULAMADI")

    def _stop_doldu(self, sembol: str, fiyat: float, ts: float, neden: str) -> None:
        poz = self.pozisyonlar.get(sembol)
        if poz is None:
            return
        self._kaydet(poz, fiyat, ts, neden)
        self.pozisyonlar.pop(sembol, None)
        self.risk.sogut(poz.baz, ts)

    def _kapat(self, poz: Pozisyon, fiyat: float, ts: float, neden: str) -> None:
        istek = EmirIstegi(
            borsa=self.borsa.ad, sembol=poz.sembol, yon=poz.yon, tip=EmirTipi.MARKET,
            adet=poz.adet, reduce_only=True, istemci_id=f"cl-{poz.kimlik}",
            meta={"baz": poz.baz},
        )
        sonuc = self.borsa.emir_gonder(istek, ts)
        if not sonuc.basarili:
            self._olay(ts, "KAPATILAMADI", f"{poz.sembol}: {sonuc.hata}")
            return
        if poz.stop_emir_id:
            self.borsa.emir_iptal(poz.stop_emir_id)
        self._kaydet(poz, sonuc.ort_fiyat, ts, neden)
        self.pozisyonlar.pop(poz.sembol, None)
        self.risk.sogut(poz.baz, ts)

    def _kaydet(self, poz: Pozisyon, cikis: float, ts: float, neden: str) -> None:
        k = self.kurallar
        carpan = self.borsa.enstrumanlar[poz.sembol].kontrat_carpani
        brut = poz.yon.value * (cikis / poz.giris_fiyati - 1.0) * (poz.adet * poz.giris_fiyati * carpan)
        komisyon = poz.adet * cikis * carpan * k.taker_fee_orani
        net = brut - poz.komisyon_usd - komisyon
        self.kapananlar.append(KapananIslem(
            kimlik=poz.kimlik, borsa=poz.borsa, sembol=poz.sembol, yon=poz.yon.etiket,
            giris_fiyati=poz.giris_fiyati, cikis_fiyati=round(cikis, 10),
            net_pnl_usd=round(net, 4), en_iyi_pnl_usd=round(poz.en_iyi_pnl_usd, 4),
            acilis_ts=poz.acilis_ts, kapanis_ts=ts, neden=neden,
        ))

    # ---------------------------------------------------------------- giriş
    def _giris_dene(self, t: Tick) -> None:
        simdi = t.ts
        if simdi - self.son_islem_ts.get(t.sembol, 0.0) < self.profil.motor.sembol_soguma_sn:
            return
        sinyal = self.komite.degerlendir(self.tapes[t.baz], t.baz, simdi)
        if sinyal is None:
            return
        self.sinyal_sayaci[sinyal.motor] = self.sinyal_sayaci.get(sinyal.motor, 0) + 1

        enstruman = self.borsa.enstrumanlar.get(t.sembol)
        if enstruman is None:
            self._red("ENSTRUMAN_YOK")
            return

        durum = self.borsa.kasa_durumu()
        karar = self.risk.giris_izni(
            baz=t.baz, yon=sinyal.yon, fiyat=t.fiyat, simdi=simdi,
            kasa_usd=durum.kasa_usd, kullanilan_teminat_usd=durum.kullanilan_teminat_usd,
            acik_semboller=set(self.borsa.pozisyonlar),
            hacim24_usd=enstruman and t.hacim24_usd, enstruman_durum=enstruman.durum,
            sinyal_yasi=max(0.0, simdi - sinyal.ts),
        )
        if not karar:
            for n in karar.nedenler:
                self._red(n)
            return

        boyut = boyut_hesapla(enstruman, t.fiyat, sinyal.yon, self.kurallar)
        if not boyut.gecerli:
            self._red(f"BOYUT_GECERSIZ ({boyut.neden})")
            return

        kimlik = f"{self.borsa.ad}-{uuid.uuid4().hex[:10]}"
        istek = EmirIstegi(
            borsa=self.borsa.ad, sembol=t.sembol, yon=sinyal.yon, tip=EmirTipi.MARKET,
            adet=boyut.adet, istemci_id=f"en-{kimlik}", meta={"baz": t.baz},
        )
        sonuc = self.borsa.emir_gonder(istek, simdi)
        self.risk.emir_sonucu(sonuc.basarili)
        if not sonuc.basarili:
            self._red(f"EMIR_RED ({sonuc.hata})")
            return

        poz = Pozisyon(
            kimlik=kimlik, borsa=self.borsa.ad, sembol=t.sembol, baz=t.baz, yon=sinyal.yon,
            adet=sonuc.dolen_adet, giris_fiyati=sonuc.ort_fiyat, notional_usd=boyut.notional_usd,
            teminat_usd=boyut.teminat_usd, acilis_ts=simdi,
            stop_fiyati=boyut.stop_fiyati,
            komisyon_usd=sonuc.dolen_adet * sonuc.ort_fiyat
            * self.borsa.enstrumanlar[t.sembol].kontrat_carpani * self.kurallar.taker_fee_orani,
        )
        self.pozisyonlar[t.sembol] = poz
        self.son_islem_ts[t.sembol] = simdi
        self._stop_koy(poz, boyut.stop_fiyati, simdi)
        self._olay(simdi, "GIRIS", f"{poz.sembol} {poz.yon.etiket} @ {poz.giris_fiyati:.8g} "
                                f"| {sinyal.motor} | stop {boyut.stop_fiyati:.8g}")

    # ---------------------------------------------------------------- özet
    def ozet(self) -> dict:
        d = self.borsa.kasa_durumu()
        kazanan = sum(1 for k in self.kapananlar if k.net_pnl_usd > 0)
        return {
            "borsa": self.borsa.ad,
            "kasa_usd": round(d.kasa_usd + d.acik_pnl_usd, 2),
            "realize_usd": round(self.borsa.realize_usd, 2),
            "acik_pnl_usd": round(d.acik_pnl_usd, 2),
            "acik_pozisyon": d.acik_pozisyon,
            "kapanan": len(self.kapananlar),
            "kazanan": kazanan,
            "win_rate": round(kazanan / len(self.kapananlar), 4) if self.kapananlar else 0.0,
            "kullanilan_teminat_usd": round(d.kullanilan_teminat_usd, 2),
            "serbest_teminat_usd": round(d.serbest_teminat_usd, 2),
            "kaldirac": d.kaldirac,
            "komisyon_usd": round(self.borsa.komisyonlar_usd, 2),
            "tasfiye_sayisi": self.borsa.tasfiye_sayisi,
            "sinyal": self.sinyal_sayaci,
            "red": self.redler,
            "risk": self.risk.kasa_raporu(d.kasa_usd, d.acik_pozisyon, d.kullanilan_teminat_usd),
        }
