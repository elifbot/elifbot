# ACAR FUTURES APEX — v1.0 (PAPER)

Geliştirme tabanı: `bot_final_v2` + `CIKARILAN_KODLAR` arşivindeki NOVA/ACARBOT yetenek notları, göstergeler, para akışı ve risk araştırmaları.

> **Güvenlik durumu: PAPER ONLY.** Bu sürümde gerçek borsaya emir gönderen kod, API imzası veya hesap erişimi yoktur. Kârlılık garantisi vermez.

## Sabit işlem profili

| Kural | Değer |
|---|---:|
| Başlangıç sanal bakiye | 1.000 USDT |
| İşlem başına teminat | 50 USDT |
| Kaldıraç | 10x |
| Azami nominal | 500 USDT |
| Pozisyon başına planlanan zarar bütçesi | 25 USDT |
| Günlük zarar durdurma | 100 USDT |
| Aynı anda azami pozisyon | 4 |
| Emir yönü | Post-only / maker simülasyonu |
| Zaman dilimi | 5 dakika, yalnız kapanmış mum |

25 USDT bir **risk bütçesidir**, mutlak gerçekleşen zarar garantisi değildir. Gap, kayma, komisyon, funding ve likidite koşulları gerçekleşen sonucu değiştirebilir.

## Başlıca yetenekler

- Binance USDⓈ-M ve OKX USDT perpetual kamu piyasa verisi.
- 10 faktörlü confluence stratejisi: EMA dizilimi, MACD, RSI, ADX/+DI/-DI, Stochastic, OBV, CCI, Supertrend, VWAP, Bollinger kırılımı.
- Piyasa rejimi filtresi: trend / yatay / aşırı volatilite.
- Mum bütünlüğü ve kapanmış mum doğrulaması; eksik/bozuk mumda sinyal yok.
- ATR tabanlı stop mesafesi ve sabit 500 USDT nominal / 50 USDT teminat / 10x risk planı.
- Günlük zarar ve pozisyon sayısı sınırları.
- SQLite WAL durum kaydı ve yeniden başlatma kurtarması.
- Maker kuyruk yaşam döngüsü için ayrı konservatif PAPER simülatörü (gerçek borsa kuyruğu değildir).
- CVD/taker akışı/defter dengesizliği için veri analiz modülü.
- Funding ve yaklaşık likidasyon mesafesi yardımcıları.
- Korelasyon ve aynı yön maruziyetini ölçen portföy risk yardımcıları.
- Otomatik çevrimdışı testler.

## Kurulum (Windows)

1. Python 3.11 veya üzerini kur.
2. Bu klasörde `install_windows.bat` dosyasını çalıştır.
3. Kurulum tamamlanınca `run_paper_windows.bat` dosyasını çalıştır.

Manuel kurulum:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m app.main --paper --exchange all --symbols BTCUSDT,ETHUSDT,SOLUSDT --strategy-mode elite --max-positions 4
```

## Linux

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m app.main --paper --exchange all --symbols BTCUSDT,ETHUSDT,SOLUSDT --strategy-mode elite --max-positions 4
```

Tek tarama / tek çevrim için komuta `--once` ekle.

## Strateji seçimi

- `--strategy-mode elite`: varsayılan CLI modu; 10 faktörlü confluence + rejim + veri kalite kapıları.
- `--strategy-mode classic`: önceki FADE + EMA/MACD trend motorları.

Confluence eşiği kodda varsayılan 7/10'dur. Eşik veya parametreler tek bir koşudan sonra otomatik olarak canlıya terfi ettirilmez.

## Önemli doğruluk sınırları

1. Maker kuyruk simülatörü ayrı bir araştırma bileşenidir; mevcut ana paper broker hâlâ emir defteri etkisiyle yaklaşık dolum yapar. Gerçek queue priority, gerçek kısmi dolum ve maker dolum olasılığı kanıtlanmış değildir.
2. Order-flow analiz modülü kamu trade/book verisini alabilecek şekilde tasarlanmıştır; henüz elite oylarına otomatik ağırlık olarak bağlanmamıştır. Veri yoksa `None/available=False` döndürür, sahte sıfır üretmez.
3. Funding ve likidasyon yardımcıları tahmin/screening amaçlıdır. Borsanın bakım marjı kademeleri ve gerçek tasfiye motoru yerine geçmez; funding oranı ana emir kapısına henüz bağlanmamıştır.
4. Korelasyon yardımcısı ve portföy guard modülü vardır; senkronize çoklu-sembol geçmişiyle ana executor'a tam bağlanmış değildir.
5. 1h/4h gerçek üst-zaman-dilimi verisi henüz elite stratejinin zorunlu giriş kapısı değildir. Mevcut rejim filtresi 5m kapanmış mumları kullanır.
6. 102 testin geçmesi kod regresyonlarını kontrol eder; kârlılığı, gerçek maker dolumunu veya canlı dayanıklılığı ispatlamaz.
7. `CIKARILAN_KODLAR` arşivindeki önceki tarihsel raporlarda negatif sonuçlar da vardı. Bu nedenle eski parametreler kârlı varsayılmadı ve hiçbir parametre otomatik optimize edilip onaylanmadı.

## Güvenli geliştirme sırası

1. 48–72 saat kesintisiz PAPER veri/sağlık testi.
2. Yeni tarihsel veri üzerinde çoklu coin, çoklu dönem backtest.
3. Walk-forward ve tamamen ayrılmış out-of-sample test.
4. Gerçekçi maker queue / partial-fill doğrulaması.
5. Funding, mark/index price, maintenance-margin tier ve liquidation kontrolünün borsa bazında bağlanması.
6. Korelasyonlu toplam maruziyetin ana executor'a bağlanması.
7. Ancak bunlardan sonra, ayrı bir testnet adaptörü tasarlanması.

**Canlı işlem bu pakette kapalıdır ve bu ZIP gerçek para ile çalıştırılmamalıdır.**
