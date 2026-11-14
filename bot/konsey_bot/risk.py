from bot.konsey_bot.strateji import ema, sinyal

def boyut(ayar, fiyat):
    notional = ayar['kasa'] / ayar['teminat']
    return notional / fiyat

def stop_fiyati(ayar, giris, yon):
    if yon == 1:
        return giris - 10
    else:
        return giris + 10

def pnl(ayar, giris, cikis, yon, miktar):
    komisyon = ayar['komisyon']
    if yon == 1:
        return (cikis - giris) * miktar - komisyon
    else:
        return (giris - cikis) * miktar - komisyon
