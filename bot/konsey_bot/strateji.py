from bot.konsey_bot.ayarlar import Ayarlar


def ema(degerler: list[float], periyot: int) -> float:
    return sum(degerler[-periyot:]) / periyot


def sinyal(fiyatlar: list[float], hacimler: list[float]) -> int:
    kisa_ema = ema(fiyatlar, 10)
    uzun_ema = ema(fiyatlar, 30)
    ortalama_hacim = sum(hacimler[-30:]) / 30

    if kisa_ema > uzun_ema and hacimler[-1] > ortalama_hacim:
        return 1
    elif kisa_ema < uzun_ema and hacimler[-1] < ortalama_hacim:
        return -1
    else:
        return 0
