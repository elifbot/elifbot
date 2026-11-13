# Bot Arşivi Denetimi — v8 → v9.4.5

**Kaynak:** `omeracar56@gmail.com` Gmail hesabı, 4 toplu teslim e-postası (3 Kasım 2026).
**Kapsam:** 17 özgün sürüm ZIP'i + güncel v9.4.5 kaynağı + rapor/kanıt arşivleri.
**Doğrulama:** 17/17 ZIP SHA-256 değeri, e-postadaki manifest ile **birebir eşleşti**.

---

## 1. Teslim alınan paketler

| E-posta | Ek | Boyut | SHA-256 doğrulama |
|---|---|---:|---|
| [1/4] | `2026-11-03_01_GUNCEL_KOD_...zip` | 13.267.705 B | `3fb8b156…` ✓ |
| [2/4] | `2026-11-03_02_ORIJINAL_SURUMLER...zip` | 14.393.092 B | `8c18b0bc…` ✓ |
| [3/4] | `2026-11-03_03_ORIJINAL_SURUMLER...zip` | 12.708.770 B | `d0f9aa24…` ✓ |
| [4/4] | `2026-11-03_04_ORIJINAL_SURUMLER...zip` | 14.106.601 B | `f1a5ac9e…` ✓ |

> Not: [2/4] e-postasının ilk gönderimi Gmail tarafından "yürütülebilir dosya/arşiv
> politikası" gerekçesiyle engellenmişti (Mail Delivery Subsystem kaydı mevcut).
> Yeniden gönderim başarıyla alınmıştır.

## 2. Sürüm hattı ve gerçek içerik

| Sürüm | .py dosya | Öne çıkan iş | Durum |
|---|---:|---|---|
| v8 "mükemmel" | 248 | İlk geniş hat; komisyon kârı yiyor sorunu | Tarihsel |
| v8.2 | 248 | "10 kodlama YZ konseyi" etiketi, 742 test | Tarihsel |
| v8.3 | 251 | 10-YZ adaptif yardımcı, %60 komisyon optimizasyonu | Tarihsel |
| v8.4 | 252 | 3 kritik bulgu + doğal kapanış (drain) mimarisi | Tarihsel |
| v9.0 | 33 / 260 | Sıfırdan temiz ürün; Binance+OKX çift borsa | **Mimari dönüm** |
| v9.1 | 33 | LiveLLMReferee; kör fail-open kaldırıldı | Davranışsal dönüm |
| v9.2 / v9.2.1 | 59 | Maker kuyruk kilidi düzeltmesi (SQLite) | Aynı SHA — içerik özdeş |
| v9.3.0 | 63 | Bağımsız paket, dondurulmuş holdout | Araştırma |
| v9.4.1 | 79 | 10 kollu doğrulama, kabul ölçütleri **başarısız** | **Kritik hüküm** |
| v9.4.3 (3 varyant) | 87–89 | Sağlık yaması, raporlama düzeltmesi | Ara |
| v9.4.4 | 97 | Doğruluk/telemetri; tekrar sayaçları ayrıldı | Sağlamlaşma |
| **v9.4.5** | **101** | 6 ana görev denetimi, monotonic süreklilik | **Uygulanmış güncel** |

### Doğrulanan iddia
v9.4.5 "158 test geçti" iddiası bu ortamda **yeniden koşuldu**:

```
158 passed in 8.50s
```

İddia doğrudur. `RELEASE_STATUS.json` ayrıca şunu açıkça beyan eder:
`real_money_approved: false`, `operational_readiness_approved: false`.

## 3. Arşivden çıkan en önemli 6 bulgu

### 3.1 Strateji komisyon öncesi bile net negatif (v9.4.1)
Araştırma paketinin kendi raporu: *"Bu kolda bile net negatif: sorun yalnızca
komisyon değildir. Yeni adayın daha az kaybetmesi kârlılık kanıtı değildir."*
Maliyet tabanı: 7 bps gidiş-dönüş + 16 bps kayma = **23 bps**, spread/funding hariç.

**Bu hüküm yeni inşaatta DEĞİŞMEDİ.** OmniStudio bunu miras alır ve kâr iddiası üretmez.

### 3.2 "10 YZ konseyi" aslında YZ değildi
`ten_agent_debate.py` kaynak kodunun kendi ifadesi:

