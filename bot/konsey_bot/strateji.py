from typing import List


def ema(degerler: List[float], periyot: int) -> float:
    return sum(degerler[-periyot:]) / periyot


def sinyal(fiyatlar: List[float], hacimler: List[float]) -> int:
    kisa_ema = ema(fiyatlar, 10)
    uzun_ema = ema(fiyatlar, 30)
    ortalama_hacim = sum(hacimler[-10:]) / 10

    if kisa_ema > uzun_ema and hacimler[-1] > ortalama_hacim:
        return 1
    elif kisa_ema < uzun_ema and hacimler[-1] < ortalama_hacim:
        return -1
    else:
        return 0
