# NOVA-BOT — 15 dakikalık PAPER test sonuçları

Koşu: 2026-11-05T21:51:55Z → 2026-11-05T22:06:55Z · ölçülen süre **900.4 sn** (hedef 900) · durum `COMPLETED`  
Gerçek emir: **0** · PAPER: **True** · dış YZ servisi: YOK — bu bot hiçbir dil modeli veya dış servis çağırmaz  
Sembol: **45** (3 borsa)

## 1. Özet

| Ölçüm | Değer |
|---|--:|
| Kapanmış 1m mum (hepsi WS'ten) | 675 |
| WS mum güncellemesi | 39619 |
| Kapanıştan ≤5 sn içinde alınan | 675 |
| Sinyal | 404 |
| Sinyalsiz mum (skor eşiği altı) | 271 |
| Açılan PAPER pozisyon | 6 |
| Kapanan | 6 |
| Funding oranı alınan | 1099 |
| Medyan kapanış→kayıt gecikmesi | 949 ms |
| En uzun gecikme | 3866 ms |
| WS bağlantısı | 3 |
| Havuz (binance/okx/gate) | 211 / 133 / 54 |

## 2. PAPER defteri

- Sermaye: **1000 → 997.992735** (gerçekleşen -2.007265 USDT)
- İşlem: **6** · açık: 0 · kazanma %16.67 · PF 0.009 · ort. R -1.094
- Ücretler: 1.483310 USDT · funding: 0.000000 USDT · maks. düşüş: 2.024823 USDT
- Devre kesici: `CONSEC_LOSSES`

## 3. İşlem listesi

| # | Borsa | Sembol | Yön | Giriş | Çıkış | Net (USDT) | R | Çıkış |
|--:|---|---|---|---|--:|--:|--:|---|
| 1 | gateio_usdt | DOGE_USDT | short | 0.07202 | 0.0719644 | -0.0568 | -0.19 | STOP |
| 2 | gateio_usdt | ETH_USDT | short | 2228.83 | 2232.81 | -0.6828 | -1.83 | STOP |
| 3 | gateio_usdt | BTC_USDT | short | 75802.9 | 75912.6 | -0.5937 | -2.49 | STOP |
| 4 | okx_swap | DOGE-USDT-SWAP | short | 0.07199 | 0.0720944 | -0.6123 | -1.87 | STOP |
| 5 | gateio_usdt | UNI_USDT | short | 6.835 | 6.83037 | -0.0791 | -0.20 | STOP |
| 6 | okx_swap | HYPE-USDT-SWAP | short | 77.979 | 77.8956 | +0.0176 | +0.02 | STOP |

6 pozisyonun 5'i short, 1'i long; hiçbiri 2,4×ATR hedefine ulaşmadı. HYPE pozisyonu 0,8R'de maliyete çekilen stop sayesinde +0,02 USDT ile kapandı — bu kâr değil, maliyet korumasıdır. BTC ve DOGE aynı anda iki borsada açıldı (piyasa başına 2 pozisyon sınırı korelasyonu bilinçli olarak sınırlar).

## 4. Neden bu kadar az işlem? Ret dağılımı

| Kapı | Adet |
|---|--:|
| `BOOK` | 189 |
| `NO_QUOTE` | 135 |
| `FUNDING_UNKNOWN` | 47 |
| `SPREAD` | 28 |

Defter tarafı: `HALTED_CONSEC_LOSSES`×125, `MAX_PER_MARKET`×32, `MAX_SAME_SIDE`×23, `ALREADY_OPEN`×9.

Okuma: 404 sinyalden 189'u defter kurallarında (pozisyon/limit/devre kesici), 135'i fiyat kotasyonu alınamadığı için, 47'si funding oranı bilinmediği için, 28'i makas çok geniş olduğu için reddedildi. 4 ardışık zarardan sonra devre kesici devreye girdi ve kalan dakikalarda yeni pozisyon açılmadı — tasarım gereği.

## 5. Bağlam: geriye dönük test (aynı kod, aynı maliyet modeli)

60 sembol × 999 mum (~16.65 saat): **2212 işlem · net -506.9666 USDT · kazanma %29.97 · PF 0.653 · ort. R -0.063 · maks. düşüş 507.5341**

Çıkış dağılımı: `STOP`×1484, `TAKE_PROFIT`×647, `MAX_HOLD`×54, `EQUITY_HALT`×27.

Geriye dönük test de negatif. Yani strateji bu parametrelerle, bu maliyet modelinde **kenar üretmiyor**; 15 dakikalık koşunun negatif sonucu bununla tutarlı. Botun işleyişi doğru, kenarı yok — bunu saklamıyorum.

## 6. Borsa sağlığı

| Borsa | İstek OK | Hata |
|---|---|--:|
| binance_usdm | 821 | 0 |
| okx_swap | 554 | 0 |
| gateio_usdt | 702 | 0 |

## 7. Testler

`python3 -m pytest -q` → **35 test / 35 geçti**, tamamen çevrimdışı (ağ gerekmez). Kapsam: göstergeler (EMA/RSI/ATR/ADX/choppiness), strateji oyları ve eşik monotonluğu, PAPER defteri (lot adımı, min notional, stop/hedef, funding işareti, tasfiye kapısı, devre kesici, pozisyon limitleri), üç borsanın veri çözümleyicileri, WS kapanış bayrağı, sayfalı mum çekme, evren filtreleri (hacim / ürün yaşı / çapraz borsa) ve kaynak kodda özel API izi olmadığını doğrulayan güvenlik testi.

## 8. Bu test neyi KANITLAMAZ

- Kârlılık kanıtı değildir: 6 işlem istatistiksel olarak anlamsızdır.
- Tek bir 15 dakikalık pencere tek bir piyasa rejimini gösterir; başka saatte işaret değişebilir.
- Gerçek emir, kısmi dolum, emir defteri derinliği ve borsanın gerçek tasfiye motoru modellenmedi.
- Makas ölçümü ticker'ın en iyi alış-satışına dayanır; ani likidite boşluklarında gerçek dolum daha kötü olur.
- Funding gerçek oranlarla işlendi ama bu koşuda hiçbir pozisyon funding anını görmedi (0,0 USDT).
- Sonuçlar KISMİdir.

Sınırların tamamı ekteki RAPOR dosyalarında ve README.md içinde yazılıdır.

## 9. Ekler

- `RAPOR-canli-15dk.md   canlı koşunun tam raporu`
- `SONUC.json            tüm ölçümler, ret sayaçları, işlem kayıtları`
- `events.jsonl          satır satır olay kaydı (sinyal/ret/açılış/kapanış)`
- `RAPOR-backtest.md     geriye dönük test raporu`
- `BACKTEST.json         geriye dönük test ölçümleri`
- `pytest-35-test.log    test çıktısı`
- `doctor.log            3 borsa tanı çıktısı`
