# ACARBOT — ortak inceleme, anlık akış ve sözleşme hesapları

**Durum: veri gecikmesinde test edilen iyileşme; tüm sözleşmelerde PAPER işlem hâlâ KISMİ.** 5 Kasım 2026. Hiç gerçek borsa emri yoktur.

## Ortak model çalışması
İlgili önceki futures kaynakları iki haricî servis üzerinden 9 modele gönderildi; 7 model yanıtladı. İkinci turda üç model, diğer modellerin yanıtlarından kesitleri çapraz değerlendirdi. İsimler, ham cevaplar, başarısız çağrılar ve kabul/reddedilen hatalı öneriler `acarbot/ORTAK_MODELLER_INCELEMESI.md` ve `reviews/futures-*-inceleme-20261105/gorusler.json` içindedir. Bu, OmniStudio'daki 20 kayıtlı sağlayıcının tamamının katıldığı anlamına gelmez. Modeller yeni yazılan kodu görmedi; yeni kodun model denetiminden geçtiği iddia edilmez.

## Anlık veri birikimi
`acarbot/futures_stream.py` Binance USD-M / COIN-M ve OKX SWAP / FUTURES için 5 dakikalık WebSocket mumlarını dinler. Açık mum güncellemeleri bellekte gözlenir; **borsanın kapanmış olarak doğruladığı mumlar** SQLite veritabanına kayıtlı olarak birikir. Tekrarlar `(pazar, sembol, mum açılış zamanı)` anahtarıyla engellenir; boşluklar `incidents` tablosuna yazılır. Collector emir açmaz. Sembol listesi başlangıçta alınır ve çalışma sırasında otomatik yenilenmez.

`runs/canli-mum-akisi-10dk-20261105/`: bağımsız 600 saniyelik gerçek veri gözlemi, 24 WS bağlantısı:
- Dört pazarda toplam 1.661 seçilen sözleşmenin tamamından güncelleme ve kapanmış mum alındı.
- 237.517 tekrar içeren açık/kapanmış mum güncellemesi; 3.322 tekil kapanmış mum (her sözleşmeden iki mum).
- 3.322 mumun tamamı 90 saniyelik tazelik sınırında ve 5 saniye içinde kaydedildi. Kapanıştan gözleme medyan 1,024 sn; en uzun 3,072 sn. Sistem saati ile borsa zamanına bağlıdır; bu ölçüm emir gecikmesi değildir.
- 0 kaydedilen boşluk; testte 0 bağlantı hatası ve 0 gerçek/sanal emir. SQLite bütünlük kontrolü `ok`. SQLite verisi `candles.sqlite3`, okunabilir CSV `KAPANMIS_MUMLAR.csv`.

Bu, 10 dakikalık gözlemdeki sonuçtur; gelecekte her mumun geleceği veya 7/24 kesintisizlik kanıtı değildir.

## Anlık akışa bağlı gerçek veri PAPER testi
`acarbot/futures_stream_paper.py` ilk geçmişi REST ile yükler, sonra ayrı collector'ın SQLite kapanış kayıtlarını okuyup her sembolü ayrı değerlendirir. Eski mum tazelik sınırı gevşetilmedi. `runs/canli-akis-paper-10dk-20261105/SONUC.json`, `events.jsonl`:
- Isınma dahil 868,456 sn; **600,392 sn aktif PAPER**. 1.661 sembolün başlangıç geçmişi alındı.
- 3.322 mum değerlendirildi: **0 STALE_CANDLE**. Önceki REST tarama koşusunda 2.735 değerlendirmenin 1.402'si eskiydi; testler farklı zamanlarda ve farklı uygulamayla yapıldığından bu kontrollü eşzamanlı A/B karşılaştırması değildir.
- Dokuz giriş eski quote nedeniyle ayrı olarak reddedildi; tüm gecikme/risk sorunları çözülmüş değildir.
- **6 sanal pozisyon:** 5 Binance USD-M, 1 OKX SWAP; 1 sanal STOP_LOSS ile ve 5'i RUN_END ile kapandı. Varsayımsal komisyon/kayma dahil net **−9,024072 USDT**; başlangıç 1.000, bitiş 990,975928 USDT. Gerçek emir 0. Bu bir kârlılık kanıtı ya da gerçek dolum değildir.
- Yine **1.047 enstrüman USDT lineer perpetual PAPER için uygun; 614 otomatik PAPER hesabı dışında**. 134 sinyal, desteklenmeyen sözleşme türü nedeniyle reddedildi.

