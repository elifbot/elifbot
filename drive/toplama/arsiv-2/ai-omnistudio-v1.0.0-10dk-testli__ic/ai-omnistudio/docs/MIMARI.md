# Mimari ve Tasarım Kararları

## 1. Katman sözleşmeleri

### 1.1 Zaman ayrımı (en kritik karar)

İki saat **asla** birbirinin yerine kullanılmaz:

| Saat | Kaynak | Kullanım |
|---|---|---|
| Duvar saati | `time.time()` | Veri zaman damgası, rapor etiketi, funding anı |
| Monotonic | `time.monotonic()` | Süre, timeout, boşluk ölçümü, süreklilik |

**Neden:** v9.4.5'te 5,22 s boşluk yaşandı. NTP/VM sıçraması duvar saatini
kaydırır; süre ölçümü duvar saatiyle yapılırsa gerçek boşluk görünmez veya
sahte boşluk oluşur. `ContinuityEngine` ikisini karşılaştırır ve sapmayı
başlı başına olay sayar (`CLOCK_SKEW_DETECTED`).

### 1.2 Sinyal yönü sözleşmesi

```
SpikeDetector  →  PİYASANIN gittiği yön (LONG = fiyat yükseldi)
EntryPolicy    →  fade ise TERSİNİ alır (LONG sinyali → SHORT giriş)
```

Bu ayrım arşivden bilinçli korunur. Dedektörde çevirme yapmak, strateji
değişimini sessizleştirir ve geri test eşleşmesini bozar.

### 1.3 Karar kaydı her durumda yazılır

Kabul edilen de reddedilen de `decisions.jsonl` + SQLite'a yazılır. Ret
nedeni makine okunur koddur (`OVER_EXTENDED`, `CONTRA_FLOW`, `EDGE_BELOW_COST`…).

**Neden:** Arşivde "421 STALE kaydı 421 fırsat değil, 16 sembol-mum
anahtarının tekrarıydı" hatası vardı. Her kararı tekil kimlikle kaydetmek
bu şişmeyi görünür kılar.

## 2. Performans: O(n·m) → O(log n) / O(1)

### 2.1 Fiyat araması

**Eski davranış:** Her tick'te tüm fiyat geçmişini baştan tara.

```python
for ts, f in d.fiyatlar:          # O(n) her çağrıda
    if ts >= threshold: return (ts, f)
```

**Yeni:** Ön-ek maksimum dizisi + ikili arama.

```python
i = bisect_left(self._prefix, threshold, lo=self._head)   # O(log n)
```

**Doğruluk garantisi:** Ön-ek maksimum monotoniktir, bu yüzden ikili arama
geçerlidir. Zaman damgaları sırasızsa indeks geçersiz aday üretebilir; aday
eşiği sağlamıyorsa **eski doğrusal aramaya düşer**. Çıktı birebir aynıdır.

### 2.2 Hacim oranı döngüsü

Arşivin "sonraki hedef" olarak işaretlediği iş. Eski kod her tick'te iki
pencere için tam tarama yapıyordu.

**Yeni:** Mutlak ekleme koordinatında kayan imleç.

```
seq  : toplam ekleme sayısı (tampon kaymasından etkilenmez)
base : seq - len(buf)  → tampondaki ilk öğenin mutlak indexi
[lo, hi) : pencere içindeki öğeler
```

Her adımda yalnız yeni gelenler eklenir, pencereden çıkanlar düşülür →
**amortize O(1)**.

**Ön koşullar ve düşüş yolları:**
1. Zaman damgaları azalmayan → değilse tam tarama.
2. Cutoff azalmayan → geriye giderse imleç yeniden hizalanır.
3. Tampon kaydığında `lo < base` olursa yeniden hizalama.

Bu üç durumun her biri test edilir; 24.000 rastgele kontrolde tam taramayla
**sıfır uyuşmazlık**.

### 2.3 Genişlik hesabı

İki iyileştirme: indeksli `first_at_or_after` + 250 ms önbellek. Önbellek
yalnız aynı tick içinde tekrarlanan çağrıları eler; karar mantığını değiştirmez.

## 3. YZ konseyi: iki mod, net sınır

```
                 ┌─ anahtar var mı? ─┐
                 │                   │
              EVET                  HAYIR
                 │                   │
            LIVE_LLM          RULE_BASED_QUANT
                 │                   │
        gerçek API çağrısı    20 deterministik
        4 protokol            kantitatif denetçi
                 │                   │
        quorum yeterli mi?    ai_generated=false
           │        │         (YZ cevabı DEĞİL)
        EVET      HAYIR
           │        │
      3 tur    INSUFFICIENT_QUORUM
      oylama        → RET
```

