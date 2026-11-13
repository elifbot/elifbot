> **Tarihsel belge:** Aşağıdaki ifadeler yazıldıkları aşamanın durumunu anlatır. Güncel kullanım ve funding sınırları için `README.md` ve `docs/OKX_SON_SURUM_KILAVUZ.md` önceliklidir.

# Binance erişimi: önceki belgelerin incelenmesi

## Bulgu ve sınama

Kullanıcının önceki `toplama` arşivindeki `file_64_KURULUM_VE_DEVIR.md` 23, 75 ve 233. satırlar, `BINANCE_PUBLIC_WWW=1` seçeneğinden söz ediyor. `file_78_exchanges.py` 294–308. satırlarda eski botun yalnız public futures yolunun `fapi.binance.com` yerine `www.binance.com` kullandığı görülüyor. Eski belgede 507 sembollü geçmiş başarı ifadesi vardır; bu eski rapor bağımsız kanıt olarak kabul edilmedi. Kullanıcının eski dosyalarında bulunabilecek anahtarlar yeni pakete taşınmadı, kullanılmadı.

9 Kasım 2026 UTC tarihinde bu çalışma alanından:

- Binance'in resmi USD-M API belgelerinde belirtilen `https://fapi.binance.com`: `exchangeInfo` için **HTTP 451**; yanıt hizmetin ağ konumuna kısıt uyguladığını ve hata olduğu düşünülüyorsa Binance destek ile görüşülmesini söylüyor.
- Eski belgede işaret edilen Binance alan adında yalnız herkese açık **GET** veri yolları (`https://www.binance.com/fapi/v1/…`): `exchangeInfo`, `ticker/24hr`, BTC derinlik, 1m mum, mark/premium **HTTP 200** döndürdü. Eski iddia tekrarlanmadı; yeni, ayrı ölçüm yapıldı. BTC için 1273 kapalı 1m mumdan araştırma confluence göstergesi hesaplandı; **PAPER çalıştırılmadı**.
- `21:12:36 UTC` örnek anında OKX **289**, Binance **519**, toplam **808 borsa-sözleşmesi** kaydedildi. Bu rakam benzersiz coin sayısı değildir; borsalar arasında coin tekrarı olabilir. OKX `instCategory=1`, Binance `underlyingType=COIN` borsa beyanları esas alındı; sınıflandırmalar bağımsız doğrulanmamıştır. Anlık evren zamanla değişir; 1000 gerçek sözleşme bulunduğu iddia edilmez.

**Önemli:** `www` denemesinin HTTP 200 dönmesi, kullanıcının veya çalışma ortamının hizmet koşulları/yerel düzenlemeler bakımından yetkili olduğunu göstermez. Resmî belgelenmiş USD-M base URL `fapi.binance.com`'dur; `www` varyantının API desteği, sürekliliği ve şartlara uygunluğu bu çalışmada doğrulanmamıştır. 451 kullanıcının kendi bağlantısının da kısıtlı olduğunu kanıtlamaz. Kullanıcı, kendi ağında erişim hakkını Binance destek/şartlarıyla doğrulamalıdır. VPN/proxy, kimlik gizleme, imzalı istek veya gerçek emir kullanılmadı. 451 alındığında program otomatik alternatif hosta geçmez.

## Yeni ayar ve veri kapsamı

Toplu veri tarayıcı varsayılan olarak yalnız OKX kullanır; `--venues both` açık seçilirse Binance için varsayılan belgelenmiş `fapi` hostudur. Eski belgede geçen `www` yolunu kullanmak kullanıcı tarafından **açıkça** seçilir; sadece sabit, imzasız public GET uçlarına uygulanır:

```bash
# Örnek: izin ve hizmet koşulları doğrulandıktan sonra; PAPER başlatmaz
python market_universe_cli.py --venues both --binance-host www --out data/binance-okx-yeni.json
python binance_signal_research.py --symbol BTCUSDT --binance-host www
```

İkinci komut yalnız bir seçili sembolün kapalı mumlarıyla araştırma skoru hesaplar, işlem önerisi ve PAPER değildir. Binance snapshot (`reports/okx_binance_iki_borsa_2026-11-09.json`, `reports/iki_borsa_futures_2026-11-09.csv`) tarihsel veridir, canlı fiyat değildir. 24 saat endpoint'inden Binance son fiyat ve hacmi gelir; CSV'de Binance bid/ask boş olması doğrudur, bu uç emir defteri değildir.

Binance public enstrüman/24h/derinlik/mum/mark adaptörü ve basit tek-simge araştırma hesabı vardır; **Binance PAPER yürütücüsü, binlerce sembolde sürekli sinyal, otomatik gerçekleşmiş funding mutabakatı, gerçek borsa fill/likidasyon paritesi ve Salesforce org kurulumu yoktur**. Mevcut OKX PAPER worker en fazla dört simgedir ve yalnız açık onayla çalışır. Sürekli operasyon, kârlılık veya finansal uygunluk doğrulanmamıştır.

Kaynaklar: [Binance USD-M genel API](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info), [exchangeInfo](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information), [24h ticker](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/24hr-Ticker-Price-Change-Statistics).