## 614 sözleşmenin hesap çekirdeği: deneysel, motora bağlı değil
`acarbot/contract_math.py` Decimal ile yerel settlement para biriminde lineer/inverse PnL, sözleşme çarpanı, miktar adımı, örnek ücret ve açık funding olayı matematiği sağlar; otomatik kur veya 1:1 USD/USDT/USDC dönüşümü yapmaz. Başlangıç bakiyesi para birimi bazında açıkça verilmelidir. Vade aşımı durumunda otomatik tasfiye uydurmak yerine reddeder.

`acarbot/futures_contract_audit.py` gerçek kamu sözleşme metaverisini taradı: 1.661/1.661 aktif kaydı bu temel şemaya eşledi ve her birinde hem LONG hem SHORT olmak üzere **3.322 sentetik fiyatlı matematik gidiş-dönüşü** denedi; `runs/sozlesme-matematik-denetim-20261105/SONUC.json`. Bunlar gerçek sinyal, canlı PAPER strateji işlemi, borsa dolumu veya bütün finansal kuralların ispatı değildir.

**614'ü hâlâ tamamen çözdük denemez:** Çoklu para portföy sermayesi/kuru ve ortak risk, gerçek zamanlı funding olayları, farklı fee kuralları, borsa asgari/maksimum emir filtreleri, vade uzlaşısı, X-PERP özel kuralları ve canlı PAPER entegrasyonu tamamlanıp test edilmelidir. Bu yüzden deneysel hesap motoru mevcut otomatik PAPER çalıştırıcısına bağlanmadı ve güvenlik filtresi kaldırılmadı.

## Kopma ve çalıştırma
Collector kopmada yeniden bağlanmayı dener ve ardışık kapanmış mumlardaki boşluğu kaydeder. `acarbot/futures_backfill.py` kaydedilmiş ve en fazla 250 mumluk boşlukları yalnız gerçek kamu REST geçmişi ile **elle** onarmayı dener; eksik geçmişi üretmez ve eksikse unresolved bırakır. Otomatik backfill yoktur; geçmişi stratejiye doğrudan yeni sinyal olarak sunmaz. Uzun kopmalar, yeni listelenen sözleşmeler, saat sıçraması ve tam portföy güvenliği ayrıca ele alınmalıdır.

Çalışma alanında test sonrası 86.400 saniye hedefli ayrı collector başlatıldı. Burası kalıcı sunucu değildir: platform/sandbox kapanması, ağ kopması veya süre sonunda toplama durabilir; kesintisiz 7/24 garanti değildir. Canlı collector sadece kapalı mum yazar, PAPER strateji süreci 10 dakikalık test sonunda durdu.

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 test.py
# Ayrı terminal: devamlı veri biriktir (süre dolunca durur)
python3 -m acarbot.futures_stream --duration 86400 --out runs/akis-1 --db runs/mumlar.sqlite3
# İkinci terminal: aynı DB ile 600 sn USDT-perpetual PAPER
python3 -m acarbot.futures_stream_paper --duration 600 --out runs/paper-1 --db runs/mumlar.sqlite3
# Gerekirse kaydedilen boşlukları elle onar (otomatik değildir)
python3 -m acarbot.futures_backfill --db runs/mumlar.sqlite3 --out runs/onarim-1
# Sentetik sözleşme matematiği denetimi; emir yok
python3 -m acarbot.futures_contract_audit --out runs/kontrat-tani-1
```
`--out` her denemede daha önce var olmayan klasör olmalıdır. Aynı DB için bir collector kullanın. Yeni kapalı mumlar DB'ye yazılır; dosyayı çalışırken yedeklemek için SQLite online backup kullanın, yalnız ana dosyayı kopyalamayın.

## Testler
148 ağsız test; sentetik HTML/strateji paritesi 1.800 kontrol ve 0 fark. Bu testler gerçek para uygunluğu veya borsa ücretlerinin doğruluğu değildir.
