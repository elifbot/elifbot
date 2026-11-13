# KARIŞIM — OKX PAPER kullanım ve sınırlar

Yalnız sanal işlem; gerçek emir yoktur. Binance PAPER daha sonraya bırakılmıştır. Kaynak kod, testler, birleştirilmiş simülasyon çekirdeği, sınırlı OKX public adaptörü ve Salesforce için doğrulanmamış arayüz taslağı içerir. 191 kaynağın tüm davranışları taşınmış değildir; uzun süreli dayanıklılık, gerçek borsa paritesi, üretim güvenliği veya kârlılık kanıtlanmamıştır.

## Bir kez kurulum

Python 3.10+ kurun. ZIP'i bir klasöre çıkartın, terminalde o klasöre geçin:

```bash
python -m unittest discover -s tests -q
python unified_cli.py init --db data/test.sqlite
```

Bu komut yeni, ayrı bir sanal 1000 USDT defteri oluşturur. Var olan DB üzerine yazmayın. Paket özel geçmiş defterleri içermez.

## Güncel enstrüman seçimi ve başlatma

```bash
python market_universe_cli.py --out reports/benim-okx-piyasalarim.json
python market_watchlist_cli.py --report reports/benim-okx-piyasalarim.json --out benim-ayarlarim.json --target-notional 50 --leverage 1 --min-notional 5 --count 4 --poll-seconds 10
python public_paper_loop.py --db data/test.sqlite --config benim-ayarlarim.json --confirm-public-paper
```

Komutlar mevcut çıktıların üzerine yazmaz. Tarama OKX USDT perpetual kripto kayıtlarını toplar; dört tanesini seçer. Bu işlem yüzlerce piyasanın aynı anda sinyal açısından izlenmesi değildir. Açık pozisyonlar öncelikle izlenir, bu sırada diğer simgelerde tarama atlanır. Seçimin nominal tutarı yaklaşık olup sonraki fiyatlarda değişir. API anahtarı ve özel emir uçları kullanılmaz. Public veri erişimi, çalışma ortamı ve 7/24 süreç sürekliliği garanti edilmez.

Durum görmek için ayrı terminalde `python unified_cli.py status --db data/test.sqlite --format risk` veya `--format omni`. Kontrol görünümü worker'ın hayatta olduğunu doğrulamaz. Ctrl+C ile worker durur; DB'deki pozisyon kapalı sayılmaz. Açık pozisyon veya kesinti sonrasında tazelik, belirsizlik ve kilitleri dikkatle inceleyin.

## Funding

Worker normalde funding anından 180 saniye önce uygun derinlikle sanal çıkış dener; başarılı olacağı garanti edilmez. Açık kalan pozisyonun funding zamanı 120 saniye geçince, OKX public funding history üzerinden birebir zamana ait **gerçekleşmiş oran** aranır. Bulunmazsa, yanlış sembol, mükerrer/çelişkili kayıt, sonraki kaçırılmış funding dönemi veya diğer hata varsa kilitleyerek durur; tahmini oranı gerçekleşmiş diye kullanmaz.

Funding tutarı için ilgili dakikanın bir dakikalık tarihsel mark mumunun **açılışı yaklaşık vekil** olarak kullanılır. Bu OKX'in kesin assessment mark fiyatı değildir. Model funding olayında oran ve vekil fiyat kaynağı saklanır; işlem/özsermaye belirsiz işaretlenir, giriş kilidi uygulanır. Borsa private hesap faturası veya gerçek tutarla mutabakat yapılmamıştır. `paper_operator.py` manuel girdi kaynağını kendisi doğrulamaz.

## Güvenlik sınırları

Giriş risk sınırları, atomik SQLite işlemleri, mükerrer defter olayı koruması, izleme boşluğu kilidi, bayat veri reddi ve kaynak/yapılandırma kontrolleri sınırlı yerel testlere tabidir. Çıkışlar sanal IOC tahminleridir; gap/gerçek likidite/kaldıraç kayıplarını sınırlamaz. Anahtar, gerçek emir, canlı hesap mutabakatı, bağımsız güvenlik denetimi ve Salesforce org kurulumu yoktur.
