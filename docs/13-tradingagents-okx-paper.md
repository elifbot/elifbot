# TradingAgents · OKX USDT perpetual paper testi

Bu deney, OKX'in **genel** REST verisini kullanır; borsa anahtarı veya özel API çağrısı yoktur ve borsaya emir göndermez. Açık ve kapanmış işlemler yerel simülasyondur, gerçek OKX demo hesabı değildir.

- Koşunun başında canlı durumdaki lineer USDT perpetual sözleşmeler arasından 24 saatlik yaklaşık USD hacmine göre en yüksek 20 tanesi seçilir. Sembol sayısı işlem limiti değil, gözlem evrenidir.
- Yaklaşık her 5 saniyede genel ticker verisi örneklenir. Kesintiler, güncellik ve kararlar olay dosyasına yazılır. Tam tick akışı veya emir defteri yoktur.
- TradingAgents v0.7.1 araştırma, trader, risk ve portföy yöneticisi düğümleri yerel Ollama `qwen2.5:1.5b` modeliyle çalışır. Küçük CPU modeli hatalı veya okunamayan kararlar üretebilir. Upstream Yahoo analisti yerine yalnızca OKX snapshot'ını aktaran deterministik bir market raporu kullanılır. Haber, funding, emir defteri, sosyal veri ve temel analiz bulunmaz.
- Upstream karar ölçeğindeki `Buy` sanal LONG açabilir. `Sell`/`Underweight` yalnızca mevcut LONG'u kapatır; bunlar doğrudan SHORT anlamına gelmediğinden short açılmaz. `Hold`, `Overweight` ve okunamayan `REVIEW` yeni işlem açmaz. Analiz 300 saniyeden eskiyse veya ilgili fiyat/portföy güncel değilse işlem yapılmaz.
- Varsayılan kasa 1.000 USD, hedef 50 USD teminat / 10x (500 USD notional). OKX kontrat değeri ve lot/minimum bilgisi kullanılarak aşağı yuvarlanır; 500 USD hedefine %10'dan fazla uzaklaşırsa işlem reddedilir. Serbest özkaynak kontrol edilir. İşlem sayısı için ayrıca bir limit yoktur.
- Komisyon %0,05 ve varsayımsal kayma %0,05 **her yönde** uygulanır. Numune fiyatta tahmini net zarar −10 USD'ye ulaşınca pozisyon kapatılır; örnekleme, boşluklar ve kayma nedeniyle zarar −10 USD'den büyük olabilir. Yaklaşık CROSS bakım marjı %0,5 alınır; funding, emir defteri, spread, kısmi dolum ve OKX'in gerçek tasfiye kademeleri modellenmez. Dolayısıyla sonuçlar iyimser veya hatalı olabilir, gerçek emir davranışı değildir.
- Süre, kurulum/model indirme tamamlandıktan ve test başladıktan sonra ölçülür. Açık pozisyonlar test sonunda zorla kapatılmaz; son fiyattan işaretlenir. `summary.json` özeti ve `events.jsonl` karar/işlem kaydı koşu bitince 7 gün saklanan Actions artifact'idir.
- Test sonunda hiç okunabilir karar yoksa job başarısız olur; bağlantı yokluğu veya model hatası asla kârlı test olarak sunulmaz. Az işlem veya 30 dakika kârlılığı kanıtlamaz.

## Başlatma

Dalda iş akışları mevcutken:

```bash
gh workflow run ollama_sonda.yml --ref "$(git branch --show-current)" -f model=paper-30m
```

Actions koşusunda `tradingagents-paper / paper` işinin **OKX gerçek veri ve sanal işlem testi** adımı canlı takip edilebilir. Test ve artifact aynı koşuya bağlıdır. Kısa teknik duman testi için `model=paper-3m` kullanılabilir.
