# SENTEZ — PAPER işlem botu (v1.0.0)

Yüklenen arşivdeki (NOVA-BOT, ACARBOT, v94/unified_engine ve risk/walk-forward modülleri) en iyi fikirleri
**sıfırdan, tek ve temiz bir pakette** birleştirir. Önceki kodlardan satır kopyalanmadı; fikirler yeniden yazıldı
ve testlerle kilitlendi.

**Yalnız PAPER.** Gerçek emir yolu, özel API anahtarı, imza veya hesap erişimi yoktur. Yalnız Python standart
kütüphanesi kullanılır (bağımlılık yok). Hiçbir sonuç kârlılık kanıtı değildir.

## Hızlı başlangıç
```bash
python3 sentez_run.py demo                         # sentetik veride boru hattı denemesi
python3 -m unittest discover -s tests -t .         # 75 çevrimdışı test
python3 sentez_run.py fetch --symbols BTCUSDT,ETHUSDT,SOLUSDT --bars 3000   # kamu veri → data/*.csv (ağ gerekir)
python3 sentez_run.py backtest --csv-dir data --out runs/bt
python3 sentez_run.py walkforward --csv-dir data --train 1200 --test 400 --out runs/wf
python3 sentez_run.py live --symbols top --top-n 10 --minutes 240 --out runs/live   # canlı PAPER (ağ gerekir)
```
Ayarlar: `--set conf_th=5 --set risk_pct=0.3` veya `--config ayar.json` (alanlar için `sentez/models.py` → `Config`).

## Mimari
| Modül | Görev | Fikrin kaynağı |
|---|---|---|
| `indicators.py` | EMA, RSI, ATR, ADX, Stoch, OBV, VWAP, CCI, Supertrend, Bollinger, Choppiness; hepsi nedensel | NOVA v2 / acarbot v3.4 |
| `signals.py` | 10 oylu confluence (eşik 2..8), choppiness kapısı, mum boşluğu kapısı | NOVA v2 / ACARBOT |
| `risk.py` | risk bazlı boyut, maliyet/hareket kapısı, yarım-Kelly (opsiyonel), devre kesici | ACARBOT / sizing / circuit_breaker |
| `engine.py` | PAPER defteri: sonraki-açılış dolumu, kötümser çıkış, breakeven, iz süren stop, funding, kapılar | NOVA çekirdeği |
| `backtest.py` | backtest + walk-forward (örneklem-dışı) | walkforward.py |
| `report.py` | metrikler, oy/çıkış/sembol/yön katkı analizi, Markdown rapor | attribution.py |
| `live.py` | Binance **kamu** klines ile canlı PAPER; backtest ile aynı motor | NOVA `live` |
| `data.py` | CSV, doğrulama, sentetik veri, Binance kamu uçları | — |

## Karar zinciri
1. Kapanmış mum → 10 oy (EMA dizilişi, MACD, RSI, ADX+EMA, Stoch, OBV, CCI, Supertrend, VWAP, Bollinger).
2. `|skor| ≥ conf_th`, choppiness < `max_chop`, mum sürekliliği (iki ardışık eksik mum = `CANDLE_GAP`).
3. Kapılar: devre kesici → `EDGE_BELOW_COST` (hedef hareket / gidiş-dönüş maliyet ≥ `min_edge_ratio`) → breadth → cooldown.
4. **Giriş sonraki mumun açılışında**; `PRICE_DRIFT`, `MAX_POSITIONS`, `MAX_SAME_SIDE`, `MAX_GROSS`, `LIQ_TOO_CLOSE`.
5. Çıkış: stop (1.2 ATR) · hedef (2.4 ATR) · 0.8R'de breakeven · 1R'den iz süren stop · en fazla 30 mum.

## Kötümser varsayımlar (kasıtlı)
- Aynı mumda stop ve hedef birlikte görülürse **stop kazanır**; stop'u aşan açılışta dolum açılıştan olur.
- Breakeven/iz süren stop mum kapandıktan sonra güncellenir (aynı mumda kullanılmaz).
- Taker ücreti iki yönde + kayma + yarım makas aleyhe; funding sabit varsayım (long öder).
- Walk-forward'da eğitim penceresinde seçilen ayar, hiç görülmemiş test penceresinde sınanır ve **sabit varsayılanla** karşılaştırılır.

## Dürüst sınırlar
- Defter derinliği, kısmi dolum ve gerçek tasfiye motoru modellenmedi; tasfiye `1/kaldıraç − bakım marjı` yaklaşımıdır.
- `fetch` ve `live` ağ gerektirir; bu ortamda ağ kapalı olduğu için **Binance çağrıları burada denenmedi**. Canlı koşucu
  sahte veri kaynaklarıyla (ağsız) test edildi; gerçek ağ davranışı kendi makinenizde doğrulanmalı.
- Varsayılan 15 dk mumlarda sentetik veride maliyetler sonrası beklenti **negatiftir** (maliyetsiz pozitif). Bu, botun
  sihirli olmadığını gösterir: kenar bulunmadan canlıya geçmek zarar üretir. Önce kendi verinizde walk-forward çalıştırın.
- Kısa koşular (< 30 işlem) istatistiksel olarak anlamsızdır; rapor bunu açıkça yazar.
- Bilinçli olarak YZ/LLM "konseyi" yoktur: arşivde anahtarsız hiç çağrılmayan bir iskelet olduğu için kopyalamak sahte onay üretirdi.
