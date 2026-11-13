# ACARBOT V10 — modüler PAPER araştırma botu

> Güncel çoklu borsa düzeltmesi ve test sonucu: `GECMIS_BOT_DUZELTME_RAPORU.md`. Aşağıdaki ilk Gate testi ve 20 model notları tarihsel bağlamdır; gerçek 12 model görüşü `DIS_YZ_GORUSLERI.md` içindedir.

## Esas alınan dosya
`kaynak-v10.html`, kullanıcının yüklediği `acarbot-system (1).html` dosyasının
birebir kopyasıdır. SHA-256:
`d384e8447aeffeadd9fd1f5e3f7e17890f6eda65bb235b0535fd50cd049ca9d2`.
Önceki HTML bu sürümün yerine kullanılmamıştır.

## Modüller
- `main.py`: komut satırı ve koşu ayarları.
- `strategy.py`: kapanmış 5dk mum, EMA 20/50/200, RSI, MACD, Bollinger;
  6 strateji, 2 mum teyidi ve 20 mum hacim filtresi.
- `ledger.py`: yalnız sanal al/sat defteri, alış/satış fiyatı, varsayımsal
  komisyon/kayma, ATR stop/hedef, 1R başabaş/takip, risk ve açık pozisyon sınırı.
- `runner.py`: Gate.io USDT perpetual kamu verisi, 20 kripto örneklemi,
  tazelik, funding yakınlığı, makas/maliyet kapısı, kural konseyi, olay kaydı.
- `test.py`: modül testleri. `parite.py`: son HTML JavaScript kararlarıyla
  sentetik örnekler üzerinde karşılaştırma (Node.js gerekli).
- `../omnistudio/`: piyasa adaptörü, risk katmanı ve konsey altyapısı.

## Kurulum ve çalıştırma (proje kökünden)
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python test.py
python main.py --duration 600 --symbols 20 --strategy trend
```
Diğer stratejiler: `rsirev`, `kombin`, `macd`, `bollkir`, `bolldon`.
Yalnız EMA trendi 10 dakika gerçek veriyle denenmiştir; diğer beş stratejinin
canlı koşu iddiası yoktur.
İsteğe bağlı parite kontrolü: `python -m acarbot.parite` (Node.js gerekir).

## Tasarım seçimi ve kaynakla farklar
Kaynağın altı sinyal kuralı örnek alınmıştır, ancak birebir ürün aktarımı
**değildir**. Kaynak HTML Binance/OKX/Bybit'i ve çok geniş evreni hedefler;
bu testte coğrafi erişim nedeniyle Gate.io kamu vadeli ucu ve önceden
belirlenmiş 20 kripto kullanılır. Gerçek borsa emri yolu yoktur. HTML'deki
2.5x ATR stop, 5x hedef ve 1R korumalar örnek alınmış; OmniStudio risk
sınıfının minimum/maksimum stop mesafesi ve düşük pozisyon boyutu sınırları da
uygulanmıştır. Pozisyon modeli HTML'deki marjin/kaldıraç/likidasyon hesabının
birebir karşılığı değildir. Kaynakta mum hacmi baz birimdeyken Gate verisinde
USDT hacmi kullanılmaktadır; aynı hacim filtresinin matematiği birebir olsa da
birim farkıyla kararlar değişebilir. EMA/RSI hesap ve veri geçmişi farkları da
canlı sonuçları değiştirebilir.

Son HTML'deki ticker yedeği, gömülü sembol listesi, tarayıcı CORS röleleri,
grafikler, arayüz, optimizasyon/lab/backtest, Sharpe/Sortino/Calmar ve bütün
borsa bağlayıcıları bu V10 Python çekirdeğine taşınmamıştır. Ağ hata sınırı ve
kamu verisi tazeliği ayrı ele alınır; sentetik veriyle sessiz geçiş yoktur.

## Güvenlik ve doğruluk sınırları
- PAPER: borsaya gerçek emir göndermez; `real_money_approved=false`.
- Stop, ayarlandığı fiyattan gerçekleşme veya maksimum zarar garantisi değildir.
  Quote aralıklarında fiyat hareketi kaçabilir; emir defteri derinliği ve
  gerçek taker dolumları modellenmez.
- Komisyon taraf başına 5.5 bps, ek kayma 2 bps varsayımdır; hesap özel gerçek
  ücret değildir. Rapor gerçekleşmiş ve açık pozisyonu birbirinden ayırır.
- Funding zamanı bilinmeyen/yakın işlemler reddedilir; funding gerçekleşmeden
  önce açık pozisyon kapatılmaya çalışılır. Funding muhasebesi **yoktur**;
  veri kaybı halinde açık pozisyon belirsiz kalabilir.
- Veri, işlem hacmi, kısa örneklem ve karar sonuçları kârlılık kanıtı değildir.
  Önceki araştırmanın gerçek para onayı yoktur.
- API anahtarları yok: 20 gerçek yapay zekâ görüşü veya tartışması
  **alınmamıştır**. İşlem öncesi `RULE_BASED_QUANT` deterministik kural
  denetçileridir, LLM değildir. Gerçek sağlayıcılar anahtar/erişim/ücret ve
  bağımsız doğrulama gerektirir. Mum bazlı akış, genişlik ve 15dk teyidi
  ölçülmediğinden konsey girişlerinde yer tutucu vardır, sonuç ihtiyatla okunur.
- Run dosyaları normal bitişte `SONUC.json`, `config.json`, `events.jsonl`;
  süreç kesilirse sonuç dosyası olmayabilir, bu tamamlanmış test sayılmaz.

## Binance / OKX ve dış model incelemesi güncellemesi
Anahtarsız gerçek model görüşleri ve filtrelenmiş bulgular için
`acarbot/DIS_YZ_GORUSLERI.md`; kapsam, çalıştırma ve eksikler için
`acarbot/BINANCE_OKX_DURUM.md` dosyasına bakın. Yukarıdaki Gate koşusunun
sonuçları, daha sonra eklenen Binance/OKX kodunun testi değildir.
