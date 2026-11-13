# KRIPTO-BOT — Bota Kod İnceletme Paketi

**Depo:** `omeracar56/kripto-bot`  
**Dal:** `arena/787d4de8-kripto-bot`  
**Commit:** `cf99ba6`  
**Kapsam:** Gerçek Binance/OKX verisiyle çalışan, gerçek emir göndermeyen canlı-benzeri paper sürümü.

## İnceleme botuna verilecek talimat

Aşağıdaki Git diff'ini kıdemli Python/async ve kripto işlem sistemi geliştiricisi olarak incele. Yalnızca somut ve yeniden üretilebilir sorunları raporla; genel geçer öneriler verme. Her bulgu için önem derecesi, dosya, ilgili kod, hatanın nasıl oluştuğu ve düzeltme önerisi ver. Özellikle şunları denetle:

1. Binance USDⓈ-M Futures ve OKX Swap enstrüman/kontrat miktarı doğruluğu.
2. WebSocket veri ayrıştırma, yeniden bağlanma ve bayat veri riskleri.
3. MA/EMA/RSI/MACD hesaplarında look-ahead veya yanlış sinyal riski.
4. Paper bid/ask, komisyon, kayma ve funding muhasebesinin doğruluğu.
5. Gerçekleşen emir miktarı/fiyatı bilinmiyorsa pozisyon açılmasını önleyen kontroller.
6. Haber yayın zamanı, veto süresi ve girdi temizliği.
7. Async görevler, SQLite kalıcılığı ve yeniden başlatma davranışı.
8. Telegram yetkilendirme ve raporların gerçek veriyi yansıtması.
9. Testlerin bu davranışları gerçekten kanıtlayıp kanıtlamadığı.

Bu inceleme paper/simülasyon içindir; gerçek para ile emir göndermeyi önerme veya etkinleştirme.

## Yerel doğrulama

```bash
MODE=paper python -m src.main
python -m pytest
python test_hizli.py
python test_bot_v7.py
```

## Kod değişiklikleri

`-` ile başlayan satırlar eski, `+` ile başlayan satırlar yeni koddur. Dosya başlıkları değişikliğin hangi modülde olduğunu gösterir.

~~~diff
diff --git a/README.md b/README.md
index d49a586..5b7e708 100644
--- a/README.md
+++ b/README.md
@@ -1,9 +1,28 @@
-# 🛡️ KRIPTO-BOT v6 — Kurumsal, Zırhlı, Multi-Timeframe 1h/4h, 20 Kademe Emir Defteri, Discord/PagerDuty & Multi-Exchange Failover Kripto Botu
+# 🛡️ KRIPTO-BOT v7.2 — Canlı Veri + Gerçekçi Paper + Çoklu Borsa Kripto Botu
 
 Binance ve OKX vadeli/spot piyasalarında çalışan; **Multi-Timeframe (1h / 4h) Ana Trend Filtresi**, **20 Kademe Emir Defteri Derinlik Analizi (`Bid/Ask Ratio`)**, **Discord Webhook & PagerDuty Acil Sesli Telefon Alarmı**, **Multi-Exchange Failover (Borsa Kesinti Sigortası)**, **SQLite WAL Modu & 24 Saatlik `VACUUM` Çöp Toplayıcı**, **Prometheus `/metrics` ve `/health` Canlı Sağlık Endpoint'i**, **Kritik Güvenlik Zırhlaması (Security Hardening)**, **%10 Kasa × Dinamik 20x/10x/5x Kaldıraç**, **%0.30 Maksimum Kayma (Slippage) & Chase Order**, **%5 Zarar Stop + Kâr Kilidi**, **Artıda Sınırsız Kademe Ekleme (Pyramiding)** ve **Çapraz İkili Kurtarma** özelliklerine sahip tam donanımlı alım-satım sistemi.
 
 ---
 
+## 🟢 Canlı Benzeri Paper (Gerçek Veri, Sanal Emir)
+
+`MODE=paper` ile gerçek para/emir kullanılmadan canlı piyasa koşulları taklit edilir:
+
+- **Doğru enstrümanlar:** Kaldıraç > 1 iken Binance USDⓈ-M Futures ve OKX USDT perpetual Swap WebSocket kanalları kullanılır; spot fiyatı perpetual fiyatıyla karıştırılmaz.
+- **Gerçek para akışı:** Binance `aggTrade`, `bookTicker`, 20 kademe derinlik ve tasfiye akışı; OKX `trades`, `tickers` ve `books5` akışı. OKX kontrat adetleri borsadan okunan `contractSize` ile coin miktarına çevrilir.
+- **Teknik analiz:** MA20/50, EMA9/21/50/200, RSI(14), MACD çizgi/sinyal/histogram; ayrıca ADX, MFI, OBV, VWAP, Bollinger ve diğer mevcut bileşenler.
+- **Haber akışı:** RSS ve opsiyonel CryptoPanic; yayın zamanı eski haberlerin yeniden yeni haber gibi veto üretmesi engellenir.
+- **Gerçekçi paper muhasebesi:** Market alışta ask, satışta bid; taker/maker komisyonu, kayma kaydı ve geçen süreye göre funding. Bakiye, komisyon ve funding SQLite'ta korunur.
+- **Telegram:** `piyasa` teknik/para akışı/funding/haber raporunu, `güncel` açık pozisyonları, `/pnl` komisyon ve funding dahil paper K/Z özetini döndürür.
+
+```bash
+MODE=paper python -m src.main
+```
+
+Bu komut gerçek emir göndermez. İşlem açılması için strateji sinyali ve risk kontrolleri gerekir; botun hemen pozisyon açmaması hata değildir. Canlı fiyatlı deneme için Binance/OKX ve haber kaynaklarına internet erişimi gerekir.
+
+---
+
 ## 🆕 v6 Sinyal Kalitesi & Acil Alarm Yükseltmeleri
 
 ### 1. Multi-Timeframe (Çoklu Zaman Dilimi — `1h` / `4h`) Ana Trend Filtresi (`src/indicators.py`, `src/strategy.py`, `src/executor.py`)
@@ -46,16 +65,19 @@ Telegram için `.env` içinde `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` tanıml
 
 | Mesaj / komut | Yanıt |
 |---|---|
+| `piyasa`, `/piyasa`, `/analiz` | MA/EMA/RSI/MACD, para akışı, emir defteri, funding ve haber raporu |
 | `güncel`, `/guncel`, `/pozisyonlar` | Açık pozisyonlar; borsa, güncel fiyat, miktar, kademe, stop, K/Z ve ROE |
