# v9.5.2 — ılımlı PAPER denemesi

Kullanıcının onayladığı üç eşik: trend verimliliği **0,20 → 0,17**; yönlü akış **8 → 6**; göreli hacim **0,90 → 0,85**.

**Risk ve güvenlik gevşetilmedi.** StateStore, Executor, PAPER broker, ATR/adaptif risk formülleri, süreklilik ve dolum öncesi giriş kilidi v9.5.1 ile byte-identical. Spread/maliyet, gerçek taker, RSI/HTF, kapalı mum ve 180 sn tazelik sınırı değişmedi.

## Kanıt
- Tam test kümesi: **259 geçti, 32.75 sn**.
- Yeni ZIP temiz klasöre açılarak: **259 geçti, 32.94 sn**.
- Test sonrası **347 mühürlü dosya** yeniden hash doğrulamasından geçti.
- 106 Python dosyası compile ve panel JavaScript sözdizimi kontrolü geçti.
- Yeni testler üç eşik sınırını, LONG/SHORT simetrisini, korunmuş filtreleri, varsayılan baseline uyumunu, aynı-girdi karşılaştırmasını ve güvenlik/drenaj engellerini kapsıyor. Eski testler atılmadı; yetkili hash/AST değişiklikleri açık listelendi ve eski halleri korundu.

## Yeni doğal test protokolü
Yeni boş defter/prefix ile 600 sn aktif + gerekirse en fazla 120 sn girişsiz drenaj. Başlangıç ısınması ayrıca. Prefix: `natural10m_mild`; oturum: `v952-mild-paper10m-20261103`.

Yalnız mild profil PAPER emir açabilir. Baseline ve mild aynı mum/özellik, piyasa bağlamı, fiyat/spread ve zamanda yan yana değerlendirilir. Sembol–mum başına ilk gözlem `_profiles.jsonl` dosyasında kaydedilir. Ortak tazelik/sapma/giriş engelleri ayrıca gösterilir. Çekirdek sinyali ve Executor öncesi aday sayısı ayrılır.

**Bu iki portföyün kâr karşılaştırması değildir.** Baseline shadow emir/dolum/PnL üretmez. Yalnız mild profilin gerçekleşmiş PAPER PnL'si olabilir. Kontrollü sınır testleri doğal kârlılık kanıtı değildir; daha fazla işlem garanti edilmez. Yeni doğal koşu bu teslim raporunda henüz başlamamıştır; ayrı makbuzla e-posta doğrulamasından sonra başlatılır.

Önceki 691 stale-mum reddi, 54 sembol–mum çiftinin tekrarlarıydı. Bu deneyde eski mumu kabul ederek işlem üretilmiyor; tazelik sorunu yeni tekrarsız kayıtlarla ayrıca ölçülüyor.

## Paket
Ana kod ZIP: `kripto-bot-v9.5.2-PAPER-RC1-mild-kod-test-rapor.zip`  
Boyut: 5780217 bayt  
SHA-256: `1679f75fe6be8a1ff3f22380c389715d7397e3c61b6f83b8e10eae64adeb9c31`

Tüm güncel kod, testler, raporlar, v951→v952 tam farkı, hash/AST testleri, çevrimdışı Omnistudio inceleme sayfası ve yeni koşu protokolü dahil. Eski v9.5.1 kodu ve eski test defteri değiştirilmedi. Dış model/ücretli API: 0. Gerçek para kapalı. Docker veya dış model onayı iddia edilmiyor.
