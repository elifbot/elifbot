## mimar


## risk_subayi
Risk subayı olarak raporu ve yama talebini inceledim.

**RİSK ANALİZİ:**
Sistemde 1.000$ kasa ile 50$ teminat ve 10x kaldıraç (500$ pozisyon büyüklüğü) kullanılıyor. CROSS modunda olduğumuz için tasfiye mesafesi tüm kasa üzerinden hesaplanır.
*   **Tek Pozisyon Tasfiye Mesafesi:** 1.000$ / 500$ = %200 (Fiyatın ters yönde %200 gitmesi gerekir, ancak 10x kaldıraçta izole stop %10'dur).
*   **Korelasyon Riski:** 6 botun aynı anda aynı yöne pozisyon açtığı "worst-case" senaryoda toplam risk 3.000$ notional büyüklüğe ulaşır.
*   **En Kötü Durumda Kasa Ne Olur?**
    Her pozisyonun net -10$ stop ile kapandığı ve 6 botun aynı anda stop olduğu senaryoda kasa **-60$** (komisyonlar hariç) daralır. Bu, kasanın %6'sına tekabül eder. Kabul edilebilir risk sınırları içerisindedir.

**VETO DURUMU:** Yama, kural sayılarını (1000, 50, 10x, -10$) değiştirmediği ve sadece çıkış mantığını (exit logic) optimize ettiği için **ONAYLANDI**.

---

### YAMA PLANI (motor.py)

**Karar 1:** `REJIM_DONUS` çıkışlarını hemen tetiklemek yerine, ters rejimde kalma süresini/sayısını ölçen bir mekanizmaya bağla.
**Karar 2:** Sadece `pnl < 0` ve `sayaç >= 3` (teyit) durumunda kapatma işlemini gerçekleştir.

#### Parça 1: Pozisyon Veri Yapısına Sayaç Ekleme
`Poz` dataclass'ına (veya ilgili sınıf tanımına) sayaç alanı eklenir.

**eski_kod:**
```python
@dataclass
class Poz:
    symbol: str
    side: str
    entry: float
    stop: float
    qty: float
```
**yeni_kod:**
```python
@dataclass
class Poz:
    symbol: str
    side: str
    entry: float
    stop: float
    qty: float
    regime_flip_count: int = 0  # Ters rejim teyit sayacı
```

#### Parça 2: İzleme Döngüsünde Sayacı Güncelleme
`_izle` metodu içerisinde, rejim ters döndüğünde sayacı artır, rejim düzeldiğinde sıfırla.

**eski_kod:**
```python
# _izle içinde rejim kontrolü kısmı
if current_regime != pos.regime:
    # rejim değişimi tespit edildi
```
**yeni_kod:**
```python
# _izle içinde rejim kontrolü kısmı
if current_regime != pos.regime:
    pos.regime_flip_count += 1
else:
    pos.regime_flip_count = 0
```

#### Parça 3: Kapatma Koşulunu Sayaca Bağlama
`motor.py` satır 140-144 arasındaki agresif kapatma mantığı, teyit sayacına bağlanır.

**eski_kod:**
```python
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    if current_regime != pos.regime and pos.pnl < 0:
        return "REJIM_DONUS"
```
**yeni_kod:**
```python
if time.time() - pos.open_time > rejim_karsi_cikis

## icra
**'Kağıtta çalışır' ile 'borsada çalışır' arasındaki fark:**
Kağıtta (paper), emir gönderildiği an limit fiyattan dolmuş kabul edilir veya basit bir simülatörle (`MakerFillSimulator`) eşleştirilir. Borsada ise; emrin deftere yazılması, öncelik sırası, kısmi dolumlar, kayma (slippage), borsa reddi ve ağ gecikmesi vardır. Kağıtta "anlık" olan işlem, borsada "belirsiz süreli bir bekleyiş" ve "fiyat sapması"dır.

**Soru Cevabı:**
Gerçek parada en pahalıya patlayan hata sınıfı **kayma (slippage)** ve **kısmi dolumların** yönetilememesidir. Özellikle stop-loss emirlerinde gerçekleşen yüksek kayma, matematiksel olarak hesaplanan net -10$ stop limitini hızla aşarak kasayı eritir.

---

**YAMA: motor.py (REJIM_DONUS Teyit Mekanizması)**

**1. Parça: Poz Dataclass Güncellemesi**
```python
# eski_kod:
# @dataclass
# class Poz:
#     ... (mevcut alanlar)

# yeni_kod:
@dataclass
class Poz:
    # ... (mevcut alanlar)
    regime_flip_count: int = 0
```

**2. Parça: _izle İçinde Sayaç Güncelleme**
```python
# eski_kod:
# if rejim_ters_dondu:
#     # rejim kontrol mantığı

# yeni_kod:
if rejim_ters_dondu:
    poz.regime_flip_count += 1
```

**3. Parça: Kapatma Koşulunun Sayaca Bağlanması**
```python
# eski_kod:
# if (time.time() - poz.acilis_zamani) > rejim_karsi_cikis_sn and rejim_ters_dondu and pnl < 0:
#     return "REJIM_DONUS"

# yeni_kod:
if (time.time() - poz.acilis_zamani) > rejim_karsi_cikis_sn and poz.regime_flip_count >= 3 and pnl < 0:
    return "REJIM_DONUS"
```

**Kararlar:**
1. Teyit eşiği `regime_flip_count >= 3` olarak belirlendi (gürültüyü önlemek için).
2. `regime_flip_count` alanı `Poz` sınıfına varsayılan `0` ile eklendi.

## test
### TEST MÜHENDİSİ RAPORU

**Sistem Durumu:**
*   **Kasa:** 1.000 $ | **Teminat:** 50 $ | **Kaldıraç:** 10x | **Mod:** CROSS
*   **Stop:** -10 $ (Net)
*   **Mevcut Performans:** WR %15.9 | PF 0.676 (Kritik Churn)
*   **Hata Kaynağı:** `bot/v9/motor.py` (Satır 140-144) - Erken `REJIM_DONUS` çıkışı.

**Veri Hattı Analizi (Kanıt Demeti):**
*   **Tick Kalitesi:** `executor.py:206` ve `v5.1` kanıtlarında `data_integrity.record_tick` ile tick bazlı kayıt yapıldığı görülmektedir.
*   **Sentetik-Gerçek Ayrımı:** `executor.py:251` (v5.0 düzeltmesi) kanıtı, dolum simülasyonunun "GERÇEK tick baz hacmiyle" beslendiğini, hacim filtresinin yalnızca sinyali iptal ettiğini, ölçülen hacmin gerçek olduğunu kanıtlar.
*   **Replay Tutarlılığı:** `test_v52_hardening.py:1850` kanıtı, izleme (probe) açık/kapalıyken aynı sonucun verildiğini (`test_probe_does_not_change_result`) kanıtlar.

---

### YAMA PLANI (MOTOR.PY)

`REJIM_DONUS` çıkışını, rejim ters döndükten sonraki tik sayısına bağlayarak "gürültü" kaynaklı kapanışları engellemek için aşağıdaki 3 parçalı yama uygulanacaktır.

#### Parça 1: Pozisyon Veri Yapısının Güncellenmesi
`Poz` dataclass'ına ters rejim sayacı eklenir.

**eski_kod:**
```python
@dataclass
class Poz:
    symbol: str
    side: str
    entry_price: float
    # ... diğer alanlar
```

**yeni_kod:**
```python
@dataclass
class Poz:
    symbol: str
    side: str
    entry_price: float
    # ... diğer alanlar
    regime_flip_count: int = 0
```

#### Parça 2: İzleme Mantığının Güncellenmesi
`_izle` metodu içinde, rejim ters döndüğünde sayaç artırılır; rejim düzeldiğinde sayaç sıfırlanır.

**eski_kod:**
```python
    def _izle(self, poz, current_regime):
        # ... mevcut izleme mantığı
        pass
```

**yeni_kod:**
```python
    def _izle(self, poz, current_regime):
        # ... mevcut izleme mantığı
        if current_regime == poz.opposite_regime:
            poz.regime_flip_count += 1
        else:
            poz.regime_flip_count = 0
```

#### Parça 3: Kapatma Koşulunun Teyide Bağlanması
`motor.py` satır 140-144 arasındaki anlık kapatma mantığı, sayacın belirli bir eşiği (örn: 3 tik) geçme şartına bağlanır.

**eski_kod:**
```python
        if time_since_entry > self.config.rejim_karsi_cikis_sn:
            if current_regime == poz.opposite_regime and pnl < 0:
                self._kapat(poz, "REJIM_DONUS")
```

**yeni_kod:**
```python
        if time_since_entry > self.config.rejim_karsi_cikis_sn:
            if

## olcum


## ops
Operasyonel gereksinimler ve `motor.py` üzerindeki churn (yüksek işlem kaybı) tanısı doğrultusunda, `REJIM_DONUS` çıkışlarını teyide bağlayan yama aşağıdadır.

### 1. Parça: Pozisyon Veri Yapısının Güncellenmesi
`Poz` dataclass'ına, rejim ters dönme olaylarını sayacak olan `regime_flip_count` alanı eklenir.

**eski_kod:**
```python
@dataclass
class Poz:
    # ... mevcut alanlar ...
    entry_time: float
    # ...
```

**yeni_kod:**
```python
@dataclass
class Poz:
    # ... mevcut alanlar ...
    entry_time: float
    regime_flip_count: int = 0  # Rejim ters dönme sayacı
    # ...
```

---

### 2. Parça: İzleme Döngüsünde Sayacın Güncellenmesi
`_izle` metodu içerisinde, mevcut rejim ile pozisyonun yönü karşılaştırılır; rejim ters döndüğünde sayaç artırılır.

**eski_kod:**
```python
# _izle metodu içinde rejim kontrolü yapılan kısım
if current_regime != poz.regime:
    # rejim değişimi tespit edildi
```

**yeni_kod:**
```python
# _izle metodu içinde rejim kontrolü yapılan kısım
if current_regime != poz.regime:
    poz.regime_flip_count += 1
    # rejim değişimi tespit edildi
```

---

### 3. Parça: Kapatma Koşulunun Teyide Bağlanması
`motor.py` satır 140-144 arasındaki agresif kapatma mantığı, sayacın belirli bir eşiği (örneğin 2) geçmesi şartına bağlanarak "churn" engellenir.

**eski_kod:**
```python
if (time.time() - poz.entry_time) > rejim_karsi_cikis_sn:
    if current_regime != poz.regime and poz.pnl < 0:
        return "REJIM_DONUS"
```

**yeni_kod:**
```python
if (time.time() - poz.entry_time) > rejim_karsi_cikis_sn:
    # Sadece rejim 2 veya daha fazla kez ters dönmüşse ve PnL negatifse kapat
    if current_regime != poz.regime and poz.pnl < 0 and poz.regime_flip_count >= 2:
        return "REJIM_DONUS"
```

**Operasyonel Not:** 7/24 ayakta kalma için asgari gereksinim; `RestartRecovery` (bayat emir iptali + stop restore), `LiveMirror` (emir eşleme) ve `EmergencyController` (kill switch) üçlüsünün aktif olmasıdır.