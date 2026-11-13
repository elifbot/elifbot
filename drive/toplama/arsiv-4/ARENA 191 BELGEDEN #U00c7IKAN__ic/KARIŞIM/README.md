# KARIŞIM — OKX PAPER araştırma botu

Bu yazılım bir **sanal işlem prototipidir**. Yalnız OKX public verileriyle çalışır; API anahtarı ve gerçek emir kullanmaz. Binance PAPER entegrasyonu sonraya bırakılmıştır. Kârlılık, gerçek dolum/likidasyon paritesi, Salesforce org kurulumu ve 7/24 güvenilirlik doğrulanmamıştır. 191 kaynağın tüm özellikleri aktarılmış değildir.

## Başlangıç

Python 3.10+ ve internet erişimi gerekir. ZIP'ten çıkardığınız klasörde:

```bash
python -m unittest discover -s tests -q
python unified_cli.py init --db data/kendi-paper.sqlite
python public_paper_loop.py --db data/kendi-paper.sqlite --config public_paper_config.example.json --confirm-public-paper
```

DB adı daha önce var olmamalıdır. Örnek BTC miktarı sabittir; piyasa değerine ve sözleşme kurallarına uymadığında giriş reddedilebilir. Yeni bir taze piyasa listesiyle en fazla dört OKX enstrümanı seçmek ve parametreleri kontrol etmek için `docs/OKX_SON_SURUM_KILAVUZ.md` ile `market_universe_cli.py --help` ve `market_watchlist_cli.py --help` okuyun. İşlemler tamamen sanaldır. Ctrl+C süreci durdurur; açık sanal pozisyon otomatik kapatılmış sayılmaz. Yeniden başlatma kesinti belirsizliği yaratabilir.

## İzleme

```bash
python unified_cli.py status --db data/kendi-paper.sqlite --format risk
python unified_cli.py status --db data/kendi-paper.sqlite --format omni
```

Durum, worker'ın halen çalıştığını kanıtlamaz. Finansal defter ve risk kontrolleri yalnızca modeldir. Giriş ve çıkış derinliği IOC simülasyonudur, gerçek dolum garantisi değildir; komisyon ve marj varsayımsaldır.

## Funding

Olası funding zamanından 180 saniye önce sanal kapanış denenir; garanti değildir. Pozisyon açık kalırsa, ilgili dönem üzerinden en az 120 saniye geçtikten sonra OKX public history içinden tam zaman eşleşen `realizedRate` alınır; yoksa veya çelişki varsa girişler kilitli kalır. Tarihsel 1 dakikalık mark mumunun açılışı yalnızca **yaklaşık fiyat vekilidir**, OKX'in gerçek assessment markı değildir. Dolayısıyla otomatik funding tutarı tahmin olarak kaydedilir, pozisyon ve geçmiş belirsiz işaretlenir ve giriş kilidi uygulanır. Borsa hesap faturası ile mutabakat yapılmaz. Manuel operatör girdisi de doğrulanmış sayılmaz.

30 saniyeyi aşan izleme boşluğu kalıcı belirsizlik ve güvenlik kilidi doğurur; bayat veriyle sahte işlem yazılmaz. Güvenlik testleri sınırlıdır; üretim güvenliği kanıtı değildir. Salesforce yalnız taslak ve test/mock içerir, gerçek ortamda kurulmadı.

Eski belgeler tarihsel geliştirme adımlarını anlatır; mevcut durumla çelişirse bu README ve `docs/OKX_SON_SURUM_KILAVUZ.md` önceliklidir. ZIP'te önceki özel sanal defterler, API anahtarları ve Gmail arşivi bulunmaz.
