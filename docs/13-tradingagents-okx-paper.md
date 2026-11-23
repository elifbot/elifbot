# TradingAgents · OKX vadeli paper testi

Bu deney yalnızca OKX'in **genel** REST verilerini kullanır; borsa anahtarı veya özel API çağrısı yoktur ve borsaya emir göndermez. Yerel simülasyondur, OKX demo hesabı değildir.

## Evren ve sinyal

- OKX'in aktif `SWAP` (sürekli) **ve** `FUTURES` (vadeli) sözleşmelerinin tamamı alınır ve yaklaşık her dakika liste yenilenir. Sabit sembol sayısı veya hacme göre ilk N filtresi yoktur. Yaklaşık 5 saniyede bir ticker'lar sorgulanır; taze fiyatı olmayan sözleşmede sinyal üretilemez.
- Örneklenen fiyatın yaklaşık bir dakikalık yönüne göre LONG veya SHORT aday sinyal oluşur. En az 50 saniye veri gerekir; fiyat değişmemişse sinyal yoktur. Bu basit sinyal, kârlılığı kanıtlanmış bir strateji değildir.
- TradingAgents v0.7.1 araştırmacı, trader, risk ve portföy yöneticisi düğümleri adayları Ollama `qwen2.5:0.5b` ile değerlendirir. OKX snapshot'ını aktaran deterministik rapor upstream Yahoo analistinin yerini alır. Küçük yerel model zayıf, yavaş veya hatalı karar verebilir; haber, funding, emir defteri ve temel analiz sağlanmaz.
- Modelin `Buy`/`Overweight` görüşü LONG adayını, `Sell`/`Underweight` görüşü SHORT adayını onaylayan **bu deneyin özel eşlemesidir**. Upstream `Sell` tek başına short emri değildir. Çelişki, `Hold` veya okunamayan çıktı işlem açmaz. Ters yönde onaylanmış aday mevcut sanal pozisyonu kapatıp yeni yönü açabilir.
- Tek CPU modelinin kapasitesi sınırlıdır: evrenin tamamı taransa bile gelen her sinyalin 30 dakikada değerlendirilmesi garanti değildir. Adaylar kuyruğa girer; 300 saniyeyi aşan sinyaller eski diye işlem yapılmadan çıkarılır. Sinyal, kuyruk, eskime ve karar sayıları logda ve özette gösterilir.

## Simülasyon sınırlamaları

- Simülatör USD/USDT/USDC fiyatlı doğrusal ve USD/USDT/USDC fiyatlı inverse sözleşmeleri destekler; USD, USDT ve USDC yaklaşık 1 USD sayılır. Başka fiyat para birimleri de taranır ve sinyalleri değerlendirilir, ancak çevrim kuru modeli olmadığından sanal işlem reddedilir. Koşu sırasında vadesi dolacak enstrümanda yeni pozisyon açılmaz; bu bir işlem adedi limiti değildir.
- Varsayılan kasa 1.000 USD, hedef 50 USD teminat / 10x (500 USD notional). OKX kontrat değeri, çarpanı, lot ve minimum miktarı kullanılarak aşağı yuvarlanır; 500 USD hedefine %10'dan fazla uzaklaşırsa işlem reddedilir. Serbest özkaynak kontrol edilir. Ek pozisyon sayısı limiti yoktur.
- Komisyon %0,05 ve varsayımsal kayma %0,05 **her yönde** uygulanır. Örneklenen fiyatta tahmini net zarar −10 USD'ye ulaşınca pozisyon kapatılır; örnekleme, boşluklar ve kayma yüzünden kayıp daha büyük olabilir. Yaklaşık CROSS bakım marjı %0,5'tir. Funding, emir defteri, spread, kısmi dolum, gerçek kaldıraç limitleri ve OKX'in tasfiye kademeleri modellenmez. Inverse kontrat PnL'si USD karşılığıyla yaklaştırılır; teminat parası riski modellenmez. Sonuçlar gerçek emir davranışı değildir.
- Süre, kurulum/model indirme tamamlandıktan sonra ölçülür. Açık pozisyonlar test sonunda zorla kapatılmaz; son fiyattan işaretlenir. `summary.json` ve `events.jsonl` koşu bitince 7 gün saklanan Actions artifact'idir. Veri kaybı, eskime, hatalar ve işlem reddi günlüğe yazılır.
- Hiç kullanılabilir karar yoksa iş başarısız olur. Az işlem veya 30 dakikalık sonuç kârlılığı kanıtlamaz.

## Başlatma

```bash
gh workflow run ollama_sonda.yml --ref "$(git branch --show-current)" -f model=paper-30m
```

Actions koşusunda `tradingagents-paper / paper` işinin **OKX gerçek veri ve sanal işlem testi** adımı canlı takip edilebilir; çıktılar aynı koşudaki artifact'tedir. `model=paper-3m` kısa teknik duman testidir.

## Arena inceleme paneli

```bash
.venv/tradingagents/bin/python -m panel.tradingagents_server --host 0.0.0.0 --port 8000
```

Panel GitHub'daki **45185083638** numaralı geçmiş koşunun anotasyonlarını `gh` ile okur; yeni bir gerçek piyasa koşusu başlatmaz. Çalıştırıldığı ortamın GitHub erişimi gerekir. Panel açılırken LONG/SHORT, TradingAgents grafiği ve sanal defter için ağsız bir teknik prova başlatılır; bu prova sentetik fiyatlar ve deterministik sahte model kullanır, performans ölçmez. Panelden tekrar çalıştırılabilir. Arena geliştirme ortamında OKX'e dış ağ erişimi ve yerel Ollama servisi bulunmadığı için burada gerçek piyasa/model testi yapılamaz.