-| `/karzar`, `/pnl` veya `kar zarar` | Oturum gerçekleşen K/Z, açık K/Z, toplam K/Z ve özsermaye |
+| `/karzar`, `/pnl` veya `kar zarar` | Gerçekleşen/açık K/Z; paper modunda komisyon, funding ve net paper K/Z |
 | `/durum` | K/Z özetinin yanında açık pozisyonların tamamı |
 | `/yardim` | Tüm uzaktan komutlar |
 
 Fiyat okunamayan pozisyonlar raporda **önbellek** olarak işaretlenir. Gerçekleşen K/Z özeti ana botun mevcut çalışma oturumuna aittir.
 
 ```bash
-# 1) Tüm 28 bölümdeki 87 kapsamlı çevrimdışı testi çalıştırın
-python3 test_hizli.py
+# 1) Regresyon ve çevrimdışi paper doğrulamalarını çalıştırın
+python3 -m pytest                 # 38 regresyon testi
+python3 test_hizli.py             # 101 ana paket senaryosu
+python3 test_bot_v7.py            # 27 bağımsız paper senaryosu
 
 # 2) Gerçek Zamanlı Web Panelini + /health & /metrics sunucusunu başlatın (Port 8501)
 python3 -m src.dashboard
diff --git a/config.yaml b/config.yaml
index f7dc731..659940d 100644
--- a/config.yaml
+++ b/config.yaml
@@ -1,5 +1,5 @@
 # =====================================================================
-# KRIPTO-BOT ANA AYAR DOSYASI (v6 — Multi-Timeframe 1h/4h Trend Filtresi +
+# KRIPTO-BOT ANA AYAR DOSYASI (v7.2 — Multi-Timeframe 1h/4h Trend Filtresi +
 # 20 Kademe Emir Defteri Derinlik Analizi (Bid/Ask Ratio) + Discord & PagerDuty Acil Alarm +
 # Multi-Exchange Failover + SQLite WAL & 24s VACUUM GC + Prometheus /health & /metrics +
 # Security Hardening + Dinamik Kaldıraç 20x/10x/5x + %0.30 Kayma & Chase Order)
@@ -13,6 +13,12 @@ genel:
   short_izni: true                                 # Short (düşüşe) işlem açılsın mı?
   kaldıraç: 20                                     # Baz kaldıraç 20x (oynaklıkta dinamik 10x / 5x)
 
+# Gerçek para gönderilmez; canlı piyasa koşullarını taklit eden paper ayarları.
+paper:
+  bakiye: 10000.0              # Sanal başlangıç kasası (USDT)
+  gercekci_yurutme: true       # Market alışta ask / satışta bid, spread ve kayma
+  funding_aktif: true          # Gerçek funding oranını geçen süreye göre sanal kasaya işle
+
 # --- YENİ: Çoklu Zaman Dilimi (Multi-Timeframe 1h/4h) Ana Trend Filtresi ---
 mtf_filtre:
   aktif: true                   # 1h ve 4h büyük trend yönü kontrol edilsin mi?
diff --git a/src/config.py b/src/config.py
index 54bcb0b..00309a3 100644
--- a/src/config.py
+++ b/src/config.py
@@ -129,7 +129,7 @@ def validate_config(cfg: dict, api: dict | None = None) -> None:
     for section in (
         "mtf_filtre", "bildirimler", "failover", "veritabani", "health_check",
         "sigorta", "emirler", "makine_ogrenmesi", "para_akisi", "arbitraj",
-        "haberler", "optimizasyon", "panel", "hiz",
+        "haberler", "optimizasyon", "panel", "hiz", "paper",
     ):
         value = cfg.setdefault(section, {})
         if not isinstance(value, dict):
@@ -166,6 +166,9 @@ def validate_config(cfg: dict, api: dict | None = None) -> None:
         raise ConfigError(f"Desteklenmeyen zaman dilimi: {timeframe}")
     _integer(cfg, "genel", "kaldıraç", minimum=1, maximum=50)
     _boolean(cfg, "genel", "short_izni", True)
+    _default_number(cfg, "paper", "bakiye", 10000, minimum=10, maximum=1e9)
+    _boolean(cfg, "paper", "gercekci_yurutme", True)
+    _boolean(cfg, "paper", "funding_aktif", True)
 
     _boolean(cfg, "mtf_filtre", "aktif", True)
     mtf_frames = cfg["mtf_filtre"].setdefault("zaman_dilimleri", ["1h", "4h"])
diff --git a/src/exchanges.py b/src/exchanges.py
index d12a2dc..3e6820e 100644
--- a/src/exchanges.py
+++ b/src/exchanges.py
@@ -59,6 +59,9 @@ class PaperBroker:
         self.max_slippage_pct = max_slippage_pct
         self.trades: list[dict] = []
         self.protections: dict[str, dict] = {}
+        self.total_fees_usdt = 0.0
+        self.total_funding_usdt = 0.0
+        self.funding_history: list[dict] = []
 
     def _fill(
         self,
@@ -73,6 +76,7 @@ class PaperBroker:
     ) -> dict:
         fee = qty * price * fee_pct / 100
         self.balance -= fee
+        self.total_fees_usdt += fee
         fill = {
             "symbol": symbol,
             "side": side,
@@ -93,6 +97,23 @@ class PaperBroker:
         """Pozisyon kapandığında gerçekleşen dolar kâr/zararını kasaya işler."""
         self.balance = round(self.balance + float(pnl_usdt), 4)
 
+    def apply_funding(self, symbol: str, cash_delta: float, rate: float, elapsed_sec: float):
+        """Funding ödemesini/alacağını sanal kasaya ve denetim kaydına işler."""
+        delta = float(cash_delta)
+        if delta == 0:
+            return
+        self.balance = round(self.balance + delta, 8)
+        self.total_funding_usdt += delta
+        self.funding_history.append(
+            {
+                "ts": time.time(),
+                "symbol": symbol,
+                "cash_delta": delta,
+                "rate": float(rate),
+                "elapsed_sec": float(elapsed_sec),
+            }
+        )
+
     def market_order(
         self,
         symbol: str,
@@ -100,10 +121,15 @@ class PaperBroker:
         qty: float,
         price: float,
         exchange: str = "binance",
+        slippage_pct: float = 0.0,
+        price_source: str = "hint",
     ) -> dict:
-        return self._fill(
-            symbol, side, qty, price, self.fee_taker_pct, "market", exchange=exchange
+        fill = self._fill(
+            symbol, side, qty, price, self.fee_taker_pct, "market",
+            slippage_pct=slippage_pct, exchange=exchange,
         )
+        fill["price_source"] = price_source
+        return fill
 
     def maker_order(
         self,
@@ -169,6 +195,9 @@ class ExchangeManager:
         rk = cfg.get("risk", {})
         sg = cfg.get("sigorta", {})
         fo = cfg.get("failover", {})
+        paper_cfg = cfg.get("paper", {})
+        self.paper_realistic = bool(paper_cfg.get("gercekci_yurutme", False))
+        self.paper_funding_enabled = bool(paper_cfg.get("funding_aktif", False))
         self.max_slippage_pct = float(
             em.get("max_kayma_yuzde", rk.get("max_kayma_yuzde", 0.30))
         )
@@ -181,6 +210,7 @@ class ExchangeManager:
         )
 
         self.paper = PaperBroker(
+            balance_usdt=float(paper_cfg.get("bakiye", 10000.0)),
             fee_taker_pct=em.get("komisyon_taker_yuzde", 0.05),
             fee_maker_pct=em.get("komisyon_maker_yuzde", 0.02),
             max_slippage_pct=self.max_slippage_pct,
@@ -243,6 +273,30 @@ class ExchangeManager:
             return f"{symbol}:USDT"
         return symbol
 
+    async def get_contract_sizes(self) -> dict[tuple[str, str], float]:
+        """WebSocket miktar normalizasyonu için gerçek kontrat boyutlarını okur."""
+        if self.default_type != "swap":
+            return {}
+        out: dict[tuple[str, str], float] = {}
+
+        async def load_one(name: str):
+            try:
+                markets = await self._ex[name].load_markets()
+                for symbol in self.symbols:
+                    market = markets.get(self._ccxt_symbol(symbol)) or {}
+                    size = float(market.get("contractSize") or 0.0)
+                    if size > 0:
+                        out[(name, symbol)] = size
+            except Exception as exc:
+                print(
+                    f"⚠️ {name} kontrat metaverisi okunamadı; "
+                    f"kontratlı işlem akışı güvenli biçimde atlanacak: {safe_exception_msg(exc)}",
+                    flush=True,
+                )
+
+        await asyncio.gather(*(load_one(name) for name in self._ex))
+        return out
+
     @staticmethod
     def _client_order_params(exchange: str, client_order_id: str) -> dict:
         key = "clOrdId" if exchange == "okx" else "newClientOrderId"
@@ -480,9 +534,9 @@ class ExchangeManager:
             name = max(quotes, key=quotes.get)
         return name, quotes[name]
 
-    async def fetch_funding(self, symbol: str) -> float | None:
+    async def fetch_funding(self, symbol: str, exchange: str | None = None) -> float | None:
         swap = self._ccxt_symbol(symbol)
-        for name in self.get_failover_order():
+        for name in self.get_failover_order(exchange):
             ex = self._ex[name]
             try:
                 fr = await ex.fetch_funding_rate(swap)
@@ -584,6 +638,15 @@ class ExchangeManager:
             raise ValueError("Emir miktarı sıfırdan büyük olmalı")
         target_ex = self.choose_healthy_exchange(exchange)
         if self.mode == "paper":
+            if self.paper_realistic:
+                bid, ask = await self.fetch_bid_ask(symbol, target_ex)
+                px = ask if side == "buy" else bid
+                reference = price_hint or (bid + ask) / 2.0
+                slippage_pct = abs(px - reference) / max(reference, 1e-12) * 100.0
+                return self.paper.market_order(
+                    symbol, side, qty, px, exchange=target_ex,
+                    slippage_pct=slippage_pct, price_source="rest_bid_ask",
+                )
             px = price_hint or await self.fetch_price(symbol, target_ex)
             return self.paper.market_order(symbol, side, qty, px, exchange=target_ex)
 
@@ -607,11 +670,36 @@ class ExchangeManager:
             raise
 
         filled = order.get("filled")
+        average = order.get("average")
+        cost = order.get("cost")
+        if order.get("id") and (filled is None or (average is None and cost is None)):
+            try:
+                # Emri TEKRAR GÖNDERMEZ; yalnızca mevcut emrin nihai dolgusunu okur.
+                fetched = await ex.fetch_order(order["id"], self._ccxt_symbol(symbol))
+                order = {**order, **(fetched or {})}
+                filled = order.get("filled")
+                average = order.get("average")
+                cost = order.get("cost")
+            except Exception as exc:
+                raise RuntimeError(
+                    f"Emir dolgu miktarı/fiyatı doğrulanamadı (order={order.get('id')}): {exc}"
+                ) from exc
+        if filled is None:
+            raise RuntimeError(
+                f"Borsa gerçekleşen miktarı döndürmedi (order={order.get('id')}); istenen miktar dolgu sayılmadı"
+            )
+        filled = float(filled)
+        if average is None and cost is not None and filled > 0:
+            average = float(cost) / filled
+        if average is None:
+            raise RuntimeError(
+                f"Borsa gerçekleşme fiyatını döndürmedi (order={order.get('id')})"
+            )
         return {
             "symbol": symbol,
             "side": side,
-            "qty": float(filled) if filled is not None else qty,
-            "price": float(order.get("average") or price_hint or 0),
+            "qty": filled,
+            "price": float(average),
             "fee": float((order.get("fee") or {}).get("cost") or 0.0),
             "id": order.get("id"),
             "client_order_id": order_id,
diff --git a/src/executor.py b/src/executor.py
index b24b08e..b2784d2 100644
--- a/src/executor.py
+++ b/src/executor.py
@@ -5,6 +5,7 @@ ve Gizli Anahtar Maskeleme entegrasyonu.
 """
 from __future__ import annotations
 
+import math
 import time
 
 from .risk import Position
@@ -50,6 +51,7 @@ class Executor:
         self._prot_stop: dict[str, float] = {}
         self._last_replace: dict[str, float] = {}
         self._last_add_ts: dict[str, float] = {}
+        self._funding_last: dict[str, float] = {}
         self.add_cooldown_sec: float = 10.0
         self.stats = {
             "trades": 0,
@@ -61,6 +63,7 @@ class Executor:
             "pair_rescues": 0,
             "chase_orders": 0,
             "mtf_filtered": 0,
+            "funding_usdt": 0.0,
         }
 
         self._last_balance = 0.0
@@ -75,10 +78,14 @@ class Executor:
         try:
             loaded = self.state_store.load_positions()
             msgs = self.state_store.startup_recovery_report()
+            funding_clock = self.state_store.get_meta("paper_funding_clock", {}) or {}
             for sym, pos in loaded.items():
                 self.positions[sym] = pos
                 self.last_prices[sym] = pos.entry
                 self.active_leverage[sym] = pos.leverage
+                self._funding_last[sym] = float(
+                    funding_clock.get(sym, time.time()) or time.time()
+                )
             for m in msgs:
                 print(mask_secrets(m), flush=True)
             return msgs
@@ -116,6 +123,7 @@ class Executor:
             )
             for sym in candidates:
                 self.positions.pop(sym, None)
+                self._funding_last.pop(sym, None)
                 self._prot.pop(sym, None)
                 self._prot_stop.pop(sym, None)
                 if self.state_store is not None:
@@ -193,6 +201,39 @@ class Executor:
             tot += self.risk.pnl_usdt(pos, px)
         return round(tot, 2)
 
+    def _save_funding_clock(self):
+        if self.state_store is not None:
+            try:
+                self.state_store.set_meta("paper_funding_clock", self._funding_last)
+            except Exception:
+                pass
+
+    def apply_funding(
+        self, symbol: str, rate: float | None, mark_price: float, enabled: bool = True
+    ) -> float:
+        """Gerçek funding oranını geçen süreye oranlayarak paper kasaya uygular."""
+        if not enabled or getattr(self.broker, "mode", "paper") != "paper":
+            return 0.0
+        pos = self.positions.get(symbol)
+        now = time.time()
+        last = self._funding_last.setdefault(symbol, now)
+        if pos is None or rate is None or not math.isfinite(float(rate)) or mark_price <= 0:
+            self._funding_last[symbol] = now
+            return 0.0
+        elapsed = max(0.0, now - last)
+        if elapsed < 1.0:
+            return 0.0
+        direction = 1.0 if pos.side == "LONG" else -1.0
+        notional = pos.qty * float(mark_price)
+        cash_delta = -direction * notional * float(rate) * elapsed / (8 * 3600.0)
+        self._funding_last[symbol] = now
+        paper = getattr(self.broker, "paper", None)
+        if paper is not None and hasattr(paper, "apply_funding"):
+            paper.apply_funding(symbol, cash_delta, float(rate), elapsed)
+        self.stats["funding_usdt"] = self.stats.get("funding_usdt", 0.0) + cash_delta
+        self._save_funding_clock()
+        return cash_delta
+
     # -- 1) HER TICK: stop / trailing / kâr kilidi + Çapraz Kurtarma -------------
     async def on_price_tick(self, symbol: str, price: float):
         self.last_prices[symbol] = price
@@ -505,6 +546,8 @@ class Executor:
         self.positions[symbol] = pos
         self.last_prices[symbol] = fill_px
         self._last_add_ts[symbol] = time.time()
+        self._funding_last[symbol] = time.time()
+        self._save_funding_clock()
 
         if self.state_store is not None:
             try:
@@ -722,6 +765,8 @@ class Executor:
 
         if fully_closed:
             self.positions.pop(symbol, None)
+            self._funding_last.pop(symbol, None)
+            self._save_funding_clock()
             prot = self._prot.pop(symbol, None)
             self._prot_stop.pop(symbol, None)
             try:
diff --git a/src/indicators.py b/src/indicators.py
index dd04eab..1fe41a0 100644
--- a/src/indicators.py
+++ b/src/indicators.py
@@ -1,7 +1,7 @@
 """Gerçek teknik indikatörler — saf pandas/numpy ile hesaplanır (TA-Lib gerekmez).
 
 İndikatör seti:
-  Trend      : EMA 9/21/50, MACD, ADX (+DI/-DI), Donchian
+  Trend      : MA 20/50, EMA 9/21/50/200, MACD, ADX (+DI/-DI), Donchian
   Momentum   : RSI, Stokastik RSI, CCI, Williams %R
   Hacim/Akış : MFI (Money Flow Index), OBV, VWAP
   Volatilite : ATR, Bollinger Bantları
@@ -146,6 +146,9 @@ def indicator_score(df: pd.DataFrame, funding_rate: float | None = None) -> dict
     e9 = _last(Indicators.ema(close, 9), price)
     e21 = _last(Indicators.ema(close, 21), price)
     e50 = _last(Indicators.ema(close, 50), price)
+    e200 = _last(Indicators.ema(close, 200), 0.0)
+    ma20 = _last(Indicators.sma(close, 20), 0.0)
+    ma50 = _last(Indicators.sma(close, 50), 0.0)
     ema9_s, ema21_s = Indicators.ema(close, 9), Indicators.ema(close, 21)
     t = 0.0
     if price > e9 > e21:
@@ -164,6 +167,15 @@ def indicator_score(df: pd.DataFrame, funding_rate: float | None = None) -> dict
     comps["ema_trend"] = t
     total += t * 1.2
 
+    # --- Klasik hareketli ortalamalar ve uzun trend ---
+    ma_score = 0.0
+    if ma20 > 0 and ma50 > 0:
+        ma_score += 4 if ma20 > ma50 else -4
+    if e200 > 0:
+        ma_score += 4 if price > e200 else -4
+    comps["ma_trend"] = ma_score
+    total += ma_score
+
     # --- RSI ---
     rsi = _last(Indicators.rsi(close, 14), 50)
     r = 10 if rsi < 25 else (5 if rsi < 35 else (-10 if rsi > 75 else (-5 if rsi > 65 else (2 if rsi > 55 else (-2 if rsi < 45 else 0)))))
@@ -171,7 +183,9 @@ def indicator_score(df: pd.DataFrame, funding_rate: float | None = None) -> dict
     total += r
 
     # --- MACD ---
-    _, _, macd_h = Indicators.macd(close)
+    macd_line, macd_signal, macd_h = Indicators.macd(close)
+    macd_value = _last(macd_line, 0.0)
+    macd_signal_value = _last(macd_signal, 0.0)
     mh = _last(macd_h, 0.0)
     m = 0.0
     try:
@@ -266,8 +280,24 @@ def indicator_score(df: pd.DataFrame, funding_rate: float | None = None) -> dict
         "score": score,
         "bias": "LONG" if score >= 25 else ("SHORT" if score <= -25 else "NOTR"),
         "components": comps,
-        "snapshot": {"price": price, "rsi": rsi, "adx": adx_last, "macd_hist": mh,
-                     "mfi": mfi_v, "cci": cci_v, "vwap": vwap_v, "williams_r": wr},
+        "snapshot": {
+            "price": price,
+            "ma20": ma20,
+            "ma50": ma50,
+            "ema9": e9,
+            "ema21": e21,
+            "ema50": e50,
+            "ema200": e200,
+            "rsi": rsi,
+            "adx": adx_last,
+            "macd": macd_value,
+            "macd_signal": macd_signal_value,
+            "macd_hist": mh,
+            "mfi": mfi_v,
+            "cci": cci_v,
+            "vwap": vwap_v,
+            "williams_r": wr,
+        },
     }
 
 
diff --git a/src/main.py b/src/main.py
index 95f4e03..c94ee50 100644
--- a/src/main.py
+++ b/src/main.py
@@ -148,6 +148,15 @@ async def main():
     )
 
     broker = ExchangeManager(cfg)
+    if mode == "paper":
+        saved_paper = state_store.get_meta("paper_account", {}) or {}
+        try:
+            if "balance" in saved_paper:
+                broker.paper.balance = float(saved_paper["balance"])
+            broker.paper.total_fees_usdt = float(saved_paper.get("total_fees_usdt", 0.0))
+            broker.paper.total_funding_usdt = float(saved_paper.get("total_funding_usdt", 0.0))
+        except (TypeError, ValueError):
+            print("⚠️ Paper hesap kaydı okunamadı; yapılandırılan başlangıç kasası kullanılıyor.")
     risk = RiskManager(
         stop_loss_pct=r["stop_loss_yuzde"],
         lock_trigger_pct=r["kar_kilit_tetikleyici"],
@@ -231,6 +240,7 @@ async def main():
         executor=executor,
         circuit_breaker=circuit_breaker,
         broker=broker,
+        state_store=state_store,
     )
 
     initial_balance = broker.paper.balance if mode == "paper" else 0.0
@@ -306,8 +316,10 @@ async def main():
         llm_key=api.get("llm_key", ""),
         llm_model=api.get("llm_model", ""),
     )
+    tg_bot.news_engine = news
 
     last_ind: dict[str, float] = {s: 0.0 for s in symbols}
+    last_indicators: dict[str, dict] = {}
     last_candle_ts: dict[str, float] = {}
     last_ml: dict[str, dict] = {
         s: {"score": 0.0, "prob_up": 0.5, "direction": "NOTR", "backend": "numpy_gbdt"}
@@ -350,6 +362,7 @@ async def main():
 
         live_scores[s] = {
             "symbol": s,
+            **last_indicators.get(s, {}),
             "price": round(price, 4),
             "total": combined["total"],
             "signal": combined["signal"],
@@ -398,7 +411,9 @@ async def main():
     ):
         tick_count["n"] += 1
         whale = flows[symbol].add_trade(price, qty, buyer_maker)
-        await executor.on_price_tick(symbol, price)
+        pos = executor.positions.get(symbol)
+        if pos is None or (getattr(pos, "exchange", None) or exchanges[0]) == exchange:
+            await executor.on_price_tick(symbol, price)
         if whale is not None:
             await alert(
                 f"🐋 BALİNA {whale.side} {symbol}: "
@@ -408,7 +423,9 @@ async def main():
 
     async def on_price(exchange: str, symbol: str, price: float):
         arb.update_quote(exchange, symbol, price, price)
-        await executor.on_price_tick(symbol, price)
+        pos = executor.positions.get(symbol)
+        if pos is None or (getattr(pos, "exchange", None) or exchanges[0]) == exchange:
+            await executor.on_price_tick(symbol, price)
         opp = arb.check_opportunity(symbol)
         if opp:
             await arb.execute_arbitrage(opp, broker, alert)
@@ -433,6 +450,7 @@ async def main():
             )
             await evaluate(symbol, price)
 
+    contract_sizes = await broker.get_contract_sizes()
     market = MarketData(
         symbols,
         exchanges,
@@ -445,6 +463,8 @@ async def main():
         state_store=state_store,
         executor=executor,
         ping_interval_sec=float(hz.get("ws_ping_saniye", 15.0)),
+        market_type=broker.default_type,
+        contract_sizes=contract_sizes,
     )
 
     async def reconcile_loop():
@@ -469,13 +489,22 @@ async def main():
                             raise ValueError(f"{s} için yeterli kapanmış mum yok ({len(df)}/60)")
                         candle_ts = float(df["ts"].iloc[-1])
                         is_new_candle = last_candle_ts.get(s) != candle_ts
-                        funding = await broker.fetch_funding(s)
+                        open_pos = executor.positions.get(s)
+                        funding = await broker.fetch_funding(
+                            s, exchange=getattr(open_pos, "exchange", None) if open_pos else None
+                        )
 
                         # ML ve göstergeler yalnızca yeni KAPANMIŞ mumda yeniden
                         # eğitilir/hesaplanır; 15 saniyelik yenileme mum sayısı değildir.
                         if is_new_candle:
                             ind = indicator_score(df, funding)
                             last_ind[s] = ind["score"]
+                            last_indicators[s] = {
+                                **ind.get("snapshot", {}),
+                                "components": ind.get("components", {}),
+                                "funding_rate": funding,
+                                "candle_ts": candle_ts,
+                            }
                             last_candle_ts[s] = candle_ts
                             if use_ml:
                                 last_ml[s] = ml_models[s].predict(df)
@@ -521,6 +550,10 @@ async def main():
                                 executor.set_atr(s, atr_value)
 
                         price = market.get_price(s) or float(df["close"].iloc[-1])
+                        if mode == "paper":
+                            executor.apply_funding(
+                                s, funding, price, enabled=broker.paper_funding_enabled
+                            )
                         oi = await broker.fetch_open_interest(s)
                         if oi is not None and oi > 0:
                             flows[s].update_open_interest(oi, price)
@@ -537,6 +570,17 @@ async def main():
                 bal = await broker.fetch_balance_usdt()
                 unreal = executor.total_unrealized_usdt()
                 state_store.record_equity(bal, bal + unreal, len(executor.positions))
+                if mode == "paper":
+                    state_store.set_meta(
+                        "paper_account",
+                        {
+                            "balance": broker.paper.balance,
+                            "start_balance": broker.paper.start_balance,
+                            "total_fees_usdt": broker.paper.total_fees_usdt,
+                            "total_funding_usdt": broker.paper.total_funding_usdt,
+                            "realistic_execution": broker.paper_realistic,
+                        },
+                    )
                 state_store.set_meta("arb_quotes", arb.scan_all(symbols))
                 st = state_store.get_meta("bot_status", {}) or {}
                 st.update(
@@ -551,6 +595,13 @@ async def main():
                         "exchange_health": broker.exchange_health_snapshot(),
                         "sqlite_wal": state_store.get_wal_status(),
                         "stats": executor.stats,
+                        "news": news.mood(),
+                        "market_data": {
+                            "market_type": broker.default_type,
+                            "latency_ms": round(market.avg_latency_ms(), 1),
+                            "last_message_ts": market.last_message_ts,
+                            "reconnect_count": market.reconnect_count,
+                        },
                         "arb_total_profit": arb.total_profit_usdt,
                     }
                 )
diff --git a/src/market_data.py b/src/market_data.py
index 0befe4f..75c08f6 100644
--- a/src/market_data.py
+++ b/src/market_data.py
@@ -25,8 +25,17 @@ def to_binance_stream(symbol: str) -> str:
     return symbol.replace("/", "").split(":")[0].lower()
 
 
-def to_okx_inst(symbol: str) -> str:
-    return symbol.replace("/", "-").split(":")[0]
+def to_okx_inst(symbol: str, market_type: str = "spot") -> str:
+    base = symbol.replace("/", "-").split(":")[0]
+    return f"{base}-SWAP" if market_type == "swap" else base
+
+
+def binance_ws_base(market_type: str = "spot") -> str:
+    return (
+        "wss://fstream.binance.com"
+        if market_type == "swap"
+        else "wss://stream.binance.com:9443"
+    )
 
 
 class MarketData:
@@ -47,6 +56,8 @@ class MarketData:
         ping_timeout_sec: float = 10.0,
         recv_timeout_sec: float = 25.0,
         max_session_sec: float = 23 * 3600,
+        market_type: str = "spot",
+        contract_sizes: dict | None = None,
     ):
         self.symbols = symbols
         self.exchanges = exchanges
@@ -64,6 +75,10 @@ class MarketData:
         self.ping_timeout_sec = ping_timeout_sec
         self.recv_timeout_sec = recv_timeout_sec
         self.max_session_sec = max_session_sec
+        if market_type not in {"spot", "swap"}:
+            raise ValueError("market_type yalnızca spot veya swap olabilir")
+        self.market_type = market_type
+        self.contract_sizes = contract_sizes or {}
 
         self._running = False
         self.prices: dict[str, float] = {}
@@ -75,6 +90,19 @@ class MarketData:
         self.reconnect_count: int = 0
         self.recovered_positions_on_reconnect: int = 0
 
+    def normalize_quantity(self, exchange: str, symbol: str, qty: float) -> float | None:
+        """OKX Swap kontratlarını coin miktarına çevirir.
+
+        ``contractSize`` bilinmiyorsa ``None`` döner; böylece kontrat adedi
+        yanlışlıkla coin gibi kullanılıp para akışı şişirilmez.
+        """
+        if exchange != "okx" or self.market_type != "swap":
+            return float(qty)
+        contract_size = self.contract_sizes.get((exchange, symbol))
+        if contract_size is None or float(contract_size) <= 0:
+            return None
+        return float(qty) * float(contract_size)
+
     def avg_latency_ms(self) -> float:
         return sum(self._lat) / len(self._lat) if self._lat else 0.0
 
@@ -172,7 +200,7 @@ class MarketData:
             streams.append(f"{b}@aggTrade")
             streams.append(f"{b}@bookTicker")
             streams.append(f"{b}@depth20@100ms")
-        url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
+        url = f"{binance_ws_base(self.market_type)}/stream?streams={'/'.join(streams)}"
         rev = {to_binance_stream(s): s for s in self.symbols}
         first_connect = True
 
@@ -303,10 +331,11 @@ class MarketData:
         url = "wss://ws.okx.com:8443/ws/v5/public"
         args = []
         for s in self.symbols:
-            inst = to_okx_inst(s)
+            inst = to_okx_inst(s, self.market_type)
             args.append({"channel": "trades", "instId": inst})
             args.append({"channel": "tickers", "instId": inst})
-        rev = {to_okx_inst(s): s for s in self.symbols}
+            args.append({"channel": "books5", "instId": inst})
+        rev = {to_okx_inst(s, self.market_type): s for s in self.symbols}
         first_connect = True
 
         while self._running:
@@ -348,11 +377,12 @@ class MarketData:
                             if ch == "trades":
                                 for t in msg["data"]:
                                     price = float(t["px"])
-                                    qty = float(t["sz"])
+                                    raw_qty = float(t["sz"])
+                                    qty = self.normalize_quantity("okx", sym, raw_qty)
                                     self.prices[f"okx:{sym}"] = price
                                     self._mark_lat(t.get("ts"))
                                     buyer_maker = t.get("side") == "sell"
-                                    if self.on_trade:
+                                    if self.on_trade and qty is not None and qty > 0:
                                         await self.on_trade(
                                             "okx", sym, price, qty, buyer_maker
                                         )
@@ -361,23 +391,28 @@ class MarketData:
                                     price = float(t["last"])
                                     bid_p = float(t.get("bidPx") or price)
                                     ask_p = float(t.get("askPx") or price)
-                                    bid_q = float(t.get("bidSz") or 1.0)
-                                    ask_q = float(t.get("askSz") or 1.0)
                                     self.prices[f"okx:{sym}"] = price
-                                    self.quotes.setdefault(sym, {})["okx"] = (
-                                        bid_p,
-                                        ask_p,
-                                    )
+                                    self.quotes.setdefault(sym, {})["okx"] = (bid_p, ask_p)
                                     self._mark_lat(t.get("ts"))
-                                    if self.on_book:
-                                        await self.on_book(
-                                            "okx",
-                                            sym,
-                                            [(bid_p, bid_q)],
-                                            [(ask_p, ask_q)],
-                                        )
                                     if self.on_price:
                                         await self.on_price("okx", sym, price)
+                            elif ch == "books5" and self.on_book:
+                                for book in msg["data"]:
+                                    bids, asks = [], []
+                                    for raw_price, raw_qty, *_ in book.get("bids", []):
+                                        qty = self.normalize_quantity("okx", sym, float(raw_qty))
+                                        if qty is not None and qty > 0:
+                                            bids.append((float(raw_price), qty))
+                                    for raw_price, raw_qty, *_ in book.get("asks", []):
+                                        qty = self.normalize_quantity("okx", sym, float(raw_qty))
+                                        if qty is not None and qty > 0:
+                                            asks.append((float(raw_price), qty))
+                                    if bids and asks:
+                                        self.quotes.setdefault(sym, {})["okx"] = (
+                                            bids[0][0], asks[0][0]
+                                        )
+                                        self._mark_lat(book.get("ts"))
+                                        await self.on_book("okx", sym, bids, asks)
                         except Exception:
                             continue
             except Exception as e:
@@ -396,7 +431,7 @@ class MarketData:
         tasks = []
         if "binance" in self.exchanges:
             tasks.append(asyncio.create_task(self._binance_loop()))
-            if self.on_liquidation:
+            if self.market_type == "swap" and self.on_liquidation:
                 tasks.append(asyncio.create_task(self._binance_liq_loop()))
         if "okx" in self.exchanges:
             tasks.append(asyncio.create_task(self._okx_loop()))
diff --git a/src/news.py b/src/news.py
index 5267bb4..daa95be 100644
--- a/src/news.py
+++ b/src/news.py
@@ -16,8 +16,10 @@
 from __future__ import annotations
 
 import asyncio
+import calendar
 import re
 import time
+from datetime import datetime
 from collections import deque
 from dataclasses import dataclass, field
 
@@ -205,6 +207,7 @@ class NewsEngine:
         score: float,
         urgent: bool,
         tags: list,
+        published_ts: float | None = None,
     ) -> NewsItem:
         clean_title = sanitize_external_text(title, max_len=350)
         clean_source = sanitize_external_text(source, max_len=80)
@@ -212,8 +215,12 @@ class NewsEngine:
         fg = self.fg.score_sync(clean_title) if self.fear_greed_on else 50.0
         if urgent:
             fg = min(fg, 8.0)
+        now = time.time()
+        event_ts = float(published_ts) if published_ts is not None else now
+        # Gelecekten gelen bozuk tarihlerin haberi süresiz taze göstermesini önle.
+        event_ts = min(event_ts, now)
         item = NewsItem(
-            time.time(),
+            event_ts,
             clean_title,
             clean_source,
             clean_url,
@@ -225,10 +232,10 @@ class NewsEngine:
             False,
         )
         self.items.append(item)
-        if urgent:
-            self._veto_until = time.time() + 30 * 60
-        elif self.fear_greed_on and fg < self.fear_veto_low:
-            self._veto_until = time.time() + 15 * 60
+        if urgent and event_ts + 30 * 60 > now:
+            self._veto_until = max(self._veto_until, event_ts + 30 * 60)
+        elif self.fear_greed_on and fg < self.fear_veto_low and event_ts + 15 * 60 > now:
+            self._veto_until = max(self._veto_until, event_ts + 15 * 60)
         return item
 
     def push_item(self, title: str, source: str, url: str = "") -> NewsItem:
@@ -255,6 +262,8 @@ class NewsEngine:
                 raw_summary = getattr(e, "summary", "") or getattr(e, "description", "")
                 summary = sanitize_external_text(raw_summary, max_len=500)
                 score, urgent, tags = score_text(title, summary)
+                published = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
+                published_ts = calendar.timegm(published) if published else time.time()
                 self._register(
                     title,
                     parsed.feed.get("title", feed_url),
@@ -262,6 +271,7 @@ class NewsEngine:
                     score,
                     urgent,
                     tags,
+                    published_ts=published_ts,
                 )
         except Exception:
             pass
@@ -289,8 +299,16 @@ class NewsEngine:
                     score = max(-95, min(95, score + net * 5))
                 except Exception:
                     pass
+                published_ts = time.time()
+                try:
+                    published_ts = datetime.fromisoformat(
+                        str(p.get("published_at", "")).replace("Z", "+00:00")
+                    ).timestamp()
+                except (ValueError, TypeError):
+                    pass
                 self._register(
-                    title, "CryptoPanic", sanitize_url(p.get("url", "")), score, urgent, tags
+                    title, "CryptoPanic", sanitize_url(p.get("url", "")),
+                    score, urgent, tags, published_ts=published_ts,
                 )
         except Exception:
             pass
diff --git a/src/telegram.py b/src/telegram.py
index b7f5f12..9baf29f 100644
--- a/src/telegram.py
+++ b/src/telegram.py
@@ -67,12 +67,16 @@ class InteractiveTelegramBot:
         circuit_breaker=None,
         broker=None,
         poll_interval: float = 2.5,
+        state_store=None,
+        news_engine=None,
     ):
         self.token = token.strip() if token else ""
         self.allowed_chat_id = str(allowed_chat_id).strip() if allowed_chat_id else ""
         self.executor = executor
         self.circuit_breaker = circuit_breaker
         self.broker = broker
+        self.state_store = state_store
+        self.news_engine = news_engine
         self.poll_interval = poll_interval
         self._last_update_id: int = 0
         self._running: bool = False
@@ -99,6 +103,9 @@ class InteractiveTelegramBot:
             cmd = cmd.split("@")[0]
         plain = clean.casefold()
 
+        if cmd in ("/piyasa", "/market", "/analiz") or plain in {"piyasa", "analiz"}:
+            return mask_secrets(await self._format_market_report())
+
         if cmd in ("/guncel", "/güncel", "/pozisyonlar", "/positions") or plain in {
             "güncel", "guncel", "pozisyonlar", "açık pozisyonlar", "acik pozisyonlar",
         }:
@@ -146,6 +153,7 @@ class InteractiveTelegramBot:
                 "🤖 KRIPTO-BOT Uzaktan Komuta Menüsü:\n"
                 "• /durum — Anlık kasa, K/Z ve açık pozisyonlar\n"
                 "• /guncel veya güncel — Güncel fiyatlarla yalnızca açık pozisyonlar\n"
+                "• /piyasa — MA/EMA/RSI/MACD, para akışı, funding ve haberler\n"
                 "• /karzar veya /pnl — Gerçekleşen ve açık K/Z özeti\n"
                 "• /kill — 🚨 TÜM POZİSYONLARI ACİL KAPAT ve Botu Kilitle\n"
                 "• /durdur — Yeni işlem açılışını duraklat\n"
@@ -239,15 +247,34 @@ class InteractiveTelegramBot:
             if self.circuit_breaker is not None
             else "AKTİF"
         )
-        return [
+        lines = [
             f"• Durum: {cb_status}",
             f"• Nakit Kasa: ${bal:,.2f}",
             f"• Gerçekleşen K/Z (bu oturum): ${realized:+,.2f}",
             f"• Açık K/Z: ${unreal:+,.2f}",
-            f"• Toplam K/Z: ${realized + unreal:+,.2f}",
-            f"• Toplam Özsermaye: ${bal + unreal:,.2f}",
-            f"• Kapanan işlem: {trades} ({wins} kâr / {losses} zarar)",
         ]
+        paper = getattr(self.broker, "paper", None) if self.broker is not None else None
+        if paper is not None and getattr(self.broker, "mode", "") == "paper":
+            fees = float(getattr(paper, "total_fees_usdt", 0.0) or 0.0)
+            funding = float(getattr(paper, "total_funding_usdt", 0.0) or 0.0)
+            start_balance = float(getattr(paper, "start_balance", bal) or bal)
+            total_pnl = bal - start_balance + unreal
+            lines.extend(
+                [
+                    f"• Toplam komisyon: ${fees:,.2f}",
+                    f"• Funding (ödeme - / alacak +): ${funding:+,.2f}",
+                    f"• Net Paper K/Z: ${total_pnl:+,.2f}",
+                ]
+            )
+        else:
+            lines.append(f"• Toplam K/Z: ${realized + unreal:+,.2f}")
+        lines.extend(
+            [
+                f"• Toplam Özsermaye: ${bal + unreal:,.2f}",
+                f"• Kapanan işlem: {trades} ({wins} kâr / {losses} zarar)",
+            ]
+        )
+        return lines
 
     async def _financial_snapshot(self):
         quotes, bal = await asyncio.gather(
@@ -260,6 +287,55 @@ class InteractiveTelegramBot:
         )
         return quotes, float(bal), float(unreal)
 
+    async def _format_market_report(self) -> str:
+        scores = {}
+        if self.state_store is not None:
+            try:
+                scores = self.state_store.get_meta("live_scores", {}) or {}
+            except Exception:
+                scores = {}
+        lines = ["📈 CANLI PİYASA / TEKNİK ANALİZ", f"🕒 {self._timestamp()}"]
+        if not scores:
+            lines.append("Henüz kapanmış mum ve piyasa verisi oluşmadı.")
+        for symbol, row in list(scores.items())[:6]:
+            if not isinstance(row, dict):
+                continue
+
+            def fmt(key, digits=2):
+                value = row.get(key)
+                if value is None:
+                    return "—"
+                try:
+                    return f"{float(value):,.{digits}f}"
+                except (TypeError, ValueError):
+                    return "—"
+
+            funding = row.get("funding_rate")
+            funding_text = "—" if funding is None else f"{float(funding) * 100:+.4f}%"
+            lines.extend(
+                [
+                    f"\n• {symbol} — {row.get('signal', 'YOK')} / skor {fmt('total', 1)}",
+                    f"  Fiyat: {fmt('price', 4)} | MA20/50: {fmt('ma20', 4)} / {fmt('ma50', 4)}",
+                    f"  EMA9/21/50/200: {fmt('ema9', 4)} / {fmt('ema21', 4)} / {fmt('ema50', 4)} / {fmt('ema200', 4)}",
+                    f"  RSI(14): {fmt('rsi', 1)} | MACD: {fmt('macd', 4)} / Sinyal: {fmt('macd_signal', 4)} / Hist: {fmt('macd_hist', 4)}",
+                    f"  Para akışı: {fmt('para_akisi', 1)} | Bid/Ask: {fmt('bid_ask_ratio', 2)} | Funding: {funding_text}",
+                ]
+            )
+        if self.news_engine is not None:
+            mood = self.news_engine.mood()
+            lines.extend(
+                [
+                    "\n📰 HABER AKIŞI",
+                    f"• Duygu skoru: {mood.get('score', 0):+.1f} | Korku/Açgözlülük: {mood.get('fear_greed', 50):.1f}",
+                    f"• Giriş vetosu: {'VAR' if mood.get('veto') else 'yok'}",
+                ]
+            )
+            latest = mood.get("latest") or {}
+            if latest.get("title"):
+                title = sanitize_external_text(latest["title"], max_len=140)
+                lines.append(f"• Son: {title} [{latest.get('source', '')}]")
+        return "\n".join(lines)
+
     async def _format_status_report(self) -> str:
         quotes, bal, unreal = await self._financial_snapshot()
         lines = [
diff --git a/tests/test_regressions.py b/tests/test_regressions.py
index 9a3828d..704d378 100644
--- a/tests/test_regressions.py
+++ b/tests/test_regressions.py
@@ -14,10 +14,13 @@ from src.backtest import EventDrivenBacktester, FillEvent, SignalEvent
 from src.circuit_breaker import CircuitBreaker
 from src.config import LIVE_CONFIRMATION, ConfigError, load_config
 from src.dashboard import ProductionBotHub, create_dashboard_app
-from src.exchanges import ExchangeManager
+from src.exchanges import ExchangeManager, PaperBroker
 from src.executor import Executor
 from src.health import build_health_payload
+from src.indicators import indicator_score
 from src.main import ohlcv_to_df
+from src.market_data import MarketData, binance_ws_base, to_okx_inst
+from src.news import NewsEngine
 from src.reconcile import reconcile_positions
 from src.risk import Position, RiskManager
 from src.sizing import KellyTracker, PositionSizer
@@ -399,6 +402,117 @@ def test_backtest_pyramiding_respects_total_margin_cap():
     assert len(engine.events) == 0
 
 
+def test_swap_market_data_uses_correct_instruments_and_contract_sizes():
+    assert to_okx_inst(SYMBOL, "swap") == "BTC-USDT-SWAP"
+    assert to_okx_inst(SYMBOL, "spot") == "BTC-USDT"
+    assert "fstream.binance.com" in binance_ws_base("swap")
+    market = MarketData(
+        [SYMBOL], ["okx"], market_type="swap",
+        contract_sizes={("okx", SYMBOL): 0.01},
+    )
+    assert market.normalize_quantity("okx", SYMBOL, 2) == pytest.approx(0.02)
+    assert market.normalize_quantity("binance", SYMBOL, 2) == 2
+    missing = MarketData([SYMBOL], ["okx"], market_type="swap")
+    assert missing.normalize_quantity("okx", SYMBOL, 2) is None
+
+
+def test_indicator_snapshot_exposes_requested_ma_ema_rsi_macd():
+    import numpy as np
+    import pandas as pd
+
+    close = np.linspace(80, 120, 220)
+    df = pd.DataFrame(
+        {
+            "open": close - 0.2,
+            "high": close + 1,
+            "low": close - 1,
+            "close": close,
+            "volume": np.full(220, 100.0),
+        }
+    )
+    result = indicator_score(df, funding_rate=0.0001)
+    snap = result["snapshot"]
+    for key in ("ma20", "ma50", "ema9", "ema21", "ema50", "ema200", "rsi", "macd", "macd_signal", "macd_hist"):
+        assert key in snap
+    assert snap["ma20"] > snap["ma50"]
+    assert snap["ema9"] > snap["ema21"] > snap["ema50"]
+    assert snap["ema200"] > 0
+    assert "ma_trend" in result["components"]
+
+
+def test_realistic_paper_market_uses_ask_for_buy_and_bid_for_sell():
+    cfg = paper_exchange_config()
+    cfg["paper"] = {"gercekci_yurutme": True, "funding_aktif": True, "bakiye": 1000}
+    manager = ExchangeManager(cfg)
+
+    class Quotes(TimeoutExchange):
+        async def fetch_ticker(self, symbol):
+            return {"bid": 100.0, "ask": 102.0, "last": 101.0}
+
+    manager._ex = {"binance": Quotes()}
+    manager._default_primary = manager._active_primary = "binance"
+    buy = run(manager.market_order(SYMBOL, "buy", 1, price_hint=101, exchange="binance"))
+    sell = run(manager.market_order(SYMBOL, "sell", 1, price_hint=101, exchange="binance"))
+    assert buy["price"] == 102 and sell["price"] == 100
+    assert buy["price_source"] == "rest_bid_ask"
+    assert buy["slippage_pct"] == pytest.approx(100 / 101)
+    run(manager.close())
+
+
+def test_paper_funding_is_time_weighted_and_directional(tmp_path):
+    class Broker:
+        mode = "paper"
+
+        def __init__(self):
+            self.paper = PaperBroker(balance_usdt=1000)
+
+    broker = Broker()
+    executor = Executor(broker, RiskManager(), Strategy(), state_store=StateStore(tmp_path / "funding.db"))
+    executor.positions[SYMBOL] = Position(SYMBOL, "LONG", 100, 2, 95)
+    executor._funding_last[SYMBOL] = time.time() - 3600
+    delta = executor.apply_funding(SYMBOL, 0.0008, 100, enabled=True)
+    assert delta == pytest.approx(-0.02, abs=0.001)
+    assert broker.paper.total_funding_usdt == pytest.approx(delta)
+
+    executor.positions[SYMBOL].side = "SHORT"
+    executor._funding_last[SYMBOL] = time.time() - 3600
+    short_delta = executor.apply_funding(SYMBOL, 0.0008, 100, enabled=True)
+    assert short_delta == pytest.approx(0.02, abs=0.001)
+
+
+def test_old_news_does_not_create_fresh_veto():
+    engine = NewsEngine([], fear_greed_on=False)
+    engine._register(
+        "Old exchange hack", "RSS", "", -90, True, ["KRİTİK"],
+        published_ts=time.time() - 7200,
+    )
+    mood = engine.mood()
+    assert mood["score"] == 0
+    assert not mood["veto"]
+    engine.push_item("New exchange hack", "RSS")
+    assert engine.mood()["veto"]
+
+
+def test_live_market_order_reads_actual_fill_instead_of_requested_qty():
+    class DeferredFill(TimeoutExchange):
+        async def create_market_order(self, symbol, side, qty, params=None):
+            self.calls += 1
+            return {"id": "order-1", "status": "open", "filled": None, "average": None}
+
+        async def fetch_order(self, oid, symbol):
+            return {"id": oid, "status": "closed", "filled": 0.4, "average": 101.0}
+
+    manager = ExchangeManager(paper_exchange_config())
+    manager.mode = "live"
+    fake = DeferredFill()
+    manager._ex = {"binance": fake}
+    manager._default_primary = manager._active_primary = "binance"
+    fill = run(manager.market_order(SYMBOL, "buy", 2, price_hint=100, exchange="binance"))
+    assert fill["qty"] == 0.4 and fill["price"] == 101
+    assert fake.calls == 1
+    run(manager.close())
+
+
 class TelegramQuoteBroker:
     def __init__(self, fail=False):
         self.fail = fail
@@ -529,6 +643,45 @@ def test_telegram_poll_filters_unauthorized_and_accepts_plain_guncel(monkeypatch
     assert posts[0][1]["json"]["text"] == "güncel pozisyon raporu"
 
 
+def test_telegram_market_report_reads_indicators_and_news(tmp_path):
+    store = StateStore(tmp_path / "market-report.db")
+    store.set_meta(
+        "live_scores",
+        {
+            SYMBOL: {
+                "symbol": SYMBOL,
+                "signal": "LONG",
+                "total": 62,
+                "price": 101,
+                "ma20": 100,
+                "ma50": 99,
+                "ema9": 100.5,
+                "ema21": 100.2,
+                "ema50": 100.1,
+                "ema200": 95,
+                "rsi": 61,
+                "macd": 1.2,
+                "macd_signal": 1.0,
+                "macd_hist": 0.2,
+                "para_akisi": 35,
+                "bid_ask_ratio": 1.8,
+                "funding_rate": 0.0001,
+            }
+        },
+    )
+    news = NewsEngine([])
+    news.push_item("ETF approved for Bitcoin", "TestRSS")
+    bot = InteractiveTelegramBot(
+        allowed_chat_id="authorized", state_store=store, news_engine=news
+    )
+    report = run(bot.handle_command("piyasa", sender_chat_id="authorized"))
+    assert "CANLI PİYASA / TEKNİK ANALİZ" in report
+    assert "MA20/50: 100.0000 / 99.0000" in report
+    assert "RSI(14): 61.0" in report
+    assert "Funding: +0.0100%" in report
+    assert "ETF approved for Bitcoin" in report
+
+
 def test_dashboard_requires_token_and_production_queues_commands(tmp_path, monkeypatch):
     token= "***REDACTED***"
     monkeypatch.setenv("DASHBOARD_TOKEN", token)

~~~
