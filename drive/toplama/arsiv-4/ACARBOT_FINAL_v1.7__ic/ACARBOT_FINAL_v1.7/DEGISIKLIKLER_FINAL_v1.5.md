# ACARBOT FINAL v1.5 — Değişiklik Günlüğü (7 Kasım 2026)

Kullanıcı isteği: "12 coin değil, Binance 500+ / OKX 200+ coinin HEPSİ
aynı anda taranacak."

## Yeni: TAM PAZAR TARAMASI (`--scan-all`)
- Coin evreni borsadan otomatik keşfedilir: **Binance 518 + OKX 528 = 1046 feed**
  (sayılar borsa listelerine göre değişir; her açılışta güncellenir).
- `--symbols` yok sayılır; `--scan-cycle-seconds` ile döngü hedefi ayarlanır (vars. 60).
- Binance: exchangeInfo TRADING/USDT (futures'ta PERPETUAL).
- OKX: canlı lineer USDT-SWAP enstrümanları (tokenize hisse swapları dahil).

## Ölçek mimarisi
1. **Paralel mum taraması**: semaphore + rate pacer (Binance 25 istek/sn,
   OKX 8 istek/sn). Tam döngü ~82 sn'de 1046 sembol. Tek tüketici kuyruğu
   executor'da yarış koşulu yaratmaz; aynı mum iki kez değerlendirilmez.
2. **OKX WS parçalama**: 250+ enstrüman 250'lik parçalara bölünür, ayrı
   bağlantılarda çalışır, kuyrukta birleşir; kopma tümünü yeniden bağlar.
3. **Sweep koruması isteğe bağlı**: 1046 defteri sürekli çekmek rate
   limitlerine sığmaz → giriş adayı sembolün defteri sinyal ANINDA
   tazelenir (executor.book_fetcher). Korumadan ödün verilmez.
4. **Veri bütünlüğü ölçeklendi**: dar listede TÜM feed'lerin ısınması
   aranırken tam pazarda çoğunluk (üst sınır 50 feed) yeterli; bayatlık
   oranı yalnız yerleşik feed'lerde sayılır (düşük hacimli coinler
   güvenli modu tetiklemez). Sembol başı tazelik denetimi AYNEN korunur.

## Duman testi sonuçları (3 dk, canlı)
- 278.937 tick (~1550/sn), 952 tekil sembol değerlendirildi
- 2 tam tarama döngüsü (82 sn), 429 hatası: 1 (pacer öncesi 18 idi)
- Güvenli mod: hayır · Hata: yok · Tüm sinyal kapıları çalışıyor

## Test durumu
**250/250 test geçti** (244 v1.4 + 6 tam pazar veri bütünlüğü testi;
toplam 26 yeni v1.5 testi: evren keşfi, CLI, sharding, book_fetcher, rapor).

## Kullanım
```
python -m app.main --mode paper --paper --exchange all --profile apex \
  --motors trend --scan-all --duration-minutes 60
```
Not: PAPER ONLY. 1046 feed'de sinyal kalitesi için varsayılan eşikler
(RVOL 1.5 / spike 3.0) korunur; TREND-only önerilir (v1.4 bulgusu).
