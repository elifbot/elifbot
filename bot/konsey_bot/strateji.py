import numpy as np

class Ayarlar:
    notional_usd = 1000
    stop_yuzde = 10


def ema(degerler: list[float], periyot: int) -> float:
    """
    EMA (Exponential Moving Average) hesaplaması.

    :param degerler: Veri listesi.
    :param periyot: EMA periyotu.
    :return: EMA değeri.
    """
    if len(degerler) < periyot:
        return np.nan
    ema_values = [degerler[0]]
    for i in range(1, len(degerler)):
        ema_values.append(ema_values[-1] * (periyot - 1) / periyot + degerler[i] / periyot)
    return ema_values[-1]


def sinyal(fiyatlar: list[float], hacimler: list[float]) -> int:
    """
    Sinyal belirleme fonksiyonu.

    :param fiyatlar: Fiyat listesi.
    :param hacimler: Hacim listesi.
    :return: 1 al, -1 sat, 0 bekle.
    """
    if len(fiyatlar) != len(hacimler):
        raise ValueError('Fiyatlar ve hacimler listesi uzunlukları eşit olmalıdır.')

    if len(fiyatlar) < 2:
        return 0

    short_ema = ema(fiyatlar, 50)
    long_ema = ema(fiyatlar, 200)

    if short_ema > long_ema:
        if hacimler[-1] > np.mean(hacimler):
            return 1
        else:
            return -1
    else:
        return 0
