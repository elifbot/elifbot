# Futures Bot v9 — Komisyon ve Limit Giriş Düzeltmeleri

Tarih: 28.10.2026  
Kaynak: Kullanıcının gönderdiği `futures_bot_v7.zip` ve `futures_bot_v8.zip`.

## Kapsam

Bu sürüm strateji eşiklerini değiştirmez. Amaç, v8'de bulunan maker/limit
simülasyon hatalarını düzeltmek ve paper sonuçların komisyon muhasebesini
doğrulamaktır. Varsayılan giriş modu **market** olarak bırakılmıştır.

## Yapılan düzeltmeler

### 1. Maker giriş ücreti gerçekten uygulanıyor

v8'de `--giris limit` seçilse bile `PaperPortfolio` giriş ve çıkışta aynı
varsayılan taker oranını (%0,05) kullanıyordu. `config.MAKER_FEE_RATE` (%0,02)
tanımlı olmasına rağmen kullanılmıyordu.

v9:
- Dolan limit girişinde `entry_fee_rate=config.MAKER_FEE_RATE` kullanılır.
- Market girişte ve tüm çıkışlarda `config.TAKER_FEE_RATE` kullanılır.
- `PaperPortfolio.open_position()` geriye uyumlu, isteğe bağlı
  `entry_fee_rate` parametresi kazanmıştır.

Dosyalar:
- `ws_bot.py`
- `portfolio/paper_futures.py`
- `config.py`

### 2. Limit fiyat payının iki kez uygulanması düzeltildi

v8'de bekleyen limit emir dolduğunda sinyal fiyatı zaten limit fiyatına
getiriliyor, ardından `_pozisyon_ac(..., limit_doldu=True)` içinde
`_limit_fiyati()` ikinci kez çağrılıyordu.

Örnek (%0,05 limit payı):
- LONG 100,00 için doğru limit: **99,95**; hatalı ikinci uygulama: **99,900025**.
- SHORT 100,00 için doğru limit: **100,05**; hatalı ikinci uygulama: **100,100025**.

v9'da dolum fiyatı ikinci kez değiştirilmez.

### 3. `ws_bot.py --help` çökmesi düzeltildi

Yardım metinlerindeki bazı literal yüzde işaretleri argparse biçimlendirmesine
uygun şekilde kaçırılmadığı için `python3 ws_bot.py --help` `ValueError` ile
kapanıyordu. İlgili metinler düzeltildi ve CLI için ayrı regresyon testi eklendi.

## Testler

Yeni `tests/test_maker_giris.py` dosyası şunları doğrular:

1. LONG limit dolumunda fiyatın yalnızca bir kez ayarlandığını.
2. SHORT limit dolumunda fiyatın yalnızca bir kez ayarlandığını.
3. Limit girişte maker, çıkışta taker ücreti hesaplandığını.
4. Market girişin taker davranışının değişmediğini.
5. `python3 ws_bot.py --help` komutunun hatasız çalıştığını.

Sonuç:

```text
173 passed in 6.40s
```

Komut:

```bash
python3 -m pytest -q
```

## v7 canlı kaydı üzerinden komisyon etkisi

`live_trades.csv` içindeki 36 işlem:

| Kalem | Sonuç |
|---|---:|
| Brüt PnL | +3,1444 USDT |
| Giriş ücreti | 4,5000 USDT |
| Çıkış ücreti | 4,5253 USDT |
| Toplam ücret | 9,0253 USDT |
| Gerçekleşen net PnL | **−5,8809 USDT** |

Yalnızca girişlerin maker (%0,02), çıkışların taker (%0,05) olduğu varsayımıyla:

| Senaryo | Net PnL |
|---|---:|
| Mevcut taker giriş + taker çıkış | −5,8809 USDT |
| Maker giriş + taker çıkış | **−3,1809 USDT** |
| Tahmini ücret tasarrufu | +2,7000 USDT |

Bu, toplam ücrette yaklaşık **%29,9 azalma** demektir. Giriş maker, çıkış taker
olduğu için “komisyon beş kat azalır” beklentisi doğru değildir; azalma giriş
tarafındadır.

**Önemli:** Bu hesap geçmiş kayıtların yalnızca ücretlerini değiştirir. Gerçek
maker sonucu; dolum oranı, kaçan sinyaller, sıra/kuyruk, kayma ve çıkış fiyatları
değişeceği için bu tablodan farklı olur. v9, maker stratejisinin daha kârlı
olduğunu kanıtlamaz.

## Sonraki doğrulama planı

1. Aynı sinyal kaydı üzerinde market ve maker senaryolarını eşleştirerek
   karşılaştır: dolum oranı, kaçan işlem PnL'i, toplam net PnL.
2. Test süresi 240 dakikalık tutma süresini kapsayacak şekilde uzatılmalı;
   `session_end` ile kapanan işlemlerin gerçek sonucu ayrıca raporlanmalı.
3. Kayma ve funding ayrı maliyet kalemleri olarak modele eklenmeli.
4. Yeterli örneklem olmadan rvol, TP veya diğer eşiklerde yeni optimizasyon
   yapılmamalı; kısa canlı/paper koşular strateji kanıtı sayılmamalı.

## Çalıştırmadan önce

Paketteki `live_trades.csv`, v7/v8 analizinde kullanılan geçmiş 36 işlemi içerir.
Yeni paper koşusunun sonuçlarını eski kayıtlarla karıştırmamak için koşudan önce
bu dosyayı arşivleyin veya yalnızca başlık satırı kalacak şekilde sıfırlayın.

Paper simülasyon içindir. Gerçek emir gönderilmez. Yatırım tavsiyesi değildir.
