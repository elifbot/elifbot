# KRIPTO-BOT v7.8 ↔ futures_bot Karşılaştırması

**Tarih:** 2026-10-27 · **Kaynak:** `KRIPTO-BOT-v7.8-MAIL-PAKETI.zip` (posta eki)

> Crew görev tanımı "Reference ZIP v7.8: KAYNAK İNCELENEMEDİ" diyordu.
> Bu paket **açıldı ve incelendi**; aşağıdaki tespitler gerçek koddan çıkarılmıştır.
> (Crew metinlerindeki "incelenemedi" notu artık **güncel değildir**.)

---

## 1. Boyut

| | KRIPTO-BOT v7.8 | futures_bot (bu teslimat) |
|---|---|---|
| Python satırı | **24.047** | 3.909 |
| Modül | 45 | 35 (daha küçük dosyalar) |
| Test dosyası | 18 | 11 |
| Test sayısı | (çalıştırılmadı) | **119 — hepsi geçiyor** |
| Bağımlılık | ccxt, aiohttp, websockets, feedparser, python-dotenv… | requests, pandas, numpy, tabulate |

## 2. ⚠️ En kritik fark: canlı emir yeteneği

**v7.8 gerçek emir GÖNDEREBİLİR.** Kanıt (koddan):

```python
# src/config.py:140
mode = str(general.get("mod", "paper")).lower()
if mode not in {"paper", "testnet", "live"}: raise ConfigError(...)

# src/exchanges.py:280,314
"apiKey": api.get("binance_key", ""),   # ccxt borsa istemcisi
"apiKey": api.get("okx_key", ""),

# src/exchanges.py:635,1260-1296
await ex.set_leverage(lev, self._ccxt_symbol(symbol))
sl_o = await ex.create_order(..., "STOP_MARKET", ..., {"stopPrice": sl_px, "reduceOnly": True})
o    = await ex.create_order(..., "limit", ..., {"triggerPrice": sl_px, "reduceOnly": True})
```

Ayrıca: `.env` okuma (`python-dotenv`), `TELEGRAM_BOT_TOKEN`,
`WHATSAPP_API_KEY/CLOUD_TOKEN`, `DASHBOARD_TOKEN`, PagerDuty webhook'u,
cryptopanic haber akışı, `graph.facebook.com` (WhatsApp Cloud API).

**futures_bot'ta bunların hiçbiri yok:** `--mode live` → `exit 1`, kimlik
bilgisi okunmaz, yalnızca 4 public GET uç noktası. Bu bir **eksiklik değil,
bilinçli tasarım sınırıdır** (crew'in Phase A güvenlik şartı).

> **Risk notu:** v7.8'i `mod=live` ile çalıştırmak gerçek para riski taşır.
> Bu projede o kod **çalıştırılmadı**, yalnızca okundu.

## 3. v7.8'de olup futures_bot'ta OLMAYAN yetenekler

| Yetenek | v7.8 modülü | Öncelik | Not |
|---|---|---|---|
| SQLite durum kalıcılığı | `state_store.py` | **Yüksek** | Yeniden başlatmada pozisyon kaybını önler |
| Circuit breaker | `circuit_breaker.py` | **Yüksek** | Ardışık zararda otomatik duruş |
| Gelişmiş çıkış kuralları | `exit_rules.py` | **Yüksek** | Trailing, runner, stagnant-adverse çıkışı |
| Pozisyon boyutlandırma | `sizing.py` | Orta | Dinamik marj |
| Risk motoru | `risk.py` | Orta | Bizdeki limitlerin genişletilmişi |
| Walk-forward (ayrı modül) | `walkforward.py` | Orta | Bizde `backtests/walk_forward.py` var |
| Bakım/uzlaştırma | `reconcile.py`, `health.py` | Orta | Durum–gerçeklik karşılaştırması |
| Nitelik/atıf analizi | `attribution.py`, `trade_quality.py`, `cohort_report.py` | Düşük | Hangi göstergenin katkısı |
| Panel | `dashboard.py` | Düşük | Streamlit benzeri |
| Telegram / WhatsApp | `telegram.py`, `whatsapp.py` | Düşük | **Kimlik bilgisi gerektirir** |
| Haber / duygu | `news.py`, `sentiment_ai.py` | Düşük | Dış API anahtarı |
| ML tahminci | `ml_predictor.py` | Düşük | Doğrulanmamış |
| Arbitraj | `arbitrage.py` | Düşük | Ayrı ürün |
| Vadeli zekâ (funding/OI/Rubik) | `derivatives_intel.py` | **Orta** | Bizde stub; v7.8 gerçek uç noktalar kullanıyor |
| Money flow | `moneyflow.py` | Düşük | |

## 4. futures_bot'ta olup v7.8'de olmayan (veya zayıf olan)

| Konu | futures_bot | v7.8 |
|---|---|---|
| Dana göre paper-only zorlaması | ✅ `exit 1` + test | ❌ canlı mod açık |
| URL allowlist (4 uç nokta) | ✅ kodda + test | ❌ çok sayıda host |
| Funding'in "bilinmiyor" etiketlenmesi | ✅ her çıktıda | ⚠️ `funding_aktif` bayrağı var |
| Sharpe bastırma (<30 işlem) | ✅ | ❓ |
| EMA şeridi yön hatası düzeltmesi | ✅ (test ile kilitli) | ❓ |
| Bollinger `ddof=1` | ✅ | ❓ |
| Lookahead guard (backtest motorunda) | ✅ `LookaheadError` + test | ⚠️ `walkforward.py` var, guard doğrulanmadı |
| Aile bazlı ablasyon | ✅ `backtests/ablation.py` | ❌ |
| Test paketinin çalıştığının kanıtı | ✅ `119 passed` | ❌ çalıştırılmadı |

## 5. Öneri (yol haritası)

1. **v7.8'i canlı modda çalıştırmayın.** Önce `mod: paper` ile sınırlayın,
   anahtar içeren `.env` dosyasını bu depoya **koymayın**.
2. Yüksek öncelikli 3 modülü **paper-only uyarlayarak** taşıyın:
   `state_store` (SQLite kalıcılık), `circuit_breaker`, `exit_rules`.
   Taşıma sırasında: kimlik bilgisi okuma yok, ağ çağrısı yok, test zorunlu.
3. `derivatives_intel` içindeki funding/OI uç noktaları **doğrulanırsa**
   Phase C stub'ları gerçek veriye çevrilebilir (allowlist'e eklenerek).
4. Telegram/WhatsApp/panel gibi dış entegrasyonlar ayrı bir "operasyon"
   deposunda tutulmalı; çekirdek bot bunlardan arındırılmış kalmalı.

## 6. Bu karşılaştırmanın sınırı

- v7.8 **çalıştırılmadı**; yalnızca statik okuma yapıldı. Davranışı,
  testleri veya performansı hakkında **hiçbir iddia** yoktur.
- "❓" işaretli hücreler **doğrulanmadı** anlamına gelir; "yok" demek değildir.
