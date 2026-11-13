# NOVA-BOT — canlı PAPER test raporu

**Durum:** `COMPLETED` · **Mod:** `live` · **Sürüm:** 1.0.0  
**Ölçülen süre:** 900.4 sn (hedef 900.0 sn) · **Sembol:** 45  
**Gerçek emir:** 0 · **Dış model/YZ çağrısı:** yok

> PAPER: borsaya emir gönderilmedi, özel API anahtarı kullanılmadı. Bu rapor kârlılık kanıtı değildir.

## 1. Veri akışı

| Ölçüm | Değer |
|---|--:|
| Değerlendirilen kapanmış 1m mum | 675 |
| WS'ten gelen kapanmış mum | 675 |
| WS mum güncellemesi | 39619 |
| Kapanıştan 5 sn içinde alınan | 675 |
| Isınması tamamlanan sembol | 45 |
| Funding oranı alınan | 1099 |
| Kapanış→kayıt medyan gecikme | 949 ms |
| En uzun gecikme | 3866 ms |

## 2. PAPER defteri

- Sermaye: **1000** → **997.992735** (gerçekleşen: -2.007265)
- İşlem: **6** · açık: 0 · kazanma: %16.7 · PF: 0.009 · ort. R: -1.094
- Ücretler: 1.483310 · funding: 0.000000 · maks. düşüş: 2.024823
- Devre kesici: `CONSEC_LOSSES`

**Defter ret nedenleri:** `HALTED_CONSEC_LOSSES`×125, `MAX_PER_MARKET`×32, `MAX_SAME_SIDE`×23, `ALREADY_OPEN`×9

## 3. İşlemler

| # | Borsa | Sembol | Yön | Giriş | Çıkış | Net | R | Neden |
|--:|---|---|---|---|--:|--:|--:|---|
| 1 | gateio_usdt | DOGE_USDT | short | 0.072020 | 0.071964 | -0.0568 | -0.19 | STOP |
| 2 | gateio_usdt | ETH_USDT | short | 2228.830000 | 2232.806472 | -0.6828 | -1.83 | STOP |
| 3 | gateio_usdt | BTC_USDT | short | 75802.900000 | 75912.579480 | -0.5937 | -2.49 | STOP |
| 4 | okx_swap | DOGE-USDT-SWAP | short | 0.071990 | 0.072094 | -0.6123 | -1.87 | STOP |
| 5 | gateio_usdt | UNI_USDT | short | 6.835000 | 6.830366 | -0.0791 | -0.20 | STOP |
| 6 | okx_swap | HYPE-USDT-SWAP | short | 77.979000 | 77.895576 | 0.0176 | 0.02 | STOP |

## 4. Sinyal ve ret dağılımı

| Sayaç | Adet |
|---|--:|
| signals | 404 |
| no_signal | 271 |
| reject_BOOK | 189 |
| reject_NO_QUOTE | 135 |
| reject_FUNDING_UNKNOWN | 47 |
| reject_SPREAD | 28 |
| opened | 6 |

## 5. Borsa sağlığı

| Borsa | İstek OK | Hata | Durum | Son hata |
|---|---|--:|---|---|
| binance_usdm | 821 | 0 | ✅ |  |
| okx_swap | 554 | 0 | ✅ |  |
| gateio_usdt | 702 | 0 | ✅ |  |

## 6. Ayarlar

| Ayar | Değer |
|---|--:|
| equity | 1000 |
| risk_pct | 0.5 |
| max_positions | 4 |
| stop_atr | 1.2 |
| tp_atr | 2.4 |
| max_hold_sec | 1800 |
| taker_bps | 5.0 |
| slip_bps | 2.0 |
| max_spread_bps | 6.0 |
| min_liq_dist_pct | 10.0 |
| daily_loss_pct | 2.0 |
| min_score | 3 |
| max_chop | 62.0 |

## 7. Dürüstlük sınırları

- Gerçek emir yolu yoktur; kamu verisi okunur, sanal deftere yazılır.
- Dolum modeli taker + makas + varsayımsal kayma; emir defteri derinliği yok.
- Likidasyon fiyatı `1/kaldıraç − bakım marjı` yaklaşımıdır; borsanın gerçek tasfiye motoru ve kademeli marjı modellenmedi.
- Funding yalnız oran bilinen sembollerde işlenir; funding anına 3 dakikadan az kaldıysa giriş reddedilir.
- 15 dakikalık pencere kârlılık kanıtı değildir; işlem sayısı çoğu zaman istatistiksel olarak anlamsızdır.
- Bu bot hiçbir dil modeli/YZ servisi çağırmaz; 'model onayı' iddiası yoktur.
