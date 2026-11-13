# 10 Dakikalık Canlı Piyasa Verisi Testi

**Koşu:** `dogal-10dk-20261103` · **Tarih:** 3 Kasım 2026, 19:19–19:32 UTC
**Mod:** PAPER — gerçek piyasa verisi okundu, **borsaya emir gönderilmedi**
**Profil:** `natural` — üretim eşikleri, **filtre gevşetmesi YOK**

## Sonuç

| Ölçüt | Değer |
|---|---|
| Koşu durumu | **COMPLETED** |
| Aktif pencere | **600.5 sn** (hedef 600 sn) |
| Aktif pencere tamamlandı | **True** |
| Evren | **300 sembol** (Binance Vision 150 + Gate.io 150) |
| İşlenen tick | **104,457** |
| Sinyal | 0 |
| Kabul edilen | 0 |
| Açılan / kapanan işlem | 0 / 0 |
| Net gerçekleşen | +0.000000 USDT |
| Equity | 10,000.00 USDT |
| Gerçek emir gönderildi | **0** |
| Veri sürekliliği boşluğu | **0** |
| Görev ölümü | **0** |
| Konsey | `RULE_BASED_QUANT` — 20 üye, 0 anahtarlı |

## Veri kaynakları (gerçek canlı veri)

| Borsa | WS mesajı | REST başarılı | REST hatalı |
|---|---:|---:|---:|
| binance_vision | 38,974 | 17,112 | 1,180 |
| gateio | 65,492 | 14,296 | 6,774 |

Uçlar: `wss://data-stream.binance.vision/stream`, `wss://fx-ws.gateio.ws/v4/ws/usdt`.
Bunlar **gerçek canlı piyasa verisidir**. Sandbox'ta `fapi.binance.com` HTTP 451
verdiği için resmî Binance Vision aynası kullanıldı.

## Neden 0 işlem?

Doğal profil gerçekten seçici. 10 dakikada 104,457 tick'in tamamı üretim
eşiklerinden geçti, hiçbiri işlem gerekçesini karşılamadı. Ret dağılımı:

| Kapı | Ret |
|---|---:|
| `ret_threshold` | 96,222 |
| `rvol_threshold` | 5,654 |
| `volume_threshold` | 2,074 |
| `context_vratio3` | 180 |
| `context_warmup` | 129 |
| `breadth` | 91 |

**Bu hata değil, doğru davranıştır.** Eşikler gevşetilseydi işlem açılırdı;
kârlılık görüntüsü üretmek için bunu yapmadım. Aç/kapat yolunun çalıştığı
ayrı etiketli `lifecycle-diagnostic` profilinde kanıtlanmıştı: BMTUSDT LONG
açıldı, 68,8 sn sonra STOP_LOSS ile kapandı, net −0,335406 USDT.

## Bu koşuda bulunan ve düzeltilen 2 kusur

### 1. Yanlış-pozitif sağlık alarmı (77 adet)
`data_progress` heartbeat eşiği 45 sn sabitti; mum yenileme aralığı da 45 sn
olduğu için üstüne ağ süresi eklenince eşik aşılıyordu. Veri akıyordu, görev
ölümü yoktu — alarm yanlıştı.
**Düzeltme:** eşik aralıktan türetiliyor (`2×aralık+30` → 120 sn); aynı bayatlık
epizodu için tek alarm yazılıyor.

### 2. REST hız sınırı (HTTP 429)
300 sembolü 4 sn'de bir tazelemek ~75 istek/sn üretiyordu; Binance
6000 ağırlık/dk ve Gate.io bütçesi aşılıyordu (Gate.io'da ~%32 hata).
**Düzeltme:** borsa başına token-bucket (`rest_rps`), 429'da hızı yarıya indirme
+ `Retry-After` saygısı + kademeli toparlanma; quote çevrimi başına sembol kotası
ve döngüsel tarama. **Açık pozisyonlar her çevrimde istisnasız tazelenir.**

> Düzeltmeler kodda ve testlerde doğrulandı (**152/152 test**, `check` TEMİZ).
> Düzeltilmiş sürümle ikinci 10 dk koşusu başlatıldı, ancak sandbox süreci
> 62. saniyede kesti. Bu yüzden **tam 10 dk kanıtı yukarıdaki ilk koşuya aittir**;
> düzeltmelerin canlı 10 dk doğrulaması henüz yapılmadı — açık iş.

## Dürüstlük sınırları

- Kârlılık iddiası **yoktur**; `real_money_approved=false`.
- LIVE mod kilitli; bu koşuda hiçbir gerçek emir gönderilmedi.
- Gerçek YZ API çağrısı yapılmadı (anahtar yok); konsey `RULE_BASED_QUANT`.
- 10 dakikalık örneklem strateji kalitesi hakkında istatistiksel söz söylemez.
- Arşivin v9.4.1 hükmü geçerli: strateji komisyon öncesi net negatif.
