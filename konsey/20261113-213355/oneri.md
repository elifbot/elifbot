## mimar
Sistem analizi tamamlandı. Mevcut WR (%15.9) ve PF (0.676) değerleri, sistemin gürültüye karşı savunmasız olduğunu ve stop mesafesinin maliyetle uyumsuz olduğunu kanıtlıyor.

### 1. Churn Azaltma (Sinyal Filtreleme)
Mevcut sistemde sinyal sayısı çok yüksek. Kanıtlar, "Cascade" (tasfiye zinciri) eşiğinin isabet oranını dramatik şekilde artırdığını gösteriyor.

*   **Kanıt:** `futures_bot_v37/ws_bot.py:86-92` ve `futures_bot_v34/ws_bot.py:85-91`. Eşik 3 (son 60 saniyede 3 sinyal) kullanıldığında isabet oranı %80.7'ye çıkıyor ve bootstrap testleri %0 negatif sonuç veriyor.
*   **Yama:** Sinyal katmanına `CASCADE_THRESHOLD = 3` filtresi ekle.

### 2. REJIM_DONUS Çıkış Kanıtı ve Optimizasyonu
`REJIM_DONUS` çıkışlarının %81'ini (36/44) oluşturması, pozisyonların hedef fiyata ulaşmadan strateji değişikliğiyle kapandığını gösterir.

*   **Kanıt:** `test_trading_system.py:1290-1296` (v1.1) ve `test_trading_system.py:1079-1085` (final). `executor.strategy`'nin `LONG`'dan `HOLD`'a, ardından `trend_strategy`'nin `SHORT`'a dönmesi pozisyonu anında kapatır.
*   **Yama:** Sinyal motorunda `HOLD` durumuna geçişi, sadece karşıt sinyal geldiğinde değil, `impulse_pct` değerinin nötrleşmesi durumunda tetiklenecek şekilde geciktir.

### 3. Stop Mesafesi ve 0.50$ Maliyet Uyumu
Mevcut stop hesaplaması sabit yüzdeler üzerinden yapılıyor, bu da 500$ notional değerde -10$ net stop kuralını (yüzde 2) ihlal ediyor veya optimize etmiyor.

*   **Kanıt:** `ws_bot.py:1062-1068` (v4_v78) ve `ws_bot.py:981-987` (v37). Stoplar `self.sl_pct` veya `marj_bitis` üzerinden hesaplanıyor.
*   **Kanıt (Maliyet):** `ws_bot.py:1140-1146` (v4_v78). `net_0 = -pos.entry_fee - tahmini_cikis_ucreti` satırı, komisyonun net zarara eklendiğini kanıtlar.
*   **Yama:** Stop mesafesini sabit yüzdeden, `impulse_pct` tabanlı dinamik mesafeye çek. `test_trading_system.py:69-75`'teki `stop_distance_fraction = abs(signal.impulse_pct) / 100` mantığını uygula.

---

### Uygulanabilir Diff Önerileri

**Dosya:** `ws_bot.py`
**Fonksiyon:** `evaluate_signal` / `open_position`

