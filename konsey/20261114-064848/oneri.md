## mimar


## risk_subayi
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
        "kod": """
async def _bakim(self, symbol: str, price: float, stop: float, side: str, qty: float, balance: float, policy: RiskPolicy) -> None:
    if self.ters_rejim:
        self.ters_rejim_sayaci += 1
    else:
        self.ters_rejim_sayaci = 0

    if self.ters_rejim_sayaci >= 20:
        self.ters_rejim = False
        self.ters_rejim_sayaci = 0

    # Diğer kod...
"""
    }
]
```

## icra
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
        "kod": "def _bakim(self, order, symbol, plan, limit_price, order_quantity, plan_qty, entry_fee, side, motor, meta, filled, average, avg_px, status):\n    if status == OrderStatus.REJECTED:\n        self.ters_rejim_sayaci += 1\n    elif status == OrderStatus.FILLED:\n        self.ters_rejim_sayaci = 0\n    if self.ters_rejim_sayaci >= 20:\n        self.kapat()\n    # Diğer mantık aynen"
    }
]
```

## test


## olcum


## ops
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
        "kod": "def _bakim(self):\n    if self.ters_rejim_sayaci >= 20:\n        self.kapat()\n    elif self.ters_rejim_sayaci > 0:\n        self.ters_rejim_sayaci += 1\n    else:\n        # Diğer mantık\n        pass"
    }
]
```