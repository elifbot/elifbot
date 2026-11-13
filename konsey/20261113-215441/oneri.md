## mimar


## risk_subayi


## icra


## test
Test mühendisi şapkasıyla; v9 smoke test sonuçları (WR %15.9, PF 0.676) sistemin şu anki haliyle "negatif beklentili" olduğunu ve yüksek churn (işlemlerin %81'i REJIM_DONUS) nedeniyle komisyonların kârı erittiğini kanıtlıyor. 

Sinyal kalitesi düşük, çıkış mekanizması ise çok hassas (gürültüye duyarlı). "Kanıtlanamıyorsa yoktur" ilkesiyle, sadece gerçek kod yapısına ve sağlanan veri demetine dayalı 4 somut yama önerim aşağıdadır:

### Yama 1: REJIM_DONUS Çıkışına Teyit Mekanizması (Churn Azaltma)
**Sorun:** İşlemlerin %81'i rejim dönüşüyle kapanıyor. Anlık bir mum kapanışı veya fiyat hareketi "rejim değişti" sinyali vererek pozisyonu erken kapatıyor (churn).
**Kanıt:** `v9 smoke` verisi: `REJIM_DONUS 36 / STOP 8`.
**Öneri:** `rejim.py` içerisinde rejim değişimini tek bir mum yerine, ardışık 2 mum veya bir eşik değer (threshold) teyidine bağla.

*   **Dosya:** `rejim.py`
*   **eski_kod:** `if current_regime != previous_regime: return True` (Temsili - mantıksal akış)
*   **yeni_kod:** 
    ```python
    # Rejim dönüşü için 2 mumluk teyit veya momentum eşiği ekle
    if current_regime != previous_regime and self.regime_confirm_count >= 2:
        return True
    self.regime_confirm_count += 1 if current_regime != previous_regime else 0
    ```

### Yama 2: Giriş Sinyali Filtresi (Sıklık Azaltma)
**Sorun:** WR %15.9 çok düşük. Sistem her volatilite artışını giriş fırsatı olarak görüyor.
**Kanıt:** `executor.py:1012-1018` ve `957-963` satırlarındaki `_rvol` ve `_impulse` hesaplamaları, hacim ve fiyat değişimini anlık ölçüyor.
**Öneri:** `sinyaller.py` içerisinde, giriş sinyalini sadece `_rvol` (Relative Volume) belirli bir standart sapmanın üzerindeyken aktif et.

*   **Dosya:** `sinyaller.py`
*   **eski_kod:** `if signal_detected: return True`
*   **yeni_kod:** 
    ```python
    # Sadece hacim anomalisi (rvol > 2.0) varsa girişe izin ver
    if signal_detected and current_rvol > 2.0: 
        return True
    ```

### Yama 3: Stop Mesafesi ve Komisyon Optimizasyonu
**Sorun:** Pozisyon başına net -10$ stop var, ancak işlem başına 0.50$ komisyon ödeniyor. %15.9 WR ile komisyonlar toplam kasanın ciddi bir kısmını (24.66$) götürüyor.
**Kanıt:** `v9 smoke` verisi: `komisyon 24.66$`, `en kötü -6.02$`.
**Öneri:** `motor.py` içerisinde stop tetikleyicisini, komisyon maliyetini absorbe edecek şekilde "hard stop" yerine "trailing stop" veya "breakeven" (başabaş) noktasına taşıma mantığı ekle.

*   **Dosya:** `bot/v9/motor.py`
*   **eski_kod:** `if current_pnl <= -10: close_position()`
*   **yeni_kod:**

## olcum
Analiz sonuçları: Örneklem (44 işlem) < 100 olduğu için bu veriler bir **'yön göstergesi'**dir. 
**Mevcut Durum:** WR %15.9 ve PF 0.676 ile sistem zarar etmektedir. En kritik sorun, işlemlerin %81'inin `REJIM_DONUS` ile kapanmasıdır (yüksek churn). Bu durum, kârın realize edilemeden veya stopa gelmeden "rejim değişti" denilerek erken kapatıldığını, komisyonların (işlem başı 0.50$) ise kârlılığı erittiğini gösteriyor.

Değişmez kurallar (1000$ kasa, 50$ teminat, 10x, -10$ stop) korunduğu sürece, churn'ü azaltacak ve çıkışları kanıta bağlayacak 4 somut yama önerisi aşağıdadır:

### 1. Yama: REJIM_DONUS Çıkışına Teyit Mekanizması (Churn Azaltma)
Anlık rejim değişikliği yerine, fiyatın rejim sınırını belirli bir mesafe (ATR bazlı) aşmasını veya belirli bir süre orada kalmasını şart koşan bir teyit eklenmelidir.
*   **Dosya:** `rejim.py`
*   **eski_kod:** `if current_regime != previous_regime: return "REJIM_DONUS"` (Temsili/Mantıksal)
*   **yeni_kod:** 
```python
# Rejim dönüşü için ATR tabanlı eşik kontrolü ekle
if current_regime != previous_regime:
    if abs(price - regime_boundary) > (atr * 0.2): # %20 ATR teyit sınırı
        return "REJIM_DONUS"
    return "HOLD"
```

### 2. Yama: Kâr Taşıma ve BE (Break-Even) Optimizasyonu
`risk.py` içerisindeki trailing stop mantığı, komisyon maliyetini (0.50$) karşılayacak şekilde "floor" (taban) değerine bağlanmalıdır. Mevcut kodda `pnl > 0` anında stop taşınmakta, bu da küçük dalgalanmalarda komisyonla beraber zararla kapanmaya yol açmaktadır.
*   **Dosya:** `risk.py`
*   **eski_kod:** 
```python
if pnl > 0 and trail_stop >= pos.entry:
    candidate = max(trail_stop, floor)
    if candidate > pos.stop:
        pos.stop = candidate
```
*   **yeni_kod:**
```python
# Komisyon maliyeti (0.50$) ve minimum kâr eşiği eklenmiş BE
if pnl > (0.50 * 2) and trail_stop >= (pos.entry + commission_buffer):
    candidate = max(trail_stop, floor)
    if candidate > pos.stop:
        pos.stop = candidate
```

### 3. Yama: Stop Mesafesinin Maliyetle Uyumu (Net -10$ Koruma)
Sistemde net -10$ stop kuralı vardır. Ancak `risk.py`'daki `ATR+SWING` stopları, bazen bu bütçeyi aşabilir veya çok dar kalıp komisyonla beraber anlamlandırılamaz hale gelebilir. Stopun, net risk bütçesini aşmadığından emin olan bir "hard-cap" eklenmelidir.
*   **Dosya:** `risk.py`
*   **eski_kod:**
```python
structure_stop = float(swing_low) - atr * float(structure_buffer_atr)
if structure_stop > 0 and structure_stop < stop:
    stop, source = structure_stop, "ATR+SWING"
```
*   **yeni_kod:**
```python
structure_stop = float(swing_low

## ops
Operasyonel sorumluluk kapsamında, 7/24 ayakta kalma için asgari gereksinimler ve sistem iyileştirme yamaları aşağıdadır.

### 1. Operasyonel Asgari Gereksinimler (7/24 Ayakta Kalma)
Kanıt demetine göre, bir botun kesintisiz çalışması için gereken minimum yapı şudur:
*   **Kopma ve Yeniden Başlatma:** `RestartRecovery` mekanizması (başlangıçta bayat emir iptali ve stop restore işlemleri için).
*   **Durum Yönetimi:** `store.save_mirror_state` ve `load_mirror_state` ile mirror durumunun kalıcı hale getirilmesi.
*   **Kill Switch / Güvenlik:** `EmergencyController` ve `fail-closed` (anahtar yoksa eşleme başlatmama) mantığı.
*   **Log ve Gözlem:** `logging.Formatter` ile standart çıktı ve `log ROTASYONU` (dosyanın sınırsız büyümesini önlemek için).
*   **Alarm:** `runtime_supervision` üzerinden `alarms` takibi ve `operational_health` (feed lag ve ledger status) izlemesi.

---

### 2. Sistem İyileştirme Yamaları (v9 Motor/Rejim/Sinyal)

Veriler; yüksek churn (%81 REJIM_DONUS) ve düşük WR (%15.9) ile komisyonun kârı erittiğini göstermektedir.

#### Yama 1: Rejim Dönüş Teyidi (Churn Azaltma)
**Dosya:** `rejim.py`
**Amaç:** Anlık rejim değişimini değil, X bar boyunca kalıcılığı teyit ederek erken çıkışları engellemek.
*   **eski_kod:** `if current_regime != previous_regime: return REJIM_DONUS` (Temsili)
*   **yeni_kod:** `if current_regime != previous_regime and regime_duration >= 3: return REJIM_DONUS`

#### Yama 2: Giriş Sinyali Filtresi (Sıklık Azaltma)
**Dosya:** `sinyaller.py`
**Amaç:** Sinyal sıklığını azaltmak için hacim ve RVOL filtresini giriş şartına bağlamak.
*   **eski_kod:** `if signal == "LONG": return True` (Temsili)
*   **yeni_kod:** `if signal == "LONG" and volume > base_volume and rvol < 3.0: return True`

#### Yama 3: Stop Mesafesi ve Maliyet Optimizasyonu
**Dosya:** `motor.py`
**Amaç:** -10$ stop'u, 0.50$ komisyon maliyetiyle uyumlu hale getirmek için "hard stop" yerine "trailing stop" veya "breakeven" tetikleyicisi eklemek.
*   **eski_kod:** `if pnl <= -10: close_position()`
*   **yeni_kod:** `if pnl >= 2: move_stop_to_breakeven(); if pnl <= -10: close_position()`

#### Yama 4: Çıkış Kanıtı Bağlama (Sinyal Teyidi)
**Dosya:** `rejim.py`
**Amaç:** REJIM_DONUS çıkışını sadece rejimle değil, ters yönlü bir sinyal oluşumuyla (kanıt) birleştirmek.
*   **eski_kod:** `if regime_changed: return CLOSE`
*   **yeni_kod:** `if regime_changed and opposite_signal_detected: return CLOSE`