```diff
--- a/ws_bot.py
+++ b/ws_bot.py
@@ -1062,7 +1062,8 @@
-        else:
-            stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
-                    else giris_fiyat * (1 + self.sl_pct / 100))
+        else:
+            # Net -10

## risk_subayi
Risk subayı olarak raporu inceledim. Mevcut veriler (WR %15.9, PF 0.676) sistemin "rastgele gürültüde stoplandığını" ve REJIM_DONUS çıkışlarının (işlemlerin %81'i) stratejik bir kanıta değil, muhtemelen zaman aşımı veya zayıf sinyale dayalı olduğunu gösteriyor.

**En kötü durumda kasa ne olur?**
Sınırsız pozisyon limiti olduğu için, korelasyon yönetimi olmazsa tüm kasa aynı yöne dönebilir. 100 eşzamanlı pozisyonun aynı anda stoplandığı bir senaryoda kasa **-1.000$ (sıfırlanma)** olur. Ancak mevcut stop kuralı (-10$) ile tekil işlem riski %1'dir.

İşte churn'ü azaltan ve stop mesafesini maliyetle uyumlu hale getiren yama önerileri:

### 1. Churn Azaltma: Yönsel Risk Filtresi (Veto Mekanizması)
Sınırsız pozisyon limiti, yüksek korelasyonlu paritelerde "cluster stop" riskini artırır. `executor.py` içindeki mevcut risk bütçesi kontrolünü aktif ederek churn'ü (gereksiz giriş-çıkış döngüsünü) azaltıyoruz.

**Dosya:** `executor.py`
**Diff:**
```python
# Satır 1323-1329 civarı (Mevcut kontrolü sıkılaştır)
- if open_risk+candidate_risk>pool_balance*policy.total_risk_fraction or side_risk+candidate_risk>pool_balance*policy.directional_risk_fraction:
+ # Kasa 1000$, Directional Risk %20 (200$) olarak set edilmeli
+ if side_risk + candidate_risk > 200.0: 
+     await self._say(f"⛔ {symbol}: Yönsel risk limiti doldu (Max 20 pozisyon/yön)")
```

### 2. REJIM_DONUS Kanıta Bağlama: Dinamik Çıkış Filtresi
REJIM_DONUS çıkışlarının %81 olması, botun "karar veremediği" için pozisyonu kapattığını gösterir. Bu çıkışları sadece volatilite artışı veya trend kırılımı kanıtına bağlamalıyız.

**Dosya:** `risk.py` (veya strateji çıkış fonksiyonu)
**Öneri:** `REJIM_DONUS` tetiklendiğinde, eğer mevcut PnL $\ge 0$ ise pozisyonu tut, sadece PnL $< 0$ ve sinyal tersine döndüyse kapat.
**Mantık:** `if exit_signal == "REJIM_DONUS" and current_pnl >= 0: continue # Pozisyonu koru`

### 3. Stop Mesafesi ve 0.50$ Maliyet Uyumu
Pozisyon başına net -10$ stop, 500$ notional (50$ x 10x) için %2'lik bir fiyat hareketine denk gelir. Komisyonlar (24.66$) toplam kârı eritiyor. Stop mesafesini "marj bazlı" sabitleyerek gürültüyü filtreliyoruz.

**Dosya:** `risk.py`
**Diff:**
```python
# Satır 249-255 (margin_stop_pct fonksiyonu)
- requested = (100.0 / lev) * self.margin_stop_fraction
+ # 50$ teminatın %20'si = 10$ net stop. 
+ # 10x kaldıraçta bu %2 fiyat hareketidir.
+ requested = 2.0 # Sabit %2 stop mesafesi
```

### Özet Uygulama Tablosu

| Sorun | Yama | Teknik Karşılık | Risk Etkisi

## icra
**Kağıtta Çalışır vs. Borsada Çalışır:**
Kağıtta çalışan sistem, `MakerFillSimulator` (paper.py:54) gibi idealize edilmiş dolum modelleri ve sabit slippage oranları kullanır; emirlerin anında veya belirlenen basit kurallarla dolduğunu varsayar. Borsada çalışan sistem ise; kısmi dolumlar, borsa reddi, `post-only` emirlerin anlık fiyat kaymasıyla iptal olması ve `fetch_order` (exchanges.py:1086) ile gerçekleşen asenkron onay süreçleri gibi deterministik olmayan gerçeklerle uğraşır.

**Yama Önerileri:**

**1. Churn Azaltma (Emir Yönetimi):**
*   **Sorun:** Yüksek churn, emirlerin hızlıca kurulup iptal edilmesinden kaynaklanıyor.
*   **Yama:** `exchanges.py` içerisinde `fetch_order` kontrolü yapan mekanizmayı, emir durumunu sadece "nihai dolum" için değil, "bekleyen/aktif" durumu için de optimize et.
*   **Diff:** `src/exchanges.py` -> `fetch_order` döngüsüne, emir durumu `open` ise belirli bir süre (timeout) boyunca `amend` (güncelleme) yapmadan bekleme mantığı ekle.

