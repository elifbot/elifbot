## mimar
Sistem mimarı olarak, v9 smoke verisindeki düşük WR (%15.9) ve yüksek churn (REJIM_DONUS baskınlığı) sorunlarını çözmek için kanıta dayalı yama önerim aşağıdadır.

### 1. Churn Azaltma: Cascade Filtresi Entegrasyonu
Sistemdeki yüksek churn, düşük kaliteli sinyallerin (gürültü) işleme girmesinden kaynaklanmaktadır. Kanıtlar, "Cascade Eşiği" (tasfiye zinciri) kullanımının isabet oranını %60.1'den %86.3'e çıkardığını göstermektedir.

*   **Kanıt:** `futures_bot_v37/ws_bot.py:86-92` ve `futures_bot_v34/ws_bot.py:85-91`.
*   **Uygulama:** Eşik 3 (son 60 saniyede $\ge 3$ sinyal) seçilerek sadece yüksek momentumlu/tasfiye odaklı kurulumlar kabul edilecektir.

### 2. REJIM_DONUS Çıkışının Kanıta Bağlanması
Mevcut sistemde çıkışların %81.8'i (36/44) `REJIM_DONUS` ile gerçekleşmektedir. Bu, sinyalin giriş motoru ile çıkış rejimi arasındaki uyumsuzluğu gösterir.

*   **Kanıt:** `test_trading_system.py:69-75` ve `test_trading_system.py:128-134`.
*   **Analiz:** `FadeStrategy` (tersine dönüş) ve `Trend` motorları farklı stop/çıkış dinamiklerine sahiptir. `REJIM_DONUS` çıkışları, sinyalin "motor" tipinin (fade vs trend) değiştiği anlarda tetiklenmektedir.
*   **Yama:** Giriş sinyaline `motor` etiketi eklenerek, sadece aynı motor tipindeki rejim değişikliği çıkış tetikleyicisi olarak kabul edilecektir.

### 3. Stop Mesafesi ve Maliyet Uyumu ($-10$ Net Stop)
Sistem kuralı pozisyon başına net $-10\$$ stop gerektirir. $500\$$ notional değerde bu, $\%2$ brüt kayba tekabül eder. Ancak mevcut kodda stoplar sabit yüzdelerle veya rastgele `sl_pct` ile belirlenmiştir.

*   **Kanıt:** `ws_bot.py:1062-1068` (v4), `ws_bot.py:981-987` (v37).
*   **Hata:** `stop = giris_fiyat * (1 - self.sl_pct / 100)` kullanımı, volatiliteye göre stop mesafesini değiştirir ve $-10\$$ sabit risk kuralını ihlal eder.
*   **Yama:** Stop mesafesi, `stop_distance_fraction` üzerinden değil, doğrudan notional değer üzerinden sabit $\%2$ (brüt) olarak kilitlenecektir.

---

### Uygulanabilir Yama (Diff)

#### Dosya: `app/executor.py` (veya `ws_bot.py` giriş fonksiyonu)
```python
<<<<
        stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                else giris_fiyat * (1 + self.sl_pct / 100))
====
        # Kural: 500$ notional, -10$ net stop = %2 brüt stop
        # Kanıt: Değişmez Kural (1000$ kasa / 50$ teminat / 10x)
        fixed_sl_pct = 2.0 
        stop = (giris_fiyat * (1 - fixed_sl_pct / 100) if s.yon == "LONG"
                else giris_fiyat * (1 + fixed_sl_pct / 100))
>>>>
```

#### Dosya: `app/executor.py` (Sinyal Filtreleme Katmanı)
```python
<<<<
        sonuc = self.portfoy.open_position(s.exchange, s.symbol, s.yon, giris_fiyat, MARJ, ...)
====
        # Churn Azaltma: Cascade Eşiği Filtresi
        # Kanıt: futures_bot_v37/ws_bot.py:86-92 (Eşik 3 seçildi)
        if not self.cascade_tracker.is_valid(s.symbol, threshold=3):
            return {"symbol": s.symbol, "signal": "BEKLE", "reason": "cascade_threshold_not_met"}
            
        sonuc = self.portfoy.open_position(s.exchange, s.symbol, s.yon, giris_fiyat, MARJ, ...)
>>>>
```

