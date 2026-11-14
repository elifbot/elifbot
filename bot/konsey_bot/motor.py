from bot.konsey_bot.ayarlar import Ayarlar
from bot.konsey_bot.strateji import ema, sinyal
from bot.konsey_bot.risk import boyut, stop_fiyati, pnl

class Motor:
    def __init__(self, ayar: Ayarlar):
        self.ayar = ayar
        self.pozisyonlar = {}
        self.kapanan_islemler = []

    def tick(self, sembol, fiyat, hacim, ts):
        sinyal_degeri = sinyal(ema, fiyat)
        if sinyal_degeri == 1 and sembol not in self.pozisyonlar:
            self.pozisyon_ac(sembol, fiyat)
        elif sinyal_degeri == -1 and sembol in self.pozisyonlar:
            self.pozisyon_kapat(sembol, fiyat)

        if sembol in self.pozisyonlar:
            pozisyon = self.pozisyonlar[sembol]
            pozisyon['stop'] = stop_fiyati(fiyat, pozisyon['stop_yuzde'])
            pozisyon['pnl'] = pnl(fiyat, pozisyon['acilis_fiyat'], pozisyon['hacim'])

            if pozisyon['pnl'] <= pozisyon['stop']:
                self.pozisyon_kapat(sembol, fiyat)

    def pozisyon_ac(self, sembol, fiyat):
        pozisyon_boyutu = boyut(self.ayar.notional_usd, sembol)
        pozisyon_stop = stop_fiyati(fiyat, self.ayar.stop_yuzde)
        pozisyon = {
            'acilis_fiyat': fiyat,
            'hacim': pozisyon_boyutu,
            'stop': pozisyon_stop,
            'pnl': 0
        }
        self.pozisyonlar[sembol] = pozisyon

    def pozisyon_kapat(self, sembol, fiyat):
        pozisyon = self.pozisyonlar[sembol]
        kazanma_orani = pozisyon['pnl'] / pozisyon['acilis_fiyat'] * 100
        self.kapanan_islemler.append({
            'sembol': sembol,
            'acilis_fiyat': pozisyon['acilis_fiyat'],
            'kapanis_fiyat': fiyat,
            'hacim': pozisyon['hacim'],
            'kazanma_orani': kazanma_orani,
            'pnl': pozisyon['pnl']
        })
        del self.pozisyonlar[sembol]

    def ozet(self):
        kazanma_orani_toplami = sum(islem['kazanma_orani'] for islem in self.kapanan_islemler)
        kazanma_orani = kazanma_orani_toplami / len(self.kapanan_islemler) if self.kapanan_islemler else 0
        realize_kar_zarar = sum(islem['pnl'] for islem in self.kapanan_islemler)
        komisyon_toplami = 0  # Komisyon hesaplaması burada yapılabilir
        return {
            'kapanan_islem_sayisi': len(self.kapanan_islemler),
            'kazanma_orani': kazanma_orani,
            'realize_kar_zarar': realize_kar_zarar,
            'komisyon_toplami': komisyon_toplami
        }
