from dataclasses import dataclass
from typing import List, Tuple
import argparse
import json
import math
import pathlib
import random
import time

@dataclass
class Ayarlar:
    kasa_usd: float = 1000.0
    teminat_usd: float = 50.0
    kaldirac: float = 10.0
    stop_net_usd: float = -10.0
    komisyon_oran: float = 0.0005
    notional_usd: float = teminat_usd * kaldirac
    stop_yuzde: float = stop_net_usd / notional_usd * 100

def ema(degerler: List[float], periyot: int) -> float:
    ortalama = sum(degerler[:periyot]) / periyot
    for deger in degerler[periyot:]:
        ortalama = 0.2 * deger + 0.8 * ortalama
    return ortalama

def sinyal(fiyatlar: List[float], hacimler: List[float]) -> int:
    ema_12 = ema(fiyatlar, 12)
    ema_26 = ema(fiyatlar, 26)
    ema_9 = ema(ema_12 - ema_26, 9)
    if ema_12 > ema_26 and ema_12 > ema_9 and ema_26 > ema_9 and hacimler[-1] > hacimler[-2]:
        return 1
    elif ema_12 < ema_26 and ema_12 < ema_9 and ema_26 < ema_9 and hacimler[-1] < hacimler[-2]:
        return -1
    else:
        return 0

def boyut(ayar: Ayarlar, fiyat: float) -> float:
    return ayar.notional_usd / fiyat

def stop_fiyati(ayar: Ayarlar, giris: float, yon: int) -> float:
    if yon == 1:
        return giris * (1 + ayar.stop_yuzde)
    else:
        return giris * (1 - ayar.stop_yuzde)

def pnl(ayar: Ayarlar, giris: float, cikis: float, yon: int, miktar: float) -> float:
    if yon == 1:
        return miktar * (cikis - giris) - miktar * giris * ayar.komisyon_oran
    else:
        return miktar * (giris - cikis) - miktar * giris * ayar.komisyon_oran

class Motor:
    def __init__(self, ayar: Ayarlar):
        self.ayar = ayar
        self.pozisyon = None
        self.kasa_usd = ayar.kasa_usd
        self.realize_usd = 0.0
        self.komisyon_usd = 0.0

    def tick(self, sembol: str, fiyat: float, hacim: float, ts: float):
        if self.pozisyon is None:
            if sinyal([fiyat], [hacim]) == 1:
                self.pozisyon = {'sembol': sembol, 'giris': fiyat, 'miktar': boyut(self.ayar, fiyat), 'ts': ts}
        else:
            if sinyal([fiyat], [hacim]) == -1 or fiyat <= stop_fiyati(self.ayar, self.pozisyon['giris'], self.pozisyon['yon']):
                cikis = fiyat
                pnl_ = pnl(self.ayar, self.pozisyon['giris'], cikis, self.pozisyon['yon'], self.pozisyon['miktar'])
                self.realize_usd += pnl_
                self.komisyon_usd += abs(pnl_) * self.ayar.komisyon_oran
                self.kasa_usd += pnl_
                self.pozisyon = None

    def ozet(self) -> dict:
        return {
            'islem': 1 if self.pozisyon else 0,
            'kazanma_orani': self.realize_usd / self.ayar.kasa_usd if self.ayar.kasa_usd != 0 else 0,
            'realize_usd': self.realize_usd,
            'komisyon_usd': self.komisyon_usd
        }

def main(argv=None):
    parser = argparse.ArgumentParser(description='Kripto vadeli işlem botu')
    parser.add_argument('sembol', type=str, help='Kripto sembolü')
    parser.add_argument('--dakika', type=float, default=5, help='Dakika aralığı (varsayılan: 5)')
    parser.add_argument('--etiket', type=str, default='test', help='Etiket (varsayılan: test)')
    args = parser.parse_args(argv)

    ayar = Ayarlar()
    motor = Motor(ayar)

    sembol = args.sembol
    dakika = int(args.dakika)  # float değerini int'e dönüştür
    etiket = args.etiket

    tohum = 42
    random.seed(tohum)

    fiyatlar = [random.uniform(10000, 15000) for _ in range(1000)]
    hacimler = [random.uniform(100, 500) for _ in range(1000)]

    for i in range(len(fiyatlar)):
        motor.tick(sembol, fiyatlar[i], hacimler[i], time.time() + i * dakika * 60)

    ozet = motor.ozet()
    print(ozet)

    pathlib.Path(f'runs/{etiket}/ozet.json').parent.mkdir(parents=True, exist_ok=True)
    with open(f'runs/{etiket}/ozet.json', 'w') as f:
        json.dump(ozet, f)

if __name__ == '__main__':
    main()