**2. REJIM_DONUS Kanıta Bağlama:**
*   **Sorun:** Çıkışların çoğu (`36/44`) REJIM_DONUS ile gerçekleşiyor ancak bu çıkışların tetikleyicisi belirsiz.
*   **Yama:** `exec/paper.py` içerisindeki `ORDER_CANCELED` loglama yapısını (`paper.py:310`), REJIM_DONUS tetiklendiğinde mevcut `live_price` ve `limit_price` farkını "Sinyal Kayması" olarak kaydedecek şekilde genişlet.
*   **Diff:** `exec/paper.py` -> `trades.append` kısmına `"exit_reason": "REJIM_DONUS", "price_diff": live_price - limit_price` alanlarını ekle.

**3. Stop Mesafesi ve 0.50$ Maliyet Uyumu:**
*   **Sorun:** Pozisyon başına -10$ stop, 500$ notional (10x) için %2'lik bir hareket demektir. Ancak komisyonlar (24.66$) ve slippage, bu mesafeyi daraltıyor.
*   **Yama:** `paper.py`'deki `max_loss_per_position` (paper.py:57) değerini, `taker_fee_rate` ve `stop_slippage_rate` (paper.py:55) toplamını düşerek "net stop" olarak hesapla.
*   **Diff:** `exec/paper.py` -> Stop hesaplama fonksiyonuna: `effective_stop = max_loss_per_position - (notional * (taker_fee_rate + stop_slippage_rate))` formülünü uygula.

**Özet Uygulama Planı:**
*   `src/exchanges.py`: `fetch_order` sonrası `status` kontrolü ile gereksiz emir iptallerini engelle.
*   `exec/paper.py`: `REJIM_DONUS` çıkışlarına fiyat farkı metriği ekle.
*   `exec/paper.py`: Stop mesafesini, komisyon maliyetini (0.50$ hedefi) önceden düşen "Net Stop" mantığına çek.

## test
Test mühendisi perspektifiyle, mevcut v9 smoke verileri (WR %15.9, PF 0.676) sistemin "rastgelelikten" kurtulmadığını ve yüksek churn (işlem sıklığı) nedeniyle komisyonların kârı erittiğini kanıtlıyor. 

**Analiz:** 
- **Churn:** `REJIM_DONUS` (36 işlem) baskın çıkış modu. Bu, sinyalin trendle değil, anlık gürültüyle (noise) tetiklendiğini ve hemen geri döndüğünü kanıtlar.
- **Stop:** -10$ stop, 500$ notional (10x) için %2'lik bir hareket demektir. Ancak komisyonlar (24.66$) toplam kârın büyük kısmını yutmuş.

İşte kanıtlara dayalı yama önerileri:

### 1. Churn Azaltma: Hacim Filtresi Sertleştirme
`executor.py` içerisindeki `_rvol` ve `_baseline_liquidity` fonksiyonları mevcut ancak sinyal tetikleme aşamasında "gerçek tick hacmi" ile "sinyal hacmi" arasındaki ayrım zayıf.

**Yama:** Sinyal girişine `_baseline_liquidity` tabanlı bir eşik ekle.
- **Dosya:** `app/executor.py`
- **Diff:**
```python
# Fonksiyon: process_signal (veya ilgili giriş kontrolü)
- if self._rvol(candles) > self.config.signal.rvol_threshold:
+ if self._rvol(candles) > self.config.signal.rvol_threshold and \
+    self._baseline_liquidity(symbol) > self.config.signal.min_baseline_vol:
```
*Kanıt: `drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/app/executor.py:895-901` (Baseline liquidity fonksiyonu mevcut ancak aktif kullanımı smoke verisinde düşük).*

### 2. REJIM_DONUS Çıkışını Kanıta Bağlama
`REJIM_DONUS` çıkışlarının %81'i (36/44) oluşturması, sistemin "momentum kaybını" yanlış ölçtüğünü gösterir. Çıkışı sadece fiyat hareketine değil, `turbo_engine.py`'daki taker buy/sell dengesine bağla.