> *"Dürüst Adlandırma: Sahte dış model pazarlama etiketleri KULLANILMAZ.
> 10 ajan, aynı tam görevi farklı risk/ufuk hassasiyetleriyle yürüten otonom
> kantitatif denetçilerdir."*

Yani v8.2–v9.x'teki "konsey" deterministik kurallardı; tek gerçek LLM çağrısı
`LiveLLMReferee` içindeydi (varsayılan: OpenRouter/DeepSeek).

**OmniStudio farkı:** 20 **gerçek** sağlayıcı adapter'ı (OpenAI, Anthropic, Google,
xAI, DeepSeek, Mistral, Groq, Together, Fireworks, Perplexity, Cohere, OpenRouter,
Cerebras, SambaNova, Hyperbolic, DeepInfra, Novita, Qwen, Moonshot, Zhipu).
Anahtar yoksa çıktı `RULE_BASED_QUANT` diye **açıkça etiketlenir**; YZ cevabı diye sunulmaz.

### 3.3 Gerçek darboğaz ölçülmüş: O(n·m) fiyat/genişlik taraması
Prob verisi (230.349 `on_trade` çağrısı):

| Alt yol | Kapsayıcı süre |
|---|---:|
| `det.price` | 140,841 s |
| `det.ratios` | 83,306 s |
| `det.breadth` | 56,587 s |
| WS JSON parse (2,55 M çağrı) | 20,218 s |

En uzun tek `on_trade`: **150,602 ms**, içindeki breadth **150,004 ms**.

### 3.4 5,22 saniyelik süreklilik boşluğunun kök nedeni hâlâ açık
Arşiv net konuşur: 32 HTTP 503 yanıtı `RUN_DISCONTINUITY_DETECTED` alarmını
taşıyor — bu **alarm bileşeninin kanıtı**, gecikmenin CPU/VM/disk kök nedeninin
kanıtı **değildir**. Tekrarlamaması da düzelme kanıtı sayılmamıştır.

### 3.5 Deneysel hızlandırma adayı bota uygulanmamış
`indexed_price_candidate.py` 24 izole test geçmiş, sentetik kıyasta 30,45× /
158,46× ölçülmüş; ancak **doğal PAPER koşusuna hiç bağlanmamış**. Arşiv açıkça
uyarır: bu oranlar tüm bot hızlanması anlamına gelmez.

### 3.6 İşlem kilitleri teşhisi — gevşetme yok
- İlk spread/fiyat sapması reddi, o sembol-mumun deneme hakkını tüketir.
- Sonraki mumda yeniden açılır → **kalıcı kilit değil**.
- 421 STALE kaydı 421 fırsat değil, **16 sembol-mum anahtarının tekrarıydı**.
- `unique_signal_count` hâlâ null; RSI/trend/akış eşiği gevşetilmemiş.

## 4. Sürümler arası gerçek farklar

**v8 → v9.0:** 248 → 33 dosya. Bu bir kayıp değil, **sıfırdan sadeleştirme**.
Eski sürüm kalıntıları, çiftli konfigürasyonlar ve gereksiz raporlar atılmış.

**v9.1:** En değerli davranışsal düzeltme. Kör `approved=True` fail-open kaldırılıp
yerine katı kantitatif gürültü denetimi konmuş. OmniStudio bu ilkeyi korur:
**YZ hatası onay üretmez.**

**v9.2 → v9.2.1:** SHA-256 değerleri **aynı** (`8cee4d4b…`). Yani içerik özdeş;
yalnız sürüm etiketi değişmiş. Bu, arşivde dürüstçe görülebilen bir detay.

**v9.4.4 → v9.4.5:** Finansal modüller byte-byte korunmuş; yalnız görev denetimi,
monotonic süre ve telemetri eklenmiş. Config farkı sadece sürüm etiketi.

## 5. Yeni inşaatta ne alındı, ne alınmadı

