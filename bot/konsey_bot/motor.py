from bot.konsey_bot.strateji import ema, sinyal
from bot.konsey_bot.risk import boyut, stop_fiyati, pnl

class Motor:
    def __init__(self, ayar):
        self.ayar = ayar
        self.pozisyonlar = {}
        self.kapanan_islemler = []

    def tick(self, sembol, fiyat, hacim, ts):
        if sembol not in self.pozisyonlar:
            if sinyal(ema(fiyat, self.ayar['ema_period']), fiyat, self.ayar['sinyal_period']) == 1:
                self.pozisyon_ac(sembol, fiyat, hacim)
            elif sinyal(ema(fiyat, self.ayar['ema_period']), fiyat, self.ayar['sinyal_period']) == -1:
                self.pozisyon_ac(sembol, fiyat, hacim)

        if sembol in self.pozisyonlar:
            pozisyon = self.pozisyonlar[sembol]
            pozisyon['stop'] = stop_fiyati(fiyat, pozisyon['tip'], pozisyon['notional'], pozisyon['boyut'])
            pozisyon['pnl'] = pnl(fiyat, pozisyon['tip'], pozisyon['notional'], pozisyon['boyut'])

            if pozisyon['pnl'] <= -10:
                self.pozisyon_kapat(sembol, fiyat)

    def pozisyon_ac(self, sembol, fiyat, hacim):
        tip = 'B' if sinyal(ema(fiyat, self.ayar['ema_period']), fiyat, self.ayar['sinyal_period']) == 1 else 'S'
        notional = boyut(fiyat, hacim, self.ayar['kasa'], self.ayar['teminat'], self.ayar['kaldiraç'])
        boyut = notional / fiyat
        stop = stop_fiyati(fiyat, tip, notional, boyut)
        pnl = pnl(fiyat, tip, notional, boyut)
        self.pozisyonlar[sembol] = {'tip': tip, 'notional': notional, 'boyut': boyut, 'stop': stop, 'pnl': pnl}

    def pozisyon_kapat(self, sembol, fiyat):
        pozisyon = self.pozisyonlar[sembol]
        kapanma_pnl = pozisyon['pnl']
        self.kapanan_islemler.append({'sembol': sembol, 'tip': pozisyon['tip'], 'notional': pozisyon['notional'], 'kapanma_pnl': kapanma_pnl})
        del self.pozisyonlar[sembol]

    def ozet(self):
        kazanma_orani = sum(1 if x['kapanma_pnl'] > 0 else 0 for x in self.kapanan_islemler) / len(self.kapanan_islemler) if self.kapanan_islemler else 0
        realize_kar_zarar = sum(x['kapanma_pnl'] for x in self.kapanan_islemler)
        komisyon_toplami = sum(x['kapanma_pnl'] * 0.001 for x in self.kapanan_islemler)  # Örnek komisyon oranı
        return {
            'kapanan_islem_sayisi': len(self.kapanan_islemler),
            'kazanma_orani': kazanma_orani,
            'realize_kar_zarar': realize_kar_zarar,
            'komisyon_toplami': komisyon_toplami
        }
