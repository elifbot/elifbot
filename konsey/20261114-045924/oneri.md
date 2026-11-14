## mimar
```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Poz",
    "dosya": "bot/v9/motor.py",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_bakim",
    "dosya": "bot/v9/motor.py",
    "kod": "    def _bakim(self, pos: Poz, fiyat: float, sinyal: any):\n        # PnL ve Temel Hesaplamalar\n        pnl = pos.hesapla_pnl(fiyat)\n        \n        # BE Kilidi ve Trailing\n        if pos.be_kilitli:\n            if (pos.yon == 'LONG' and fiyat >= pos.be_fiyat) or (pos.yon == 'SHORT' and fiyat <= pos.be_fiyat):\n                pos.stop_loss = pos.be_fiyat\n        \n        # Zombi Kontrolü\n        if pos.is_zombi():\n            return self.kapat(pos, \"ZOMBI\")\n\n        # Ters Rejim Teyit Mantığı\n        if sinyal == \"REJIM_DONUS\":\n            pos.ters_rejim_sayaci += 1\n        else:\n            pos.ters_rejim_sayaci = 0\n\n        # Kapatma Koşulları\n        if pos.ters_rejim_sayaci >= 20:\n            return self.kapat(pos, \"REJIM_TEYIT_KAPAT\")\n\n        if pnl <= -10:\n            return self.kapat(pos, \"STOP_LOSS\")\n\n        return None"
  }
]
```

## risk_subayi
**Risk Analizi:**
Öneri, mevcut risk parametrelerini (1.000$ kasa, 50$ teminat, 10x, -10$ stop) değiştirmez; sadece hatalı sinyallerle kapanan pozisyonların (REJIM_DONUS) kapatma eşiğini yükselterek "testere" piyasasında erken çıkışı engeller.
**En kötü durumda kasa ne olur?**
Kapatma koşulunun `ters_rejim_sayaci >= 20` şeklinde esnetilmesi, pozisyonun hatalı rejimde daha uzun süre kalmasına neden olabilir. Ancak pozisyon başına net -10$ stop kuralı değişmediği için, en kötü senaryoda kasa yine pozisyon başına maksimum 10$ kaybeder. Toplam risk, eşzamanlı açık pozisyon sayısıyla sınırlıdır.

```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Poz",
    "dosya": "bot/v9/motor.py",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_bakim",
    "dosya": "bot/v9/motor.py",
    "kod": "async def _bakim(self, poz: Poz, data: dict):\n    # PnL ve Temel Hesaplamalar\n    pnl = poz.hesapla_pnl(data['close'])\n    \n    # Trailing Stop ve Zombi Kontrolü\n    if poz.trailing_update(data['close']):\n        return await self.kapat(poz, \"TRAILING\")\n    \n    if poz.is_zombie(data):\n        return await self.kapat(poz, \"ZOMBIE\")\n\n    # BE Kilidi\n    if poz.be_lock and pnl < 0:\n        return await self.kapat(poz, \"BE_LOCK\")\n\n    # REJIM_DONUS ve Ters Rejim Mantığı\n    if data.get('REJIM_DONUS'):\n        poz.ters_rejim_sayaci += 1\n    else:\n        poz.ters_rejim_sayaci = 0\n\n    if poz.ters_rejim_sayaci >= 20:\n        return await self.kapat(poz, \"REJIM_DONUS\")\n\n    return None"
  }
]
```

## icra


## test
```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Poz",
    "dosya": "bot/v9/motor.py",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_bakim",
    "dosya": "bot/v9/motor.py",
    "kod": "    def _bakim(self, poz: Poz, fiyat: float, sinyal: dict):\n        # PnL ve Temel Hesaplamalar\n        poz.pnl = (fiyat - poz.entry) * poz.miktar if poz.side == 'LONG' else (poz.entry - fiyat) * poz.miktar\n        \n        # BE Kilidi ve Trailing\n        if poz.pnl > poz.be_threshold and not poz.be_locked:\n            poz.be_locked = True\n        \n        if poz.be_locked and poz.pnl < poz.trailing_stop:\n            return self._kapat(poz, fiyat, \"TRAILING_STOP\")\n\n        # Zombi Kontrolü\n        if poz.is_zombie():\n            return self._kapat(poz, fiyat, \"ZOMBIE\")\n\n        # Rejim Kontrolü ve Ters Rejim Sayacı\n        if sinyal.get('REJIM_DONUS'):\n            poz.ters_rejim_sayaci += 1\n        else:\n            poz.ters_rejim_sayaci = 0\n\n        # Kapatma Koşulu: Ters Rejim Teyidi\n        if poz.ters_rejim_sayaci >= 20:\n            return self._kapat(poz, fiyat, \"REJIM_DONUS_TEYIT\")\n\n        return None"
  }
]
```

## olcum
```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Poz",
    "dosya": "bot/v9/motor.py",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_bakim",
    "dosya": "bot/v9/motor.py",
    "kod": "    def _bakim(self, pos: Poz, price: float, signal: dict):\n        # PnL ve Temel Hesaplamalar\n        pnl = (price - pos.entry) * pos.qty if pos.side == \"LONG\" else (pos.entry - price) * pos.qty\n        \n        # Ters Rejim Takibi\n        if signal.get('REJIM_DONUS'):\n            pos.ters_rejim_sayaci += 1\n        else:\n            pos.ters_rejim_sayaci = 0\n\n        # Kapatma Koşulları\n        if pos.ters_rejim_sayaci >= 20:\n            return \"REJIM_SAYAC_STOP\"\n\n        # BE Kilidi ve Trailing Mantığı (Korunan Kısım)\n        if pos.side == \"LONG\":\n            if pnl > pos.be_threshold:\n                pos.be_locked = True\n            if pos.be_locked and price > pos.entry:\n                pos.stop = max(pos.stop, price - pos.trailing_dist)\n            if price <= pos.stop:\n                return \"STOP_LOSS\"\n        else:\n            if pnl > pos.be_threshold:\n                pos.be_locked = True\n            if pos.be_locked and price < pos.entry:\n                pos.stop = min(pos.stop, price + pos.trailing_dist)\n            if price >= pos.stop:\n                return \"STOP_LOSS\"\n\n        # Zombi ve Genel PnL Kontrolü\n        if pos.is_zombie and pnl < 0:\n            return \"ZOMBIE_EXIT\"\n\n        return None"
  }
]
```

## ops
