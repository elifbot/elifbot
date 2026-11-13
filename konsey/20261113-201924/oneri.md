## mimar
Sistem mimarı olarak, v9 smoke verisindeki düşük WR (%15.9) ve yüksek churn'ü (REJIM_DONUS baskınlığı) çözmek için aşağıdaki yamayı öneriyorum.

### 1. Analiz ve Kanıtlar

*   **Churn ve REJIM_DONUS:** Mevcut sistemde çıkışların %81.8'i (36/44) `REJIM_DONUS` ile gerçekleşiyor. Bu, sinyallerin trendle uyumsuz olduğunu ve rejim değiştiği anda (muhtemelen düşük kâr veya hafif zarar ile) pozisyonun kapatıldığını gösterir.
*   **Sinyal Kalitesi (Churn Azaltma):** `futures_bot_v37/ws_bot.py:86-117` kanıtı, "CASCADE EŞİĞİ" (tasfiye zinciri) kullanımının isabet oranını %60.1'den %86.3'e çıkardığını kanıtlar. Eşik 3 (60 sn'de 3 sinyal) seçilmiştir. Churn'ü azaltmak için rastgele sinyaller yerine bu "kümelenmiş" (cascade) sinyallerin zorunlu kılınması gerekir.
*   **Stop Mesafesi ve Maliyet:** 50$ teminat $\times$ 10x = 500$ notional. Pozisyon başına net -10$ stop hedefi, notional üzerinden %2'lik bir toplam kayba denk gelir. `test_trading_system.py:69-75` kanıtında `stop_distance_fraction`'ın `abs(signal.impulse_pct) / 100` olarak hesaplandığı görülmektedir. 0.50$ maliyet (komisyon) sonrası net -10$ kalması için stop mesafesinin dinamik olarak impulse'a bağlanması ancak sabit bir tavanla sınırlandırılması gerekir.

### 2. Yama Önerisi (Diff)

#### Yama A: Churn Azaltma (Cascade Filtresi Entegrasyonu)
Sinyal katmanına, sadece yüksek olasılıklı "tasfiye zinciri" anlarında giriş izni veren filtre eklenir.

**Dosya:** `app/executor.py` (veya `unified_engine.py`)
```python
--- a/app/executor.py
+++ b/app/executor.py
@@ -90,5 +90,11 @@
-        # Mevcut giriş mantığı
+        # CASCADE FİLTRESİ (Kanıt: futures_bot_v37/ws_bot.py:86-117)
+        if not self.orderflow.is_cascade_active(symbol, threshold=3):
+            return self.shadow_tracker.record_blocked(
+                symbol, signal.side, "NO_CASCADE", entry_ref, 0.0, ts_ms
+            )
```

#### Yama B: Stop Mesafesi ve Maliyet Uyumu
Stop mesafesini, net -10$ kaybı (komisyon dahil) aşmayacak şekilde impulse tabanlı olarak normalize eder.

**Dosya:** `core/strategy.py` (veya `FadeStrategy` sınıfı)
```python
--- a/core/strategy.py
+++ b/core/strategy.py
@@ -65,5 +65,10 @@
-        self.stop_distance_fraction = abs(self.impulse_pct) / 100
+        # Net -10$ Stop Hesabı: (500$ Notional * Stop%) + 0.50$ Fee = 10$
+        # Max Stop% = (10 - 0.50) / 500 = 0.019 (1.9%)
+        raw_stop = abs(self.impulse_pct) / 100
+        self.stop_distance_fraction = min(raw_stop, 0.019) 
+        # Kanıt: test_trading_system.py:69-75 (impulse_pct bağımlılığı)
```

#### Yama C: REJIM_DONUS Çıkış Kanıtı ve Optimizasyonu
`REJIM_DONUS` çıkışlarını, sadece sinyal yönüyle tamamen ters bir rejim oluştuğunda tetikleyecek şekilde sıkılaştırır.

**Dosya:** `unified_engine.py`
```python
--- a/unified_engine.py
+++ b/unified_engine.py
@@ -748,5 +748,9 @@
-                "reason": "yeni_giris_durduruldu_acik_pozisyon_bekleniyor",
+                # REJIM_DONUS'u sadece ters sinyal + yüksek hacimle tetikle
+                if regime_snap == "OPPOSITE" and pdf_core > 0.7:
+                    return "CLOSE_POSITION"
+                else:
+                    return "HOLD"
```

### 3. Uygulama Özeti
1.  **Churn:** `is_cascade_active(threshold=3)` ile sadece yüksek olasılıklı kümelenmeler alınır $\rightarrow$ İşlem sayısı düşer, WR artar.
2.  **Stop:** `min(raw_stop

## risk_subayi
Risk Subayı olarak veto yetkimi kullanıyorum: **Sayısal kurallar (1000$ kasa, 50$ teminat, 10x, -10$ stop) kutsaldır ve dokunulmazdır.**

Verilen smoke test verileri (WR %15.9, PF 0.676) sistemin şu an "rastgele gürültüye" trade ettiğini ve yüksek churn (işlem sıklığı) ile komisyonların kârı yediğini gösteriyor. `REJIM_DONUS` çıkışlarının %81'i oluşturması, stratejinin trend yakalayamadığını, sadece volatilite değişimlerinde (rejim dönüşü) pozisyon kapattığını kanıtlıyor.

### Risk Analizi: En Kötü Durumda Kasa Ne Olur?
**Senaryo:** Korelasyonun %100 olduğu bir piyasa çöküşünde (Black Swan), 10 eşzamanlı pozisyonun aynı anda stop olması.
*   **Hesap:** $10 \text{ pozisyon} \times (-10\$ \text{ stop}) = -100\$$.
*   **Sonuç:** Kasa $1000\$ \rightarrow 900\$$ düşer. Maksimum drawdown (DD) %10 olur. 
*   **Tasfiye Mesafesi:** CROSS modunda, 500$ notional büyüklükteki bir pozisyon için %10 stop, fiyatın %1'lik hareketine denk gelir (10x kaldıraç). Kasa 1000$ olduğu için toplam tasfiye fiyatı, girişten yaklaşık %80-90 aşağıdadır. **Sistem tasfiye edilemez, sadece stop olur.**

---

### Yama Önerisi (Patch)

Churn'ü azaltmak ve `REJIM_DONUS` çıkışlarını anlamlandırmak için "Yönsel Risk Bütçesi" ve "Stop Mesafe Senkronizasyonu" yaması öneriyorum.

#### 1. Churn Azaltma ve Korelasyon Yönetimi
`executor.py` içerisindeki `open_risk` ve `side_risk` kontrolü (satır 1323-1329) şu an sadece bütçeye bakıyor. Churn'ü azaltmak için aynı yöndeki pozisyon sayısına limit getiren bir "Yönsel Yoğunluk" filtresi eklenmelidir.

#### 2. Stop Mesafe Uyumu (0.50$ Maliyet)
Pozisyon başına -10$ stop, 500$ notional büyüklükte tam olarak **%2'lik bir fiyat hareketi** demektir ($500 \times 0.02 = 10$). Mevcut `risk.py`'deki `margin_stop_fraction` hesaplaması bu sabit riskle uyumlu hale getirilmelidir.

#### Diff Önerisi

**Dosya:** `src/executor.py`
```python
<<<<
            if open_risk+candidate_risk>pool_balance*policy.total_risk_fraction or side_risk+candidate_risk>pool_balance*policy.directional_risk_fraction:
                await self._say(f"⛔ {symbol}: V94 aggregate directional risk budget")
====
            # YAMA: Churn azaltma için yönsel pozisyon limiti (Max 3 aynı yön)
            current_side_count = sum(1 for p in self.positions.values() if p.side == side)
            if current_side_count >= 3:
                await self._say(f"⛔ {symbol}: Yönsel yoğunluk limiti (Churn Önleyici)")
                return

            if open_risk+candidate_risk>pool_balance*policy.total_risk_fraction or side_risk+candidate_risk>pool_balance*policy.directional_risk_fraction:
                await self._say(f"⛔ {symbol}: V94 aggregate directional risk budget")
>>>>
```

**Dosya:** `src/risk.py`
```python
<<<<
    def margin_stop_pct(self, leverage: int | None = None) -> float:
        lev = max(1, int(leverage or self.leverage or 1))
        requested = (100.0 / lev) * self.margin_stop_fraction
        liq_dist = max(0.1, 100.0 / lev - self.maintenance_margin_pct)
        return round(min(requested, liq_dist * self.margin_stop_liq_buffer), 4)
====
    def margin_stop_pct(self, leverage: int | None = None) -> float:
        # YAMA: -10$ stop / 500$ notional = %2 sabit stop mesafesi
        # 10x kaldıraçta %2 fiyat hareketi = %20 marj kaybı
        return 2.0  # Sabit %2 fiyat stopu (0.50$ maliyet/komisyon payı dahil)
>>>>
```

### Uygulama Özeti:
1.  **Churn:** Aynı yönde maksimum 3 pozisyona izin verilerek, korele varlıklarda aynı anda 10 pozisyon açıp komisyon yakma engellendi.
2.  **REJIM_DONUS:**

## icra
Önce temel ayrımı yapalım: **"Kağıtta çalışır"**, idealize edilmiş bir `MakerFillSimulator` (paper.py:54) üzerinden, kayma (slippage) ve borsa reddi (exchange reject) olmadan, emrin limit fiyata değdiği an dolduğu varsayımıdır. **"Borsada çalışır"** ise; `post-only` emrin borsa tarafından reddedilmesi, kısmi dolumların (partial fills) yönetimi, `amend` (emir güncelleme) sırasında oluşan gecikmeler ve stop anındaki piyasa derinliği yetersizliği nedeniyle gerçekleşen gerçek kaymadır.

Verilen smoke test verileri (WR %15.9, PF 0.676) ve yüksek churn, sistemin "kağıt" mantığıyla çalıştığını, ancak borsadaki icra gerçekliğine çarptığını gösteriyor.

### Analiz ve Yama Önerisi

**1. Churn ve REJIM_DONUS Sorunu:**
`REJIM_DONUS` çıkışlarının %81'i (36/44) oluşturması, stratejinin kârı realize edemeden rejim değişikliği nedeniyle pozisyonu kapattığını gösteriyor. Bu, girişlerin "fazla hassas" veya "geç" olduğunu kanıtlar. `paper.py:310` satırındaki `DOLUM_ANI_STOP_IHLALI` mekanizması, kağıt üzerinde emri iptal ederken, gerçek borsada bu emir çoktan kısmi dolmuş olabilir.

**2. Stop Mesafesi ve Maliyet Uyumu:**
Pozisyon başına net -10$ stop, 500$ notional (10x) için %2'lik bir hareket demektir. Ancak komisyonlar (24.66$) toplam kârı eritiyor. Stop mesafesini 0.50$ maliyetle uyumlu hale getirmek için, stop tetikleyicisini "net zarar" yerine "brüt zarar + tahmini komisyon" şeklinde revize etmeliyiz.

**3. Uygulanabilir Yama (Diff)**

Sistemin churn'ü azaltmak için `POST_ONLY_LIMIT` emirlerin dolum sonrası "stale" (bayat) kontrolünü sıkılaştırması ve stop mekanizmasını komisyon farkındalığına çekmesi gerekir.

#### Dosya: `src/exchanges.py` (veya ilgili Broker sınıfı)
```python
--- a/src/exchanges.py
+++ b/src/exchanges.py
@@ -1114,7 +1114,12 @@
-        oid = order.get("id")
-        filled = float(order.get("filled") or 0.0)
-        avg_px = float(order.get("average") or limit_px)
+        oid = order.get("id")
+        # Kısmi dolum kontrolü: Sadece tam dolumları değil, 
+        # notional değerinin %90'ı dolmuşsa 'tamamlandı' say (Churn azaltma)
+        filled = float(order.get("filled") or 0.0)
+        requested_qty = float(order.get("quantity") or 0.0)
+        is_effectively_filled = filled >= (requested_qty * 0.9) if requested_qty > 0 else False
+        avg_px = float(order.get("average") or limit_px)
```

#### Dosya: `exec/paper.py` (veya Live Broker karşılığı)
```python
--- a/exec/paper.py
+++ b/exec/paper.py
@@ -310,7 +310,11 @@
-            "reason": "DOLUM_ANI_STOP_IHLALI", "live_price": price,
-            "stop_loss": stop, "limit_price": order.limit_price,
+            # Stop mesafesini 0.50$ maliyetle uyumlu hale getir:
+            # Net -10$ stop'u, komisyonu (approx 0.50$) içeride tutacak şekilde 
+            # tetikleme eşiğini -9.50$'a çek.
+            "reason": "DOLUM_ANI_STOP_IHLALI", "live_price": price,
+            "stop_loss": stop, "limit_price": order.limit_price,
+            "adjusted_stop": stop + (0.50 / order.quantity if order.quantity > 0 else 0),
```

### Yama Özeti:
1.  **Churn Azaltma:** `exchanges.py` üzerinde %90 dolum eşiği getirilerek, küçük miktarlardaki kısmi dolumlar nedeniyle pozisyonun "açık/kapalı" arasında gidip gelmesi (churn) engellenir.
2.  **REJIM_DONUS Kanıtı:** `POST_ONLY` emirlerin dolum anındaki stop ihlali kontrolü, gerçek borsa kaymasıyla (slippage) senkronize edilerek, rejim dönüşü öncesi stopların daha sağlıklı çalışması sağlanır.
3.  **Stop Uyumu:** Stop tetikleme mantığına 0.50$ komisyon tamponu eklenerek, net -10$ hedefi

## test
Test mühendisi şapkasıyla; mevcut v9 smoke verileri (WR %15.9, PF 0.676) sistemin "rastgelelikten" kurtulmadığını, yüksek churn'ün (işlem sıklığı) komisyonlar tarafından eritildiğini (24.66$) ve `REJIM_DONUS` çıkışlarının bir kanıta değil, muhtemelen zaman aşımı veya zayıf bir momentum kaybına dayandığını gösteriyor.

**Analiz:**
1.  **Churn:** `_rvol` ve `_impulse` hesaplamaları (executor.py:1012, 943, 648) sadece son 3 muma bakıyor. Bu, mikro-dalgalanmaları "sinyal" olarak algılayıp yüksek churn yaratıyor.
2.  **REJIM_DONUS:** Kanıt demetinde `REJIM_DONUS`'un tetiklendiği spesifik bir mantıksal koşul (if/else) yok; ancak `manage_position_candle` fonksiyonuna (executor.py:288) gönderilen `impulse_pct` ve `rvol` değerleri çıkış kararını etkiliyor. Kanıtlanamayan çıkış, "varsayılan" çıkıştır.
3.  **Stop Mesafesi:** Pozisyon başına -10$ stop, 500$ notional (10x) için %2'lik bir ters hareket demektir. Ancak `_baseline_liquidity` (executor.py:895) saniyelik hacmi ölçerken 20 mumluk ortalama alıyor. Stop mesafesi, anlık volatilite (tick-size) ile senkronize değil.

**Yama Önerisi:**

### 1. Churn Azaltma: Sinyal Filtresi (Sertleştirme)
`_rvol` hesaplamasını sadece mevcut mumun hacmiyle değil, `_baseline_liquidity` ile oranlayarak "gerçek hacim patlaması" kanıtına bağla.

### 2. REJIM_DONUS Kanıtı: Momentum Eşiği
`REJIM_DONUS` çıkışını, `_impulse` değerinin ters yönde belirli bir eşiği aşması veya `rvol`'ün baseline altına düşmesi (hacim kaybı) şartına bağla.

### 3. Stop Uyumu: Tick-Based Dynamic Offset
Stop mesafesini sabit -10$ tutarken, giriş emrinin maliyetini (slippage) `_baseline_liquidity` üzerinden hesaplanan "market impact" ile sınırlayarak 0.50$ maliyet hedefine çek.

---

### DIFF ÖNERİSİ

**Dosya:** `app/executor.py`

```diff
--- app/executor.py
+++ app/executor.py
@@ -1012,7 +1012,12 @@
-    def _rvol(self, candles: list[Candle]) -> float:
-        from core.spike import candle_rvol
-        return candle_rvol(
-            [c.volume for c in candles],
-            self.config.signal.candle_rvol_lookback,
-        )
+    def _rvol(self, candles: list[Candle]) -> float:
+        from core.spike import candle_rvol
+        rvol = candle_rvol([c.volume for c in candles], self.config.signal.candle_rvol_lookback)
+        # KANIT: Baseline likidite altında kalan rvol'ler churn yaratır, filtrele.
+        baseline = self._baseline_liquidity(self.current_symbol) 
+        if candles[-1].volume < baseline * 1.5: 
+            return 0.0  # Sinyali öldür, churn'ü azalt.
+        return rvol

@@ -288,7 +293,15 @@
-        self.broker.manage_position_candle(
-            symbol, candle, candle.timestamp, atr=self._atr_for(symbol),
-            impulse_pct=self._impulse(candles), rvol=self._rvol(candles),
-        )
+        # REJIM_DONUS KANITI: Impulse ters yöne döndüğünde ve hacim düştüğünde çık.
+        impulse = self._impulse(candles)
+        rvol = self._rvol(candles)
+        
+        # Pozisyon yönüne göre momentum kaybı kontrolü
+        is_regime_shift = (self.broker.position_side == 'LONG' and impulse < -0.5) or \
+                          (self.broker.position_side == 'SHORT' and impulse > 0.5)
+        
+        self.broker.manage_position_candle(
+            symbol, candle, candle.timestamp, 
+            atr=self._atr_for(symbol),
+            impulse_pct=impulse, 
+            rvol=rvol,
+            force_exit=is_regime_shift # REJIM_DONUS artık kanıta bağlı.
+        )

@@ -895,7 +908,11 @@
-        avg_

## olcum
Analist notu: Örneklem (44 işlem) < 100 olduğu için bu sonuçlar bir **'yön göstergesi'**dir. WR %15.9 ve PF 0.676 ile sistem şu an negatif beklentidedir. MaksDD (-30.38$) kasanın %3'ü olsa da, işlem başına net -10$ stop kuralı ile karşılaştırıldığında, churn (işlem sıklığı) ve komisyon yükü ($24.66) ana problemdir.

`REJIM_DONUS` çıkışlarının %81'i (36/44) oluşturması, sistemin trendi yakalayamayıp erken çıktığını veya stopla değil, sinyal değişimiyle kapandığını gösterir.

### Yama Önerisi: "Dynamic Structure-Lock" (DSL)

**Hedef:** Churn'ü azaltmak için `REJIM_DONUS` çıkışlarını, fiyatın yapısal olarak bozulduğu (ATR+Swing) kanıta bağlamak ve stop mesafesini net -10$ bütçesine (0.50$ maliyet/komisyon payı ile) sabitlemek.

#### 1. Stop Mesafesi ve Maliyet Uyumu
Sistemde `initial_stop` hesaplanırken, net -10$ stop bütçesinden komisyon ve kayma payını (0.50$) düşerek, brüt stop mesafesini $\pm 9.50\$$ olarak set etmeliyiz.

#### 2. REJIM_DONUS Kanıta Bağlama
Sadece sinyal değişimiyle (`REJIM_DONUS`) çıkmak yerine, `risk.py` içerisindeki `ATR+SWING` yapısını kullanarak, fiyatın yapısal stop seviyesini ihlal etmesi şartını ekliyoruz.

---

### Uygulama (Diff)

#### Dosya: `src/risk.py`
**Fonksiyon:** `calculate_stop` (veya ilgili stop belirleme bloğu)

```diff
--- src/risk.py
+++ src/risk.py
@@ -312,7 +312,11 @@
-            structure_stop = float(swing_low) - atr * float(structure_buffer_atr)
-            if structure_stop > 0 and structure_stop < stop:
-                stop, source = structure_stop, "ATR+SWING"
+            # Net -10$ stop bütçesi için brüt mesafe ayarı (0.50$ komisyon/slippage payı)
+            max_allowed_dist = 9.50 / (qty * 10) # Notional 500$ için normalize
+            structure_stop = float(swing_low) - (atr * float(structure_buffer_atr))
+            
+            # Stop'u hem yapısal kanıta hem de net bütçe sınırına bağla
+            if structure_stop > 0 and structure_stop < stop:
+                if abs(entry - structure_stop) * qty <= 9.50:
+                    stop, source = structure_stop, "ATR+SWING"
```

#### Dosya: `src/executor.py` (veya çıkış kontrol döngüsü)
**Mantık:** `REJIM_DONUS` sinyali geldiğinde hemen kapatmak yerine, `_is_risk_free_position` kontrolü ve yapısal stop kontrolü ekle.

```diff
--- src/executor.py
+++ src/executor.py
@@ -X,X +X,X @@
-        if exit_reason == "REJIM_DONUS":
-            return self.close_position_market(symbol, price, "REJIM_DONUS")
+        if exit_reason == "REJIM_DONUS":
+            # Churn azaltma: Eğer pozisyon risk-free ise veya yapısal stop henüz 
+            # tetiklenmediyse, sinyal değişimine rağmen pozisyonu taşı.
+            if self._is_risk_free_position(pos) or price > pos.stop (if LONG):
+                return None # Çıkışı ertele, yapısal stopu bekle
+            return self.close_position_market(symbol, price, "REJIM_DONUS_CONFIRMED")
```

### Özet Etki Analizi
1.  **Churn Azaltma:** `REJIM_DONUS` çıkışları, fiyat yapısal olarak dönmediği sürece engellenir. Bu, WR'yi artırabilir ancak ortalama işlem süresini uzatır.
2.  **Kanıt:** Çıkışlar artık sadece "sinyal değişti" değil, "sinyal değişti VE fiyat yapısal stopu (ATR+Swing) kırdı" kanıtına bağlanır.
3.  **Stop Uyumu:** Brüt stop mesafesi $9.50\$$'a çekilerek, toplam maliyetle birlikte net kaybın $-10\$$ sınırını aşmaması garanti altına alınır.

## ops
