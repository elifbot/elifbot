## mimar
```json
{
  "patch": [
    {
      "file": "bot/v9/motor.py",
      "action": "modify_dataclass",
      "target": "Poz",
      "changes": {
        "add_field": {
          "name": "ters_rejim_sayaci",
          "type": "int",
          "default": 0
        }
      }
    },
    {
      "file": "bot/v9/motor.py",
      "action": "modify_method",
      "target": "_izle",
      "logic": "if rejim == 'TERS': pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0"
    },
    {
      "file": "bot/v9/motor.py",
      "action": "replace_lines",
      "range": [140, 144],
      "old_condition": "if time_diff > 120 and rejim == 'TERS' and pnl < 0:",
      "new_condition": "if pos.ters_rejim_sayaci >= 20 and pnl < 0:"
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

## risk_subayi


## icra
```json
{
  "yama": {
    "dosya": "bot/v9/motor.py",
    "degisiklikler": [
      {
        "hedef": "Poz dataclass",
        "islem": "EKLE",
        "kod": "ters_rejim_sayaci: int = 0"
      },
      {
        "hedef": "_izle fonksiyonu",
        "islem": "MANTIK_EKLE",
        "kod": "if rejim_ters: poz.ters_rejim_sayaci += 1\nelse: poz.ters_rejim_sayaci = 0"
      },
      {
        "hedef": "satır 140-144 (kapatma koşulu)",
        "islem": "DEGISTIR",
        "eski_kosul": "pozisyon_suresi > 120 and rejim_ters and pnl < 0",
        "yeni_kosul": "poz.ters_rejim_sayaci >= 20"
      }
    ],
    "sabitler": {
      "kasa": "1000$",
      "teminat": "50$",
      "kaldiraç": "10x",
      "mod": "CROSS",
      "pozisyon_limiti": "YOK",
      "stop_loss": "-10$"
    }
  },
  "kanit_analizi": {
    "soru": "Hangi hata sınıfı gerçek parada pahalıya patlar?",
    "cevap": "veri yok"
  }
}
```

## test
```json
{
  "patch": {
    "file": "bot/v9/motor.py",
    "changes": [
      {
        "target": "Poz dataclass",
        "action": "add_field",
        "field": "ters_rejim_sayaci: int = 0"
      },
      {
        "target": "_izle method",
        "action": "insert_logic",
        "logic": "if rejim_ters: poz.ters_rejim_sayaci += 1 else: poz.ters_rejim_sayaci = 0"
      },
      {
        "target": "lines 140-144",
        "action": "replace_condition",
        "old_condition": "time_elapsed > 120 and rejim_ters and pnl < 0",
        "new_condition": "poz.ters_rejim_sayaci >= 20"
      }
    ],
    "constraints_validation": {
      "equity": "1000$",
      "margin": "50$",
      "leverage": "10x",
      "mode": "CROSS",
      "position_limit": "NONE",
      "stop_loss": "-10$"
    }
  },
  "evidence_check": {
    "data_pipeline_quality": "veri yok",
    "replay_consistency": "veri yok",
    "synthetic_vs_real_distinction": "veri yok"
  }
}
```

## olcum
```json
{
  "patch": {
    "file": "bot/v9/motor.py",
    "changes": [
      {
        "target": "Position dataclass",
        "action": "add_field",
        "field": "ters_rejim_sayaci: int = 0"
      },
      {
        "target": "_izle method",
        "action": "insert_logic",
        "logic": "if rejim_ters: pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0"
      },
      {
        "target": "lines 140-144",
        "action": "replace_condition",
        "old_condition": "time_elapsed > 120 and rejim_ters and pnl < 0",
        "new_condition": "pos.ters_rejim_sayaci >= 20"
      }
    ]
  },
  "constraints_validation": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "mode": "CROSS",
    "position_limit": "NONE",
    "net_stop": "-10$"
  }
}
```

## ops