#### Dosya: `core/strategy.py` (Sinyal Nesnesi)
```python
<<<<
    def __init__(self, side, impulse_pct, rvol, stop_distance_fraction, motor="fade"):
====
    def __init__(self, side, impulse_

## risk_subayi


## icra
Önce temel sorunu tanımlayalım: **"Kağıtta çalışır"** ile **"Borsada çalışır"** arasındaki fark; kağıt üzerinde emrin gönderildiği an dolduğu varsayılması (veya basit bir simülatörle geçiştirilmesi), borsada ise emrin deftere yazılması, öncelik sırası, kısmi dolumlar, `post-only` reddi ve ağ gecikmesiyle fiyatın kaymasıdır.

Verdiğin smoke test sonuçları (WR %15.9, PF 0.676) sistemin şu an "rastgele gürültüye" trade ettiğini ve yüksek churn (işlem sıklığı) ile komisyonların kârı yediğini gösteriyor. `REJIM_DONUS` çıkışlarının %81'i (36/44) oluşturması, stratejinin stop olmadan önce "sinyal değişti" diyerek pozisyonu kapattığını ancak bunu kârlı bir şekilde yapamadığını kanıtlıyor.

İşte belirlenen kısıtlar altında (1000$ kasa, 50$ giriş, -10$ stop) churn'ü azaltan ve icrayı borsaya uygun hale getiren yama:

### 1. Analiz ve Yama Mantığı
*   **Churn Azaltma:** `REJIM_DONUS` çıkışlarını sadece "karşıt sinyal" ile değil, minimum bir "kâr eşiği" veya "zaman filtresi" ile bağlamalıyız.
*   **Stop Uyumu:** Pozisyon başına -10$ stop, 500$ notional (10x) için %2'lik bir hareket demektir. `paper.py` içindeki `DOLUM_ANI_STOP_IHLALI` (satır 310-316) gerçek borsada "slippage" (kayma) nedeniyle -10$ yerine -12$ veya -15$ olarak gerçekleşir.
*   **Kanıt Bağlantısı:** `test_v52_hardening.py` içindeki `_stale_fill_blocks` ve `bind_plan` mekanizması, emrin güncelliğini kontrol eder. Churn'ü azaltmak için bu kontrolü "sinyal kalitesine" bağlayacağız.

### 2. Uygulanabilir Yama (Diff)

#### Dosya: `src/exchanges.py` (veya ilgili broker sınıfı)
**Amaç:** `post-only` emirlerin reddini yönetmek ve kısmi dolumları (partial fills) tek bir pozisyon olarak konsolide etmek.

```python
--- a/src/exchanges.py
+++ b/src/exchanges.py
@@ -1114,7 +1114,12 @@
-        status = order
+        # YAMA: Post-only reddi durumunda emri hemen iptal et ve churn'ü önlemek için 
+        # aynı tick içinde tekrar denemeyi engelle.
+        if order.get("status") == "CANCELED" and "post-only" in order.get("reason", "").lower():
+            return {"status": "REJECTED_POST_ONLY", "filled": 0.0, "avg_px": None}
+        
+        status = order
```

#### Dosya: `exec/paper.py` $\rightarrow$ `exec/broker.py` (Canlı İcra Katmanı)
**Amaç:** `REJIM_DONUS` çıkışlarını kanıta bağlamak ve stop mesafesini optimize etmek.

```python
--- a/exec/paper.py
+++ b/exec/broker.py
@@ -310,6 +310,15 @@
-        self.trades.append({
-            "type": "ORDER_CANCELED", "order_id": order.id, "symbol": order.symbol,
-            "reason": "DOLUM_ANI_STOP_IHLALI", "live_price": price,
-            "stop_loss": stop, "limit_price": order.limit_price,
-            "filled_quantity": order.filled_quantity,
-            "quantity": order.quantity, "timestamp": order.created_ms,
+        # YAMA: Stop mesafesini 0.50$ maliyet (komisyon+kayma) ile uyumlu hale getir.
+        # Net -10$ stop'u korumak için, tetikleme fiyatını 0.20$ yukarı/aşağı çek.
+        adjusted_stop = stop + (0.20 if order.side == OrderSide.BUY else -0.20)
+        
+        # REJIM_DONUS kanıtı: Sadece fiyat girişten %0.1 uzaklaştıysa veya 
+        # karşıt sinyal 'strong' ise çıkış yap.
+        if motor == "REJIM_DONUS" and abs(price - order.limit_price) / order.limit_price < 0.001:
+            return "HOLD_POSITION" # Churn'ü azaltan filtre
+
+        self.trades.append({
+            "type": "ORDER_CANCELED", "order_id": order.id, "symbol": order.symbol,
+            "reason": "DOLUM

## test


## olcum


## ops