**Yama:** Çıkış mantığına `buy_usd` / `delta_usd` oranını ekle.
- **Dosya:** `bot/acarbot_6bot/turbo_engine.py`
- **Diff:**
```python
# Fonksiyon: check_exit_conditions
- if current_regime != prev_regime: return REJIM_DONUS
+ if current_regime != prev_regime and (buy_usd / delta_usd if delta_usd > 0 else 0) < 0.3:
+     return REJIM_DONUS
```
*Kanıt: `bot/acarbot_6bot/turbo_engine.py:224-230` (Taker buy USD hesaplaması mevcut, ancak çıkış karar mekanizmasına entegre değil).*

### 3. Stop Mesafesi ve Maliyet Uyumu (0.50$ Maliyet)
Pozisyon başına -10$ stop sabit kuraldır. Ancak 500$ notional'da komisyonlar (entry+exit) yaklaşık 0.50$ - 1.00$ arasıdır. Stop mesafesini "net" hale getirmek için giriş anındaki `tick_size` doğrulamasıyla stop'u normalize et.

**Yama:** Stop'u fiyat bazlı değil, tick bazlı kesinleştir.
- **Dosya:** `app/executor.py`
- **Diff:**
```python
# Fonksiyon: place_order
- stop_price

## olcum
Örneklem (44 işlem) < 100 olduğu için bu analiz bir **'yön göstergesi'**dir.

**Mevcut Durum Analizi:**
*   **WR %15.9 / PF 0.676:** Sistem şu an zarar ediyor.
*   **Çıkış Dağılımı:** REJIM_DONUS (36) >> STOP (8). Bu, işlemlerin çoğunun stop olmadan, stratejik bir sinyal değişimiyle kapandığını ancak bu kapanışların kârlı olmadığını (PF < 1) gösterir.
*   **Churn:** Yüksek. Sık işlem açılıp REJIM_DONUS ile kapatılıyor, komisyonlar ($24.66) net kârı eritiyor.

### Yama Önerileri

#### 1. Churn Azaltma ve REJIM_DONUS Kanıtı
REJIM_DONUS çıkışları şu an "erken" veya "verimsiz" gerçekleşiyor. Kanıt demetindeki `trailing_stop` mekanizması (`risk.py:702-708` ve `748-754`) kârı korumak için var ancak REJIM_DONUS bu mekanizmayı bypass ediyor olabilir.

*   **Yama:** REJIM_DONUS sinyali geldiğinde, eğer pozisyon `_is_risk_free_position` (kanıt: `executor.py:719-725`) durumundaysa (stop girişin ötesindeyse), hemen kapatmak yerine stop'u `entry` seviyesine çekip trailing'e bırak.
*   **Diff (`src/executor.py`):**
    ```python
    # REJIM_DONUS tetiklendiğinde:
    if signal == "REJIM_DONUS" and self._is_risk_free_position(pos):
        pos.stop = pos.entry  # Kârı kilitle, trendin sonuna kadar bekle
        return "HOLD_UNTIL_STOP" 
    ```

#### 2. Stop Mesafesi ve 0.50$ Maliyet Uyumu
Sistemde net -10$ stop kuralı var. 50$ teminat x 10x = 500$ notional.
$10 / 500 = \%2$ stop mesafesi. 
Kanıtlar (`risk.py:312-318`), stopun `ATR+SWING` ile belirlendiğini gösteriyor. Eğer ATR bazlı stop %2'den genişse, -10$ kuralı ihlal edilir; darsa, churn artar.

*   **Yama:** `initial_stop` hesaplamasını, ATR'yi baz alacak şekilde ancak maksimum %2 (net -10$) ile sınırlayacak bir "hard-cap" mekanizmasına bağla.
*   **Diff (`src/risk.py`):**
    ```python
    # structure_stop hesaplamasından sonra:
    max_stop_dist = entry * 0.02 # 500$ notional için 10$
    if side == "LONG":
        stop = max(structure_stop, entry - max_stop_dist)
    else:
        stop = min(structure_stop, entry + max_stop_dist)
    ```

#### 3. Stop İhlali ve Kayma (Slippage) Önlemi
Kanıtlar (`paper.py:299-305`), limit emir dolarken fiyatın stopun ötesine geçebildiğini ("TERS SEÇİLİM") kanıtlıyor. Bu, gerçek verideki maksDD'yi artıran gizli etkendir.

*   **Yama:** `cancel_on_stop_breach_at_fill` parametresini `True` yap. Emir dolmadan önce fiyat stop seviyesini ihlal etmişse emri iptal et.
*   **Diff (`config/exit.yaml` veya ilgili config dosyası):**

## ops
Operasyonel sorumluluk çerçevesinde, verilen gerçek veriler ve kanıt demeti üzerinden churn'ü azaltmaya ve stop maliyetini optimize etmeye yönelik yama önerileri aşağıdadır.

### 1. Churn Azaltma: Likidite ve Hacim Filtresi Entegrasyonu
**Sorun:** Yüksek churn ve düşük WR (%15.9), botun düşük likiditeli veya aşırı volatil (şüpheli) sembollerde çok fazla işlem açtığını gösteriyor.
**Yama:** `main.py` içerisinde mevcut olan ancak aktif kullanılmayan "HACİM FİLTRESİ v5.0" mekanizması, giriş sinyali öncesine zorunlu bir kontrol olarak eklenmelidir.

*   **Dosya:** `app/main.py`
*   **Fonksiyon:** `check_signal()` veya `entry_logic()` (Sinyal değerlendirme döngüsü)
*   **Diff:**
```python
# Mevcut: if signal_detected: open_position()
# Yama:
if signal_detected:
    if current_volume < config.portfolio.min_volume_usdt_sec:
        logger.info("SİNYAL REDDEDİLDİ: LİKİDİTE DÜŞÜK")
        return None
    if rvol > config.portfolio.max_rvol_threshold:
        logger.warning("SİNYAL REDDEDİLDİ: RVOL ŞÜPHELİ")
        return None
    open_position()
