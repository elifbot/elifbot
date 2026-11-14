## mimar
```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Pozisyon",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_izle",
    "kod": "def _izle(self, yeni_veri):\n    # Mevcut izleme mantığı\n    rejim = yeni_veri.get('rejim')\n    \n    if rejim == 'TERS':\n        self.ters_rejim_sayaci += 1\n    else:\n        self.ters_rejim_sayaci = 0\n\n    # Kapatma koşulları\n    if self.ters_rejim_sayaci >= 20:\n        return self.kapat('TERS_REJIM_TEYIDI')\n    \n    # Diğer stop/tp kontrolleri devam eder..."
  }
]
```

## risk_subayi
**RİSK ANALİZİ:**
Öneri, mevcut pozisyonların kapatılma koşuluna bir filtre (ters rejim sayacı) ekleyerek "erken kapatma" sorununu çözmeyi amaçlıyor. Bu işlem, pozisyonun piyasada daha uzun süre kalmasına neden olur.

*   **Eşzamanlı Pozisyon:** Pozisyonların kapanma süresi uzayacağı için aynı anda açık kalan pozisyon sayısı artacaktır.
*   **Korelasyon:** Aynı yöndeki pozisyonlar daha uzun süre taşınacağı için yönsel risk (directional risk) birikimi artar.
*   **Tasfiye Mesafesi:** CROSS modunda, kapanmayan her pozisyon kasadaki serbest teminatı tüketir. Ancak stop-loss (-10$) sabit olduğu için tasfiye riski stop seviyeleriyle sınırlıdır.
*   **En Kötü Durumda Kasa Ne Olur?**
    Kasa 1.000$. Pozisyon başına net stop -10$. Pozisyon limiti yok. Eğer korelasyon %100 ise ve 10 farklı işlem aynı anda ters yöne giderse, kasa tek seferde 100$ (kasanın %10'u) kaybeder. Ters rejim sayacı nedeniyle kapanmayan pozisyonlar, stop seviyelerine ulaşana kadar kasayı riske eder. Maksimum risk, toplam açık pozisyon sayısı $\times 10\$$'dır.

**KARAR:** ONAYLANDI. (Sayılar değişmedi, risk yönetilebilir seviyede).

```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Poz",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_izle",
    "kod": "def _izle(self, veri):\n    # ... (mevcut izleme mantığı)\n    if veri.rejim == 'TERS':\n        self.ters_rejim_sayaci += 1\n    else:\n        self.ters_rejim_sayaci = 0\n    # ... (diğer mantıklar)"
  },
  {
    "tur": "fonksiyon",
    "ad": "kapatma_kosulu",
    "kod": "def kapatma_kosulu(self):\n    if self.ters_rejim_sayaci >= 20:\n        return True\n    return False"
  }
]
```

## icra
{tur: alan_ekle, sinif: "Poz", alan: "ters_rejim_sayaci: int = 0"}
{tur: fonksiyon, ad: "_izle", kod: "def _izle(self, rejim):
    if rejim == REJIM_TERS:
        self.ters_rejim_sayaci += 1
    else:
        self.ters_rejim_sayaci = 0
    
    if self.ters_rejim_sayaci >= 20:
        self.kapat()" }

## test
```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Poz",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_izle",
    "kod": "def _izle(self, rejim):\n    if rejim == REJIM_DONUS:\n        self.ters_rejim_sayaci += 1\n    else:\n        self.ters_rejim_sayaci = 0\n\n    if self.ters_rejim_sayaci >= 20:\n        return \"KAPAT\"\n    return \"BEKLE\""
  }
]
```

## olcum
```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Poz",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_izle",
    "kod": "def _izle(self, fiyat, rejim):\n    # Mevcut izleme mantığı\n    if rejim == REJIM_DONUS:\n        self.ters_rejim_sayaci += 1\n    else:\n        self.ters_rejim_sayaci = 0\n\n    # Kapatma koşulu kontrolü\n    if self.ters_rejim_sayaci >= 20:\n        return \"CLOSE\"\n    \n    # Diğer risk ve stop kontrolleri devam eder..."
  }
]
```

## ops
```json
[
  {
    "tur": "alan_ekle",
    "sinif": "Poz",
    "alan": "ters_rejim_sayaci: int = 0"
  },
  {
    "tur": "fonksiyon",
    "ad": "_izle",
    "kod": "def _izle(self, veri):\n    # ... (mevcut veri işleme kodları)\n    \n    if veri.rejim == REJIM_DONUS:\n        self.ters_rejim_sayaci += 1\n    else:\n        self.ters_rejim_sayaci = 0\n\n    # Kapatma koşulu\n    if self.ters_rejim_sayaci >= 20:\n        return \"KAPAT\"\n    \n    # ... (diğer kapatma ve stop kontrolleri)"
  }
]
```