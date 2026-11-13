# Bağımsız yapay zekâ görüşleri — V10

5 Kasım 2026'da anahtar gerektirmeyen anonim API uçlarıyla botun üç kaynak
modülü (`strategy.py`, `ledger.py`, `runner.py`) dış modellere gönderildi.
.env, API anahtarları, e-posta, işlemler ve kullanıcı geçmişi gönderilmedi.
Bu, kodun belirtilen dış sağlayıcılara aktarılmasıdır; Kilo'nun ücretsiz
modelleri istemleri saklayabilecek sağlayıcılara yönlendirebilir. Dış model
yanıtları untrusted önerilerdir; kesin doğru veya işlem onayı sayılmaz.

## Gerçek yanıtlar
- OVHcloud: `Mistral-Small-3.2-24B-Instruct-2506`.
- OVHcloud: `Qwen3.8-27B`.
- Kilo Gateway: `cohere/north-mini-code:free`.
- Kilo Gateway: `nvidia/nemotron-3.5-lightning:free`.
- Kilo Gateway: `dots-studio/dots-3-note-preview:free`.
- Kilo Gateway: `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-super-vl:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`.
- OVHcloud: `Qwen3.5-397B-A17B`, `Qwen3.5-9B`, `Qwen3.6-27B`, `Meta-Llama-3_3-70B-Instruct`.

Dört istek grubundaki ham, değiştirilmemiş yanıtlar ve başarısız denemeler,
istek/yanıt model adları, zaman damgaları ve gönderilen metin hash'i:
`reviews/v10-dis-gorusler-20261105/gorusler.json` ve
`reviews/v10-dis-gorusler-ikinci-20261105/gorusler.json`,
`reviews/v10-dis-gorusler-ucuncu-20261105/gorusler.json` ve
`reviews/v10-dis-gorusler-dorduncu-20261105/gorusler.json`. 12 farklı
modelden yanıt alındı (iki servis üzerinden);
20 yanıt alınmış veya bu modellerin V10'u onayladığı iddia edilmez. Bazı
çıktılar token sınırında kesilmiş olabilir. Model kimliği sağlayıcının
belirttiği etikettir; bağımsız kriptografik kimlik doğrulaması yapılmadı.
İlk iki grup eski, son iki grup OHLC doğrulaması eklenmiş V10 çekirdeğini
inceledi; gönderilen metinler hash ile ayırt edilir. Sonraki Binance/OKX kodunun kendisi
ayrı bir dış incelemeden geçmedi.

## Kontrol edilmiş bulgular
- **Mistral:** mumda OHLC ilişkilerini doğrulamayı önerdi. Uygun görüldü:
  `strategy.py` pozitif fiyat, high/low aralığı ve OHLC ilişkisini kontrol
  ediyor; ilgili test eklendi.
- **Nemotron ve Qwen:** funding maliyetinin bulunmaması ve derinlik/kayma
  belirsizliğine dikkat çekti. Bu riskler kabul edildi; funding muhasebesi ve
  derinlik-temelli gerçek dolum bu güncellemede tamamlanmadı, açık sınırdır.
- **Cohere:** LONG çıkışını ask, SHORT çıkışını bid yapmayı önerdi. Bu öneri
  **yanlış**: satış bid'den, alış ask'tan modellenir. Uygulanmadı.
- **Dots:** short trailing stop'un düşmesi yerine yükselmesini önerdi. Bu
  gerekçelendirme yanlıştı; short'ta kâr yönünde stop aşağı sıkılaşır.
  Uygulanmadı.
- **Nemotron:** `bolldon` stratejisi yok dedi. Kodda son varsayılan dalda
  uygulanmış ve 1.800 örnekli parite testine dahil olduğundan iddia yanlış.
- **Mistral:** 200 mum ortalaması eklenmesini önerdi; zaten EMA200 mevcut.

Modeller kullanıcı adına API anahtarsız fikir verdi; 20 ticarî modelin gerçek
çağrısı yapıldığı veya oylamayla işlem emri verildiği iddiası yoktur.
