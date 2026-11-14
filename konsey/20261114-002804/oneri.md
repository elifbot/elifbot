## mimar
```json
{
  "yama": {
    "1": {
      "dosya": "bot/v9/motor.py",
      "islem": "Poz dataclass'ına 'ters_rejim_sayaci: int = 0' alanı eklendi."
    },
    "2": {
      "dosya": "bot/v9/motor.py",
      "islem": "_izle fonksiyonu içinde: if rejim == TERS: pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0"
    },
    "3": {
      "dosya": "bot/v9/motor.py:140-144",
      "islem": "Kapatma koşulu 'rejim_karsi_cikis_sn' ve 'pnl < 0' kontrolünden 'pos.ters_rejim_sayaci >= 20' olarak değiştirildi."
    }
  },
  "risk_kontrol": {
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
  "karar": "ONAYLANDI",
  "risk_analizi": {
    "en_kotu_durum": "Kasa kaybı değişmez; stop-loss -10$ olarak sabit kaldığı için maksimum risk pozisyon başına -10$ + komisyonla sınırlıdır. Yama sadece çıkış zamanlamasını optimize eder, teminat fiziğini bozmaz.",
    "teminat_kontrol": "1000$ Kasa / 50$ Teminat / 10x / CROSS / -10$ Stop kurallarına sadık kalındı."
  },
  "yama": [
    {
      "dosya": "bot/v9/motor.py",
      "satir": "dataclass Poz",
      "islem": "ters_rejim_sayaci: int = 0 alanını ekle"
    },
    {
      "dosya": "bot/v9/motor.py",
      "satir": "_izle",
      "islem": "if rejim_ters: pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0"
    },
    {
      "dosya": "bot/v9/motor.py",
      "satir": "140-144",
      "islem": "Kapatma koşulunu 'pos.ters_rejim_sayaci >= 20 and pnl < 0' olarak güncelle"
    }
  ]
}
```

## icra
```json
{
  "yama": {
    "bot/v9/motor.py": [
      {
        "islem": "ekle",
        "hedef": "Poz dataclass",
        "kod": "ters_rejim_sayaci: int = 0"
      },
      {
        "islem": "degistir",
        "hedef": "_izle",
        "kod": "if rejim_ters: poz.ters_rejim_sayaci += 1\nelse: poz.ters_rejim_sayaci = 0"
      },
      {
        "islem": "degistir",
        "hedef": "satır 140-144",
        "kod": "if poz.ters_rejim_sayaci >= 20 and pnl < 0: kapat()"
      }
    ]
  },
  "kanit": "bot/v9/motor.py:satır 140-144",
  "parametreler": {
    "kasa": "1000$",
    "teminat": "50$",
    "kaldiraç": "10x",
    "mod": "CROSS",
    "stop": "-10$"
  }
}
```

## test
```json
{
  "yama": {
    "1": {
      "dosya": "bot/v9/motor.py",
      "islem": "Poz dataclass'ına 'ters_rejim_sayaci: int = 0' alanı eklendi."
    },
    "2": {
      "dosya": "bot/v9/motor.py",
      "islem": "_izle fonksiyonu içinde: if rejim_ters: poz.ters_rejim_sayaci += 1 else: poz.ters_rejim_sayaci = 0"
    },
    "3": {
      "dosya": "bot/v9/motor.py",
      "islem": "Satır 140-144 arası kapatma koşulu 'if poz.ters_rejim_sayaci >= 20 and pnl < 0:' olarak güncellendi."
    }
  },
  "kanit": "bot/v9/motor.py:140-144",
  "parametreler": {
    "kasa": "1000$",
    "teminat": "50$",
    "kaldiraç": "10x",
    "mod": "CROSS",
    "stop": "-10$"
  }
}
```

## olcum
```json
{
  "yama": {
    "1": "bot/v9/motor.py:Poz dataclass -> ters_rejim_sayaci: int = 0",
    "2": "bot/v9/motor.py:_izle -> if rejim_ters: pos.ters_rejim_sayaci += 1 else: pos.ters_rejim_sayaci = 0",
    "3": "bot/v9/motor.py:satır 140-144 -> if pos.ters_rejim_sayaci >= 20 and pnl < 0: close_position()"
  },
  "kanit": "bot/v9/motor.py:satır 140-144",
  "risk_parametreleri": {
    "kasa": "1000$",
    "teminat": "50$",
    "kaldiraç": "10x",
    "mod": "CROSS",
    "stop_net": "-10$"
  }
}
```

## ops
```json
{
  "yama": [
    {
      "dosya": "bot/v9/motor.py",
      "islem": "ekle",
      "hedef": "Poz dataclass",
      "kod": "ters_rejim_sayaci: int = 0"
    },
    {
      "dosya": "bot/v9/motor.py",
      "islem": "guncelle",
      "hedef": "_izle",
      "kod": "if rejim_ters: poz.ters_rejim_sayaci += 1\nelse: poz.ters_rejim_sayaci = 0"
    },
    {
      "dosya": "bot/v9/motor.py",
      "islem": "degistir",
      "satir": "140-144",
      "kod": "if poz.ters_rejim_sayaci >= 20 and pnl < 0: kapat()"
    }
  ],
  "kanit": "bot/v9/motor.py:140-144",
  "parametreler": {
    "kasa": "1000$",
    "teminat": "50$",
    "kaldiraç": "10x",
    "mod": "CROSS",
    "stop": "-10$"
  }
}
```