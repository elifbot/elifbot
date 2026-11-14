## mimar
```json
{
  "modifikasyonlar": [
    {
      "dosya": "bot/v9/motor.py",
      "hedef": "Poz dataclass",
      "islem": "EKLE",
      "kod": "ters_rejim_sayaci: int = 0"
    },
    {
      "dosya": "bot/v9/motor.py",
      "hedef": "_izle metodu",
      "islem": "GUNCELLE",
      "mantik": "if rejim_ters: pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0"
    },
    {
      "dosya": "bot/v9/motor.py",
      "hedef": "satır 140-144 (REJIM_DONUS)",
      "islem": "DEGISKILIK",
      "eski_kosul": "rejim_ters and pnl < 0",
      "yeni_kosul": "pos.ters_rejim_sayaci >= 20"
    }
  ],
  "sabitler_kontrol": {
    "kasa": "1000$",
    "teminat": "50$",
    "kaldiraç": "10x",
    "mod": "CROSS",
    "stop_loss": "-10$"
  }
}
```

## risk_subayi
```json
{
  "risk_assessment": {
    "status": "APPROVED",
    "worst_case_scenario": "Kasa kaybı değişmez; stop-loss -10$ kuralı korunduğu için tek pozisyon başına maksimum zarar 10$ olarak kalır. Sadece kapanma zamanlaması (gecikmesi) değişir, risk miktarı değil.",
    "technical_validation": {
      "margin_physics": "Sabit 50$ teminat / 10x Cross yapısı korunuyor.",
      "liquidation_distance": "Kapatma koşulunun esnetilmesi tasfiye mesafesini etkilemez, çünkü -10$ net stop önceliklidir.",
      "correlation": "Pozisyon limiti olmadığı için korelasyon riski mevcut ancak önerilen değişiklik risk miktarını artırmamaktadır."
    }
  },
  "implementation": {
    "file": "bot/v9/motor.py",
    "changes": [
      {
        "target": "Poz dataclass",
        "action": "ADD_FIELD",
        "field": "ters_rejim_sayaci: int = 0"
      },
      {
        "target": "_izle method",
        "action": "LOGIC_UPDATE",
        "logic": "if rejim_ters: pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0"
      },
      {
        "target": "REJIM_DONUS exit condition",
        "action": "REPLACE",
        "old_condition": "time > 120 and rejim_ters and pnl < 0",
        "new_condition": "pos.ters_rejim_sayaci >= 20"
      }
    ]
  }
}
```

## icra
```json
{
  "action": "modify_code",
  "file": "bot/v9/motor.py",
  "changes": [
    {
      "target": "Poz dataclass",
      "addition": "ters_rejim_sayaci: int = 0"
    },
    {
      "target": "_izle method",
      "logic": "if rejim_ters: poz.ters_rejim_sayaci += 1 else: poz.ters_rejim_sayaci = 0"
    },
    {
      "target": "lines 140-144",
      "replacement": "if poz.rejim_karsi_cikis_sn >= 120 and poz.ters_rejim_sayaci >= 20 and poz.pnl < 0: kapat()"
    }
  ],
  "constraints_check": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "mode": "CROSS",
    "pos_limit": "NONE",
    "stop": "-10$"
  }
}
```

## test
```json
{
  "action": "modify_code",
  "file": "bot/v9/motor.py",
  "changes": [
    {
      "target": "Poz dataclass",
      "addition": "ters_rejim_sayaci: int = 0"
    },
    {
      "target": "_izle method",
      "logic": "if rejim_ters: poz.ters_rejim_sayaci += 1 else: poz.ters_rejim_sayaci = 0"
    },
    {
      "target": "lines 140-144",
      "replacement": "if poz.ters_rejim_sayaci >= 20 and poz.pnl < 0: self.kapat(poz)"
    }
  ],
  "constraints_validation": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "mode": "CROSS",
    "pos_limit": "NONE",
    "stop_loss": "-10$"
  }
}
```

## olcum
```json
{
  "action": "modify_code",
  "file": "bot/v9/motor.py",
  "changes": [
    {
      "target": "Poz dataclass",
      "addition": "ters_rejim_sayaci: int = 0"
    },
    {
      "target": "_izle method",
      "logic": "if rejim_ters: pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0"
    },
    {
      "target": "lines 140-144",
      "replacement": "if pos.ters_rejim_sayaci >= 20 and pnl < 0: close_position()"
    }
  ],
  "constraints_check": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "mode": "CROSS",
    "stop_net": "-10$"
  }
}
```

## ops
```json
{
  "file": "bot/v9/motor.py",
  "changes": [
    {
      "target": "Poz dataclass",
      "action": "add_field",
      "field": "ters_rejim_sayaci: int = 0"
    },
    {
      "target": "_izle method",
      "action": "update_logic",
      "logic": "if rejim_ters: poz.ters_rejim_sayaci += 1 else: poz.ters_rejim_sayaci = 0"
    },
    {
      "target": "lines 140-144",
      "action": "replace_condition",
      "old": "rejim_karsi_cikis_sn == 120 and rejim_ters and pnl < 0",
      "new": "poz.ters_rejim_sayaci >= 20 and pnl < 0"
    }
  ],
  "constraints_check": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "mode": "CROSS",
    "stop": "-10$"
  }
}
```