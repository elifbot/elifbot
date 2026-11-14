## mimar
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
  "constraints_validation": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "mode": "CROSS",
    "position_limit": "NONE",
    "stop_loss": "-10$"
  }
}
```

## risk_subayi
```json
{
  "risk_assessment": {
    "status": "APPROVED",
    "veto": false,
    "worst_case_scenario": "En kötü durumda kasa, her pozisyon için tanımlanan net -10$ stop limitine sadık kaldığı sürece, eşzamanlı açık pozisyon sayısı kadar risk taşır. Önerilen değişiklik (ters_rejim_sayaci >= 20) çıkış süresini uzattığı için, fiyatın stop noktasına ulaşma ihtimalini artırır ancak stop miktarı sabit (-10$) olduğu için kasa üzerindeki maksimum tekil işlem kaybı değişmez. Toplam risk, açık pozisyon sayısı * 10$ olarak kalır.",
    "compliance_check": {
      "kasa": "1000$ (SABİT)",
      "teminat": "50$ (SABİT)",
      "leverage": "10x (SABİT)",
      "margin_mode": "CROSS (SABİT)",
      "stop_loss": "-10$ (SABİT)"
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
        "target": "lines 140-144",
        "action": "REPLACE_CONDITION",
        "old_condition": "rejim_karsi_cikis_sn > 120 and rejim_ters and pnl < 0",
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
      "replacement": "if poz.ters_rejim_sayaci >= 20 and poz.pnl < 0: kapat_pozisyon()"
    }
  ],
  "constraints_check": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "mode": "CROSS",
    "position_limit": "NONE",
    "stop_loss": "-10$"
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
      "replacement": "if poz.ters_rejim_sayaci >= 20 and pnl < 0: close_position()"
    }
  ],
  "constraints_validation": {
    "equity": "1000$",
    "margin": "50$",
    "leverage": "10x",
    "mode": "CROSS",
    "position_limit": "NONE",
    "stop_loss": "-10$"
  },
  "test_engineer_note": "REJIM_DONUS çıkışı zaman bazlı (120sn) tetikleyiciden, durum bazlı (sayaç >= 20) teyide bağlanmıştır. Kanıtlanamayan her türlü iyileştirme reddedilmiştir."
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
  "constraints_validation": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "margin_mode": "CROSS",
    "position_limit": "NONE",
    "net_stop": "-10$"
  },
  "analyst_note": "Örneklem (n=44) < 100 olduğu için bu değişiklik bir 'yön göstergesi' olarak değerlendirilmelidir. Mevcut durumda 44 işlemin 36'sının (%81.8 WR) anlık rejim dönüşüyle kapanması, yüksek komisyon maliyetine (24.66$) yol açmaktadır. Teyit mekanizması (sayac >= 20) ile PF ve maksDD üzerindeki etkisi izlenmelidir."
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
      "target": "_izle function",
      "action": "update_logic",
      "logic": "if rejim_ters: poz.ters_rejim_sayaci += 1 else: poz.ters_rejim_sayaci = 0"
    },
    {
      "target": "lines 140-144",
      "action": "replace_condition",
      "old_condition": "rejim_karsi_cikis_sn > 120 and rejim_ters and pnl < 0",
      "new_condition": "poz.ters_rejim_sayaci >= 20"
    }
  ],
  "constraints_verified": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "margin_mode": "CROSS",
    "position_limit": "NONE",
    "stop_loss": "-10$"
  }
}
```