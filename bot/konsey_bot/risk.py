from bot.konsey_bot.ayarlar import Ayarlar
from bot.konsey_bot.strateji import ema, sinyal



def boyut(ayar: Ayarlar, fiyat: float) -> float:
    return ayar.notional_usd / fiyat


def stop_fiyati(ayar: Ayarlar, giris: float, yon: int) -> float:
    if yon == 1:
        return giris - 10
    else:
        return giris + 10


def pnl(ayar: Ayarlar, giris: float, cikis: float, yon: int, miktar: float) -> float:
    if yon == 1:
        return (cikis - giris) * miktar
    else:
        return (giris - cikis) * miktar
