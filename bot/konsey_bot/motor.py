import json
from bot.konsey_bot.ayarlar import Ayarlar
from bot.konsey_bot.strateji import Strateji

class Motor:
    def __init__(self, ayarlar):
        self.ayarlar = ayarlar
        self.pozisyonlar = {}

    def tick(self, sembol, fiyat, hacim, ts):
        if sembol not in self.pozisyonlar:
            self.pozisyonlar[sembol] = {'fiyat': fiyat, 'hacim': hacim, 'ts': ts}
            self.pozisyonlar[sembol]['sinyal'] = self.strateji.sinyal(sembol, fiyat, hacim, ts)

        if self.pozisyonlar[sembol]['sinyal'] == 1:
            self.pozisyonlar[sembol]['fiyat'] = fiyat
            self.pozisyonlar[sembol]['hacim'] = hacim
            self.pozisyonlar[sembol]['ts'] = ts

        self.pozisyonlar[sembol]['stop'] = self.ayarlar.stop_yuzde * fiyat
        self.pozisyonlar[sembol]['pnl'] = self.pozisyonlar[sembol]['fiyat'] * self.pozisyonlar[sembol]['hacim'] - self.ayarlar.notional_usd

        if self.pozisyonlar[sembol]['fiyat'] < self.pozisyonlar[sembol]['stop']:
            self.kapat(sembol)

    def kapat(self, sembol):
        fiyat = self.pozisyonlar[sembol]['fiyat']
        hacim = self.pozisyonlar[sembol]['hacim']
        self.pozisyonlar.pop(sembol)

    def ozet(self):
        kapanan_islem_sayisi = len([p for p in self.pozisyonlar.values() if p['sinyal'] == 0])
        kazanma_oranı = kapanan_islem_sayisi / len(self.pozisyonlar) if len(self.pozisyonlar) > 0 else 0
        realize_kar_zarar = sum(p['pnl'] for p in self.pozisyonlar.values())
        komisyon_toplami = sum(p['fiyat'] * p['hacim'] * 0.001 for p in self.pozisyonlar.values())

        return {
            'kapanan_islem_sayisi': kapanan_islem_sayisi,
            'kazanma_oranı': kazanma_oranı,
            'realize_kar_zarar': realize_kar_zarar,
            'komisyon_toplami': komisyon_toplami
        }