### Bilinçli olarak devralınan davranışlar
| İlke | Kaynak | OmniStudio'daki yeri |
|---|---|---|
| Kör fail-open yasak | v9.1 | `ai/council.py` — quorum yetersizse ret |
| Genişlik kapısı bağlamdan bağımsız | v20 düzeltmesi | `strategy/detector.py::update_breadth` |
| Mum başına tek deneme | v9.x router | `strategy/policy.py` |
| Dedektör piyasa yönünü döndürür | v9.x sözleşme | `core/types.py::Signal` |
| Tekrar sayacı ≠ ekonomik ret | v9.4.4 | `PolicyState.evaluation_repeats` ayrı |
| Görev ölümünde giriş kes, pozisyon zorla kapatma | v9.4.5 | `runtime/supervisor.py` |
| Monotonic süre + boşlukta DISCONTINUOUS | v9.4.5 | `core/clock.py:: ContinuityEngine` |
| Writer lease hatası yutulmaz | v9.4.5 | `state/store.py::WriterLeaseError` |
| Eski DB devralınmaz | devam notu | `StateStore(fresh=True)` |
| Ölçüm önceden beyan edilir | v9.4.1 | `Engine::_criteria` koşudan önce yazılır |

### Bilinçli olarak alınmayanlar
- **Sahte model etiketleri** — hiçbir yerde "dünyanın en iyi X modeli" pazarlama iddiası yok.
- **`patch_v944.py` / `patch_v945.py`** — arşiv "tekrar körlemesine çalıştırmayın" diyor; çalıştırılmadı.
- **Eski snapshot DB'ler** — yalnız kanıt olarak arşivde; yeni koşuya taşınmadı.
- **Eski launcher mutlak yolları** — taşınmadı; yeni CLI göreli yol kullanır.

## 6. Arşivde açık kalan işler ve yeni durum

| Açık iş (arşiv) | OmniStudio'da durum |
|---|---|
| Fiyat araması O(n) darboğazı | **Çözüldü** — `PriceHistory` O(log n), eşdeğerlik testli |
| Hacim oranı döngüsü ("sonraki hedef") | **Çözüldü** — kayan pencere toplamı, 24.000 kontrol |
| Genişlik hesabı tekrar maliyeti | **Çözüldü** — indeksli arama + 250 ms önbellek |
| 5,22 s boşluk kök nedeni | **Kısmen** — anında tespit + alarm var; kök neden hâlâ açık |
| SQLite risk yazımı/stop gecikmesi | Ölçüm eklendi; gerçek yük testi yapılmadı |
| Thread-token görünürlük yarışı | Tasarımdan çıkarıldı (tek event-loop, senkron tick hattı) |
| Büyük gerçek defter API yükü | **Yapılmadı** |
| Tam transitif bağımlılık kilidi | **Yapılmadı** — yalnız doğrudan bağımlılık sabitlendi |
| Bridge/Compose dağıtımı | **Yapılmadı** |
| Tekil olgun sinyal/karar kimliği | **Çözüldü** — `signal_id` + `decision_id` + `closed_bar_key` |

## 7. Ölçülen sonuç (bu ortam, gerçek veri)

| Ölçüm | v9.4.5 (arşiv) | OmniStudio (bu ortam) |
|---|---:|---:|
| En uzun tick işleme | 150,602 ms | **~1,4 ms** |
| Genişlik güncelleme | 150,004 ms | **~0,46 ms** |
| WS JSON parse | 20,218 s / 2,55 M çağrı | 0,155 s / 8.482 çağrı |
| Süreklilik boşluğu | 1 (5,22 s) | **0** |

> **Yorum sınırı:** Bunlar farklı ortam, farklı sembol sayısı ve farklı sürelerde
> alınmış ölçümlerdir. Eşleştirilmiş kontrollü kıyas **değildir**; "X kat hızlandı"
> iddiası kurulmaz. Yalnız aynı işin artık milisaniye altı sürdüğü söylenebilir.

## 8. Kanıt konumu

```
_archive/
├── originals/                        # 17 özgün sürüm ZIP'i (SHA doğrulanmış)
├── current-v9.4.5/                   # güncel kaynak + 158 test
├── current-v9.4.5-reports.tar.gz     # özgün raporlar (sıkıştırılmış)
├── probe-raporu/                     # alt-yol prob kanıtları
├── indexed_price_candidate.py        # bota uygulanmamış deneysel aday
├── ONCE_OKUYUN_AKSAM_DEVAM_NOTU.md   # özgün devam notu
└── ORIJINAL_SURUM_ARSIVLERI_INDEKSI.json
```

Arşivdeki hiçbir özgün dosya silinmedi veya değiştirilmedi; yalnız açılmış
kopyalar ve `__pycache__` budandı, raporlar kayıpsız sıkıştırıldı.