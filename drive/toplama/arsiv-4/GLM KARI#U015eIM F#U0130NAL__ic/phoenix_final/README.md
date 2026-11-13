# PHOENIX FINAL v3.0 — Kripto Futures Confluence Bot

**4 sistemden sentez:** AcarBot v7.2 (orijinal arşiv) · ChatGPT FUSION_PRO 4.0 · Claude sentez-bot · Phoenix v2.0. Detaylı karşılaştırma için `KARSILASTIRMA.md` dosyasına bakın.

## Ne içerir?

| Katman | Kaynak fikir | Uygulama |
|---|---|---|
| Strateji | 8 faktörlü confluence (EMA, MACD, RSI, ADX+DI, hacim, VWAP, Supertrend, Bollinger) | `phoenix/strategy.py` |
| Rejim + HTF | FUSION_PRO: TREND/RANGE/HIGH_VOL/LOW_VOL + 1h/4h oybirliği filtresi | `phoenix/strategy.py` |
| Vetolar | CHOP (sentez) · sıkışma + hacim-z (FUSION) · edge/maliyet kapısı (sentez) · mum boşluğu (sentez) | `phoenix/strategy.py` |
| Motor | Kötümser semantik: giriş sonraki açılışta, stop-once, kayma+makas+ücret+funding | `phoenix/engine.py` |
| Çıkışlar | SL 1.5×ATR, TP 2R, **+1R'de %35 kısmi kâr**, 0.8R'de başaboya, 1.8×ATR trail, max 30 mum | `phoenix/engine.py` |
| Risk | %0.5 risk/işlem, oynaklığa göre 5x→3x→2x kaldıraç (AcarBot fikri, güvenli bant), isolated margin | `phoenix/risk.py` |
| Kesiciler | Günlük %3 + 4 ardışık kayıp duraksaması + %25 sermaye tabanı + `data/STOP` kill dosyası | `phoenix/risk.py` |
| Veri | Binance→OKX→Bybit kamu failover — **API anahtarı gerektirmez** | `phoenix/datafeed.py` |
| Canlı | ccxt binanceusdm, dry→testnet→live merdiveni, `--confirm-live` kilidi, durum kalıcılığı | `phoenix/exchange.py`, `phoenix/main.py` |
| Doğrulama | Kötümser backtest + walk-forward (OOS) + katkı analizi + 30 test | `phoenix/backtest.py`, `tests/` |

**Reddedilen tehlikeli fikirler** (raporda gerekçesi var): sınırsız piramitleme, çapraz kurtarma (pair rescue), 20x kaldıraç, %5 sabit SL (20x ile likidasyon noktasına eşittir).

## Kurulum

```bash
cd phoenix_final
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q                                            # 30 test — hepsi geçmeli
```

## Kullanım (SIRAYLA!)

```bash
# 1) Anlık sinyal taraması (anahtar gerekmez)
python -m phoenix.main scan

# 2) Backtest — gerçek kamu verisiyle, anahtar gerekmez
python -m phoenix.main backtest --all --bars 3000

# 3) Walk-forward (aşırı uyum denetimi)
python -m phoenix.main walkforward --symbol BTC/USDT:USDT --bars 4000

# 4) PAPER oturum (sanal 10.000 USDT, gerçek kamu verisi, aynı motor)
./run_paper.sh 30          # 30 dakikalık oturum
./run_paper.sh 60          # 1 saatlik oturum
# Sizin planınız: 15dk/30dk/1saatlik oturumlarla BİRKAÇ GÜN.

# 5) Paper testleri bittikten sonra:
python -m phoenix.main live --engine testnet --confirm-live   # .env'e anahtarları koyun
python -m phoenix.main live --engine live --confirm-live      # GERÇEK PARA — en son adım
```

## Güvenlik mekanizmaları

- `data/STOP` dosyasını oluşturun (`touch data/STOP`): bot yeni giriş yapmaz, mevcut pozisyonlar yönetilir. Silinince devam eder.
- Durum (`data/state.json`) kalıcıdır: bot çöksüp yeniden başlasa pozisyonları hatırlar.
- `data/journal.jsonl` her olayı (open/close/tp1/reject) kaydeder; `data/bot.log` konsol+dosya logu tutar.
- Canlı modda SL/TP gerçek borsa emirleridir (reduceOnly STOP_MARKET + TAKE_PROFIT_MARKET, MARK_PRICE).

## Doğrulanmış gerçek sonuçlar (bu repo, sandbox'ta 2026-11-09'da koşuldu)

- **34/34 pytest** testi geçer (nedensellik, stop-once semantiği, ücret/funding, kesiciler).
- **Backtest 15m, 2999 mum (~31 gün), BTC+ETH+SOL, gerçek kamu verisi (Bybit):**
  71 işlem, kazanma %42.3, ort. R **−0.36**, profit factor 0.47, net **−1.18%**.
- **Backtest 1h (config_1h.example.yaml):** 21 işlem, ort. R −0.26, PF 0.64 (n<30 → anlamsız).
- **Walk-forward (4 fold):** OOS ort. R = sabit-ayar OOS ort. R = −0.35 →
  *optimizasyon kazandırmıyor; ama aşırı-uyum da yok.*
- **Canlı dry 5 dk duman-testi:** döngü, durum kalıcılığı ve graceful hata yönetimi çalışıyor.

**Dürüst yorum:** çerçeve (motor, risk, kesiciler, doğrulama altyapısı) sağlam ve kanıtlanmış;
AMA varsayılan 8-faktör stratejisi bu örnekleminde maliyetler sonrası **negatif beklentiye** sahip.
Bu tam olarak paper-test aşamasının amacıdır: `walkforward` + katkı analiziyle (data/BACKTEST.md)
kenar bulunana kadar canlıya GEÇİLMEZ. Katkı analizi bu örneklemede zararın büyük kısmının
STOP çıkışlarından (−113.85) geldiğini, TARGET'ların kârlı (+66.7) olduğunu gösteriyor →
eşik/filtre ayarlarıyla girilecek trade sayısını azaltmak bir sonraki inceleme alanıdır.

## Dürüst sınırlar

- Backtest/walk-forward **geçmiş performanstır**; gelecek getirinin garantisi değildir.
- Tasfiye mesafesi `1/kaldıraç − bakım marjı` yaklaşımıdır; gerçek likidasyon motoru değildir.
- Microstructure verisi (taker akışı, OI, defter derinliği) bu sürümde YOKTUR — FUSION_PRO'daki fikir 15m mum rejimiyle kaba taklit edilir. İsterseniz WebSocket katmanı sonraki adım olur.
- < 30 işlemlik koşular istatistiksel olarak anlamsızdır; rapor bunu açıkça yazar.
- Binance sandbox IP'lerinde engelliyse veri otomatik OKX/Bybit'ten gelir (failover).
