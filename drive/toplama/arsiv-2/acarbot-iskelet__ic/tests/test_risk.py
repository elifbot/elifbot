import unittest

from bot.core import risk


class RiskTest(unittest.TestCase):
    def test_boyut(self):
        b = risk.pozisyon_boyutu(100.0, marj_usd=50, kaldirac=10)
        self.assertAlmostEqual(b["nominal"], 500.0)
        self.assertAlmostEqual(b["adet"], 5.0)

    def test_sabit_zarar_komisyon_dahil_25_dolar(self):
        giris, adet, k = 100.0, 5.0, 0.0005
        m = risk.stop_mesafesi_sabit_zarar(giris, adet, 25.0, k)
        stop = risk.stop_fiyati("LONG", giris, m)
        zarar = (giris - stop) * adet + k * giris * adet + k * stop * adet
        self.assertAlmostEqual(zarar, 25.0, delta=0.05)  # cikis komisyonu stop fiyatindan

    def test_long_stop_likidasyondan_once(self):
        giris, adet = 100.0, 5.0
        stop = risk.stop_fiyati("LONG", giris, risk.stop_mesafesi_sabit_zarar(giris, adet))
        liq = risk.likidasyon_fiyati("LONG", giris, 10)
        self.assertGreater(stop, liq)

    def test_short_yonu(self):
        self.assertGreater(risk.stop_fiyati("SHORT", 100, 2), 100)
        self.assertGreater(risk.likidasyon_fiyati("SHORT", 100, 10), 100)

    def test_atr_zarar_sinirlanir(self):
        # cok oynak coin: ATR buyuk, adet kuculmeli ve zarar <= 25$
        r = risk.atr_stop_icin_adet(giris=100.0, atr=4.0, atr_carpani=2.5)
        self.assertTrue(r["risk_ile_kisitlandi"])
        self.assertLessEqual(r["adet"] * r["mesafe"], 25.0 + 1e-9)

    def test_atr_sakin_coinde_marj_siniri(self):
        r = risk.atr_stop_icin_adet(giris=100.0, atr=0.2, atr_carpani=2.5)
        self.assertFalse(r["risk_ile_kisitlandi"])
        self.assertAlmostEqual(r["adet"], 5.0)

    def test_gecersiz_girdi(self):
        with self.assertRaises(ValueError):
            risk.pozisyon_boyutu(0)
        with self.assertRaises(ValueError):
            risk.stop_fiyati("YANLIS", 100, 1)


if __name__ == "__main__":
    unittest.main()
