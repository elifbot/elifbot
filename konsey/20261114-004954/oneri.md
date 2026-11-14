## mimar
```json
{
  "yama": {
    "dosya": "bot/v9/motor.py",
    "degisiklikler": [
      {
        "hedef": "Poz dataclass",
        "islem": "EKLE",
        "satir": "tanim_alani",
        "kod": "ters_rejim_sayaci: int = 0"
      },
      {
        "hedef": "_izle fonksiyonu",
        "islem": "GUNCELLE",
        "mantik": "if rejim == TERS: pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0",
        "kod": "if current_regime == opposite_regime:\n    pos.ters_rejim_sayaci += 1\nelse:\n    pos.ters_rejim_sayaci = 0"
      },
      {
        "hedef": "kapatma_kosulu",
        "islem": "DEGISTIR",
        "satir": "140-144",
        "eski_kod": "if time_elapsed > 120 and regime == TERS and pnl < 0:",
        "yeni_kod": "if pos.ters_rejim_sayaci >= 20 and pnl < 0:"
      }
    ],
    "risk_parametreleri": {
      "kasa": "1000$",
      "teminat": "50$",
      "kaldiraç": "10x",
      "mod": "CROSS",
      "stop_loss": "-10$"
    }
  }
}
```

## risk_subayi
```json
{
  "risk_assessment": {
    "status": "APPROVED",
    "worst_case_scenario": "En kötü durumda kasa, her pozisyon için tanımlanan net -10$ stop limitine sadık kaldığı sürece, açık pozisyon sayısı kadar lineer zarar eder. Önerilen yama, 'anında kapatma' yerine 'teyitli kapatma' (20 bar) getirdiği için, stop noktasına ulaşana kadar olan volatilite süresini uzatır ancak toplam risk bütçesini (pozisyon başına -10$) değiştirmez. Kasa üzerindeki maksimum baskı, stop tetiklenene kadar geçen süredeki yüzer zarardır.",
    "verification": {
      "margin": "50$",
      "leverage": "10x",
      "mode": "CROSS",
      "stop_per_pos": "-10$",
      "equity": "1000$"
    }
  },
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
        "action": "logic_update",
        "logic": "if rejim == 'TERS': pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0"
      },
      {
        "target": "lines 140-144",
        "action": "replace_condition",
        "old_condition": "time_elapsed > 120 and rejim == 'TERS' and pnl < 0",
        "new_condition": "pos.ters_rejim_sayaci >= 20 and pnl < 0"
      }
    ]
  }
}
```

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
        "kod": "if rejim == 'TERS': poz.ters_rejim_sayaci += 1\nelse: poz.ters_rejim_sayaci = 0"
      },
      {
        "hedef": "satır 140-144 (Kapatma Koşulu)",
        "islem": "DEGISTIR",
        "eski_kod": "if zaman > 120 and rejim == 'TERS' and pnl < 0: kapat()",
        "yeni_kod": "if poz.ters_rejim_sayaci >= 20 and pnl < 0: kapat()"
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
    "constraints_verification": {
      "equity": "1000$",
      "margin": "50$",
      "leverage": "10x",
      "mode": "CROSS",
      "position_limit": "NONE",
      "stop_loss": "-10$ net per position"
    }
  },
  "evidence_check": {
    "data_pipeline_query": "veri yok"
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
        "old": "if time_since_open > 120 and rejim_ters and pnl < 0:",
        "new": "if pos.ters_rejim_sayaci >= 20 and pnl < 0:"
      }
    ]
  },
  "constraints_validation": {
    "kasa": "1000$",
    "teminat": "50$",
    "leverage": "10x",
    "margin_mode": "CROSS",
    "position_limit": "NONE",
    "net_stop": "-10$"
  }
}
```

## ops
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
    "constraints_verified": {
      "kasa": "1000$",
      "teminat": "50$",
      "leverage": "10x",
      "mode": "CROSS",
      "position_limit": "NONE",
      "stop_loss": "-10$"
    }
  }
}
```