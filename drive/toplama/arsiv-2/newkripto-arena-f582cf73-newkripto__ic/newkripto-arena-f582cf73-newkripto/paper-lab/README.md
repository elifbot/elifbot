# Paper Lab — Kripto Bot Araştırma ve Kanıt Arşivi

Bu dizin, mevcut `kripto-bot` reposu içindeki bağımsız araştırma/arşiv projesidir.
Amaç; baseline stratejiyi ve geçmiş deneyleri koruyarak yeni fikirleri aynı kanıt
standartlarıyla ölçmek, hiçbir paper sonucunu otomatik canlı kurala dönüştürmemektir.

## Hızlı bağlantılar

- **Kalıcı proje hafızası:** [`../PROJECT_MEMORY.md`](../PROJECT_MEMORY.md)
- **Üç deneme genel analizi:** [`../analysis/UC_DENEME_GENEL_ANALIZ.md`](../analysis/UC_DENEME_GENEL_ANALIZ.md)
- **Araştırma sırası ve yeni fikir kuralları:** [`RESEARCH_BACKLOG.md`](RESEARCH_BACKLOG.md)
- **Run/dosya manifesti:** [`manifest.json`](manifest.json)
- **Makine-okunabilir üç-run metrikleri:** [`three-run-metrics.json`](three-run-metrics.json)
- **PDF v2 indikatör envanteri/backlog:** [`PDF_INDIKATOR_ANALIZI.md`](PDF_INDIKATOR_ANALIZI.md)
- **Ana bot ve Shadow kodu:** [`../src/`](../src/)
- **Workflow:** [`../.github/workflows/paper-live.yml`](../.github/workflows/paper-live.yml)

## Ana deney üçlüsü

| Sıra | Run | Okuma |
|---|---|---|
| 1 | [39969507314](https://github.com/omeracar56/kripto-bot/actions/runs/39969507314) | 100.000 USDT; çapraz kurtarma + duplicate-close/muhasebe sorunu. OKX-only; birleşik borsa kanıtı değil. |
| 2 | [40077757773](https://github.com/omeracar56/kripto-bot/actions/runs/40077757773) | 100.000 USDT; 2 saat, çapraz kurtarma kapalı, planlı closeout ve iki-borsa kanıtı. |
| 3 | [40090692312](https://github.com/omeracar56/kripto-bot/actions/runs/40090692312) | 1.000 USDT; 60 dakika, altı Shadow varyantı. 9/9 kapanış, net −3,05 USDT; tüm kapanışlar flash-crash sigortası. |

## PDF v2 kontrollü deneyi

[Run 40095304624](https://github.com/omeracar56/kripto-bot/actions/runs/40095304624) —
`a5b8d0e`, 1.000 USDT, 50 USDT marj/10x, 120 dakika, Binance+OKX ve yedinci
`pdf-confluence` Shadow varyantı. Başlangıç kontrolleri PASS; nihai sonuç bu dosyaya ve
manifest'e artifact sonrası işlenecek.

## Çalışma kuralları

1. Her yeni deney önce run ID, commit SHA, kasa, süre, marj/kaldıraç ve borsa kapsamıyla kaydedilir.
2. Gerçek emir yok; Binance+OKX birlikte doğrulanmadan birleşik sonuç iddia edilmez.
3. Botun doğal kapanışları ile sigorta/manuel/erken/süre-sonu kapanışları ayrılır.
4. Net K/Z; brüt fiyat K/Z, giriş/çıkış ücreti ve funding ile mutabık olmalıdır.
5. İşlem sayısı tek başına başarı ölçütü değildir; median net, PF, drawdown, maliyet,
   kaçırılan kazanan ve sonuç yoğunlaşması birlikte okunur.
6. Tek run veya kısa kesit gelecek kâr/zararsızlık garantisi değildir.
7. Secret, token, chat ID ve `.env` arşive eklenmez. Loglar maskeli tutulur.

## Yeni yenilikler nereye eklenecek?

Yeni fikir önce `RESEARCH_BACKLOG.md` içine hipotez, ölçüm, kabul/ret ve risk sınırıyla
yazılır. Ardından izole Shadow varyantı veya ayrı paper profili olarak uygulanır.
Baseline sonuçları silinmez veya geçmişe dönük değiştirilmez; yeni run ayrı klasörde saklanır.