```

### 2. REJIM_DONUS Çıkışını Kanıta Bağlama: Telemetri Kaydı
**Sorun:** Çıkışların %81'i (36/44) `REJIM_DONUS` ile gerçekleşiyor ancak bu çıkışların kârlılığı/nedeni ölçülmemiş.
**Yama:** `ws_bot.py` içerisindeki telemetri yapısı, her `REJIM_DONUS` tetiklendiğinde anlık piyasa durumunu (volatilite, trend yönü) CSV'ye yazacak şekilde genişletilmelidir.

*   **Dosya:** `aday/ws_bot.py`
*   **Fonksiyon:** `close_position()` veya `exit_logic()`
*   **Diff:**
```python
# Mevcut: log_exit(event)
# Yama:
if exit_reason == "REJIM_DONUS":
    with open(AKIS_KAPANIS_CSV, 'a') as f:
        f.write(f"{timestamp},{symbol},{pnl},{current_regime},{market_volatility}\n")
```

### 3. Stop Mesafesi ve Maliyet Uyumu (0.50$ Maliyet)
**Sorun:** Pozisyon başına -10$ stop kuralı sabitken, komisyonların (24.66$) toplam PnL'e oranı yüksek. 500$ notional işlemde, giriş-çıkış komisyonu yaklaşık 0.50$ - 1.00$ arasındadır. Stop mesafesi, komisyon maliyetini absorbe edecek şekilde "net" hesaplanmalıdır.
**Yama:** Stop tetikleyicisi, sadece fiyat hareketini değil, `realized_pnl - commissions` toplamını baz almalıdır.

*   **Dosya:** `app/main.py` (veya OKX/Binance emir yönetimi)
*   **Fonksiyon:** `monitor_stop_loss()`
*   **Diff:**
```python
# Mevcut: if current_pnl <= -10: close()
# Yama:
net_pnl = current_pnl - total_trade_commissions
if net_pnl <= -10.00: 
    # Komisyon dahil net zarar -10$ olduğunda kapat
    close_position(reason="STOP")
```

### Operasyonel Özet (7/24 Ayakta Kalma Asgarisi)
Kanıt demetindeki `RestartRecovery