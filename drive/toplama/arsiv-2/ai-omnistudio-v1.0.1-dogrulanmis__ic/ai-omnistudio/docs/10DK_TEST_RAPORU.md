# 10 Dakikalık Canlı Piyasa Verisi Testi — DOĞRULANMIŞ SÜRÜM

**Koşu:** `dogal-10dk-final` · **Tarih:** 3 Kasım 2026, 20:15–20:28 UTC
**Mod:** PAPER — gerçek piyasa verisi, **borsaya emir gönderilmedi**
**Profil:** `natural` — üretim eşikleri, **filtre gevşetmesi YOK**
**Test paketi:** 111/111 geçti · `check` TEMİZ

## Sonuç

| Ölçüt | Değer |
|---|---|
| Koşu durumu | **COMPLETED** |
| Aktif pencere | **600.5 sn / 600 sn** — tamamlandı |
| Evren | **300 sembol** (Binance Vision 150 + Gate.io 150) |
| İşlenen tick | **105,089** |
| WebSocket mesajı | **105,098** |
| REST başarılı / hatalı | **8,474 / 0** |
| Sinyal / kabul | 0 / 0 |
| Açılan / kapanan işlem | 0 / 0 |
| Net gerçekleşen | +0.000000 USDT |
| Equity | 10,000.00 USDT |
| Gerçek borsa emri | **0** |
| Veri boşluğu | **0** |
| Sağlık alarmı | **0** |
| Görev ölümü | **0** |
| Konsey | `RULE_BASED_QUANT` — 20 üye, 0 anahtar |
| `real_money_approved` | **false** |

## Düzeltmelerin canlı etkisi (önce → sonra)

İki koşu da 300 sembol, 600 sn aktif pencere, aynı `natural` profil.

| Ölçüt | İlk koşu | Düzeltilmiş koşu |
|---|---:|---:|
| REST hatası | **7,954** | **0** |
| REST hata oranı | **%20.2** | **%0.0** |
| Sağlık alarmı | **77** | **0** |
| İşlenen tick | 104,457 | 105,089 |
| Veri boşluğu | 0 | 0 |
| Görev ölümü | 0 | 0 |

**REST hatası 7,954 → 0. Sağlık alarmı 77 → 0.**
İstek sayısı da düştü (39,362 → 8,474); çünkü artık evrenin tamamı her
çevrimde değil, kotalı ve döngüsel taranıyor. Açık pozisyonlar istisna:
her çevrimde tazelenir.

## Düzeltilen 3 kusur

1. **Yanlış-pozitif heartbeat alarmı.** Eşik 45 sn sabitti, mum yenileme de
   45 sn; ağ süresi eklenince aşılıyordu. Eşik aralıktan türetiliyor
   (`2×aralık+30` → 120 sn), epizod başına tek alarm.
2. **HTTP 429 hız sınırı.** 300 sembol / 4 sn ≈ 75 istek/sn borsa bütçesini
   aşıyordu. Borsa başına token-bucket + 429'da yarıya indirme + `Retry-After`
   saygısı + kademeli toparlanma + çevrim başına sembol kotası.
3. **Açık pozisyon önceliğinde olmayan alan.** Quote önceliği `Position.venue`
   kullanıyordu; gerçek alan `exchange`. Bu, **ilk açık pozisyonda quote
   görevini öldürürdü**. Koşudan önce yakalandı, regresyon testiyle korundu.

## Neden 0 işlem?

Doğal profil seçici. 105,089 tick üretim eşiklerinden geçti, hiçbiri işlem
gerekçesini karşılamadı. Ret dağılımı:

| Kapı | Ret |
|---|---:|
| `ret_threshold` | 98,126 |
| `rvol_threshold` | 5,105 |
| `volume_threshold` | 1,627 |
| `breadth` | 173 |
| `stale_volume` | 21 |
| `context_vratio3` | 20 |

**Bu arıza değil, doğru davranış.** Eşikler gevşetilseydi işlem açılırdı;
kârlılık görüntüsü üretmemek için yapılmadı. Aç/kapat yolunun çalıştığı ayrı
etiketli `lifecycle-diagnostic` profilinde kanıtlı: BMTUSDT LONG açıldı,
68,8 sn sonra STOP_LOSS ile kapandı, net −0,335406 USDT. O profil
`LIFECYCLE_DIAGNOSTIC_NOT_NATURAL` işaretlidir; strateji kanıtı sayılmaz.

## Veri kaynakları

`wss://data-stream.binance.vision/stream` ve `wss://fx-ws.gateio.ws/v4/ws/usdt`
— **gerçek canlı piyasa verisi**. Bu ortamda `fapi.binance.com` HTTP 451 verdiği
için Binance'in resmî Vision aynası kullanıldı.

## Dürüstlük sınırları

- Kârlılık iddiası **yok**; `real_money_approved=false`.
- LIVE mod kilitli; hiçbir gerçek emir gönderilmedi.
- Gerçek YZ API çağrısı yapılmadı (anahtar yok); konsey `RULE_BASED_QUANT`.
- 10 dakikalık örneklem strateji kalitesi hakkında istatistiksel söz söylemez.
- Arşivin v9.4.1 hükmü geçerli: strateji komisyon öncesi net negatif
  (23 bps gidiş-dönüş maliyeti).
- **Telemetri notu:** `rate_limit` alanı bu koşunun SONUC.json'unda boştur;
  alan koşu başladıktan sonra koda eklendi. Limiter etkisi REST hata
  sayısıyla ({af:,} → {bf}) kanıtlanmıştır. Sonraki koşuda alan dolu olacak.
