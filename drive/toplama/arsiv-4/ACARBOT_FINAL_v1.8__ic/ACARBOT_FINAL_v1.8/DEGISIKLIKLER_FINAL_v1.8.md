# ACARBOT FINAL v1.8 — İşlem başı 25 USDT hedef net risk

Tarih: 7 Kasım 2026
Kullanıcı kararı: **"evet hepsini 25 yap"**

## 1. Sorun (v1.7 ve öncesi)

`max_loss_per_position=25` bir **üst sınırdı**, sabit zarar değil.
Pozisyon boyutu:

```text
notional = min(500, (25 - funding_tamponu) / (stop_mesafesi + maliyetler))
```

Dar stoplarda (ör. FTT %0,77) **500 USDT nominal tavanı** bağlayıcı oluyor,
planlanan net risk ~3,8 USDT'de kalıyordu. Kullanıcının beklentisi ise
her işlemde ~25 USDT riskti.

## 2. v1.8 çözümü

Varsayılan boyutlandırma artık **hedef net risk** odaklı:

```text
hedef_net_risk = 25 USDT
notional       = 25 / (stop_mesafesi + maker + taker + kayma + ek_kayma + funding_oranı)
margin         = notional / kaldıraç          # dinamik teminat
quantity       = notional / giriş_fiyatı
```

- `max_notional_per_position = 0` → nominal tavanı **KAPALI**.
- `margin_per_position = 0` → teminat **dinamik** (`notional / leverage`).
- Funding tamponu sabit 500 USDT üzerinden değil, gerçek notional üzerinden
  ölçeklenir.
- Limit emir miktarı, dolumda hedef notionalı koruyacak şekilde ince ayarlanır.
- Bekleyen giriş emirleri teminat rezerve eder; aynı anda birden fazla emir
  bakiyeyi aşamaz.
- Teminat yetmezse giriş **AÇILMAZ**; risk sessizce küçültülmez.
- Acil net-zarar stopu (`<= -25`), likidasyon modeli, drawdown koruması,
  haber/sweep kapıları ve v1.7 bayat sinyal iptali korunur.

## 3. Örnekler (10x kaldıraç, varsayılan maliyetler)

| Stop mesafesi | Notional | Dinamik teminat | Hedef net risk |
|---:|---:|---:|---:|
| %0,30 | ~5.435 USDT | ~543 USDT | 25 USDT |
| %0,77 (FTT benzeri) | ~2.688 USDT | ~269 USDT | 25 USDT |
| %2,50 | ~940 USDT | ~94 USDT | 25 USDT |

Not: 1.000 USDT bakiyede dar stoplu işlemler daha fazla teminat bağlar;
bu nedenle aynı anda açılabilecek pozisyon sayısı doğal olarak azalabilir.
APEX'te pozisyon adedi sınırsızdır, ancak teminat/drawdown sınırı her zaman
aktiftir.

## 4. APEX profili

`--profile apex` artık açıkça şunu uygular:

- `max_loss_per_position = 25`
- `max_notional_per_position = 0`
- `margin_per_position = 0`
- pozisyon adedi sınırsız, günlük fren kapalı, portföy tavanları kapalı
- teminat yeterliliği + drawdown koruması + likidasyon + haber/sweep aktif

## 5. Testler

- Yeni: `tests/test_target_risk_25.py`
  - dar/geniş stoplarda LONG+SHORT 25 USDT hedef
  - 500 nominal tavanının artık bağlamadığı
  - dinamik teminat, funding ölçeklemesi, legacy tavan
  - bekleyen emir teminat rezervi, yetersiz bakiyede giriş engeli
  - OPEN olayında notional/margin/net_risk raporlanması
- Güncellenen eski testler: 500 tavanı ve ~2-3 USDT risk beklentileri
  v1.8 hedef risk davranışına göre düzeltildi.
- Sonuç: **281/281 test geçti**.

## 6. Önemli uyarı

25 USDT bir **garanti** değildir. Stop'a normal koşullarda gidilirse
beklenen net zarar 25 USDT'dir. Gap, aşırı kayma, funding veya likidasyon
durumlarında gerçek zarar farklı olabilir. Bot yalnızca **paper** modda
çalışır; gerçek borsaya emir göndermez.