### 3.1 Sert ön kapılar YZ'yi bağlar

Maliyet tabanı ve makas limiti konseyden **önce** kontrol edilir. Hiçbir YZ
"maliyetin altında ama bence iyi" diyemez. Bu, v9.1'in kör fail-open
düzeltmesinin doğal uzantısıdır.

### 3.2 Üç tur gerçek çapraz teftiş

- **Tur 1:** Her üye aynı 6 boyutta bağımsız tam değerlendirme.
- **Tur 2:** Üyeler birbirinin itirazlarını görür, puanını revize eder.
  Görev bölüşümü **yok** — herkes tam göreve bakar.
- **Tur 3:** Tier ve güven ağırlıklı konsensüs + çoğunluk onayı.

### 3.3 Devre kesici

Ardışık 3 hata → sağlayıcı 120 s devre dışı. Böylece bozuk bir uç tüm
karar hattını yavaşlatmaz.

## 4. Görev denetimi

v9.4.5'in doğrulanmış sözleşmesi aynen korunur:

| Olay | Davranış |
|---|---|
| Görev istisna atarsa | Girişler kesilir, run FAILED |
| Görev beklenmedik normal dönerse | **Aynı** — bu da ölümdür |
| Görev iptal edilirse | Planlı kapanış değilse ölüm sayılır |
| Açık pozisyon varsa | **Zorla kapatılmaz** (FAILED durumunda) |
| Sinyal yoksa | Ölüm **değildir**; heartbeat ayrı ölçülür |
| Otomatik restart | **Yapılmaz** |

Planlı kapanışta `begin_shutdown()` çağrılır; sonraki iptaller
`cancelled_planned` olarak işaretlenir ve hata sayılmaz. (İlk gerçek koşuda
bu ayrım eksikti ve normal kapanış FAILED görünüyordu — düzeltildi.)

## 5. PAPER icra gerçekçiliği

| Unsur | Model | Sınır |
|---|---|---|
| Maker dolum | Fiyat seviyeyi **geçmeli** | Kuyruk önceliği bilinmez |
| Kısmi dolum | Tick hacminin ≤%25'i | Gerçek derinlik profili yok |
| Emir zaman aşımı | 20 s, dolmazsa EXPIRED | — |
| Çıkış | Taker + 3 bps kayma | Gerçek slipaj daha kötü olabilir |
| Ücret | maker 2 bps / taker 5 bps | VIP kademesi yok |
| Funding | Yalnız gözlemlenirse uygulanır | Uydurulmaz |

`require_trade_through=True` varsayılan olması bilinçli iyimserlik frenidir:
fiyatın limite yalnız dokunması dolum sayılmaz.

## 6. Veri bütünlüğü

### 6.1 Niyet önce yazılır

```
INTENT → PENDING → (OPEN|PARTIAL) → terminal
```

Süreç PENDING'de ölürse kayıt kalır ve mutabakatla bağlanır. Arşivdeki
v9.2 SQLite kilitlenmesi bu sıralamayla önlendi.

### 6.2 Writer lease

Tek yazar garantisi. Lease yenileme hatası **yutulmaz**, `WriterLeaseError`
yükselir ve supervisor bunu görev ölümü sayar.

### 6.3 Temiz DB

Her koşu yeni DB ile başlar (`fresh=True`). Eski snapshot DB'ler yalnız
kanıttır; sonraki koşuya devredilmez. Arşivin açık talimatı budur.

## 7. Güvenlik

| Önlem | Nerede |
|---|---|
| LIVE mod istisna ile kilitli | `execution/live_guard.py` |
| Config LIVE'ı doğrulamada reddeder | `core/config.py::validate` |
| Anahtarlar `public_info()`'da yok | `ai/registry.py` |
| Config dökümünde anahtar yok | test edilir |
| Pano salt okunur, yazma ucu yok | `web/server.py` |
| Pano yol geçişi engelli (`..`, `/`) | `api_report` |
| Emir gönderen ağ kodu yok | `PaperExecutor` yalnız bellek/DB |

## 8. Bilinçli yapılmayanlar

- Gerçek emir yolu, imzalı borsa istemcisi, anahtar yönetimi.
- Bridge/Compose dağıtımı.
- Tam transitif bağımlılık kilidi (yalnız doğrudan bağımlılık).
- Büyük gerçek defter yük testi.
- Nedensel CPU profili (ölçümler kapsayıcı duvar süresi).
- Korelasyon riskinin tam modellenmesi (yalnız kaba sembol/yön limiti).

Bunlar raporda "yapılmadı" olarak açıkça yazılır; yapılmış gibi sunulmaz.