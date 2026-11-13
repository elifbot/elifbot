# Kritik bulgular — kaynaklara ve kanıt düzeyine bağlı

Bu inceleme gerçek para onayı değildir. Yalnız belirtilen izole fonksiyon deneyleri ve yeni prototip testleri bu çalışma sırasında çalıştırıldı. Diğer bulgular statik kod okuması veya arşivdeki önceki rapor beyanıdır; önceki raporların testleri otomatik olarak yeniden yapılmış sayılmaz.

## K1 — Açık metin Telegram bot kimlik bilgisi
- **Kaynak:** `file_176_Yeni Metin Belgesi (3).txt`, ilk satır. Bir bot URL'si içinde erişim bilgisi bulunuyor. Değer ve URL bu rapora, analiz paketine veya yeni kaynak koduna kopyalanmamıştır.
- **Risk:** Bu değer geçerliyse sahip olduğu bot yetkileri kötüye kullanılabilir. Bu incelemede Telegram'a bağlanılmadı ve geçerlilik doğrulanmadı.
- **Önlem:** BotFather aracılığıyla token iptal/yenileme; eski değerin kullanıldığı servisleri güncelleme; paylaşılan yedekleri ve geçmişleri kontrol etme. Sadece gizlemek yeterli değildir. Diğer değerler için statik anahtar sözcük taraması tam bir sır denetimi değildir.

## K2 — Bir proje dosyasının içinde gizli ikinci proje ve canlı emir kodu
- **Kaynak:** `file_128_make_bot_v2.py` L12–698; `file_167_make_bot_v2.py` birebir aynı. Script çalıştırılmadan literal AST çıkarımıyla 10 gömülü dosya tespit edildi: `GOMULU_PROJE.md`.
- **Risk:** Örnek config L40–52 paper/testnet/live seçeneklerini içeriyor; max pozisyon ve günlük kayıp alanları null. Bunun çalışma zamanında nasıl yorumlandığı ayrıca sınanmadı. Gömülü ccxt broker içinde gerçek borsa emir API'si çağrısı var; bu nedenle arşivdeki bütün kodun paper-only olduğu söylenemez. Dosyayı çalıştırmadık.
- **Önlem:** Eski broker doğrudan taşınmaz veya çalıştırılmaz; yeni sistemde gerçek emir modülü ve anahtar erişimi yoktur. Risk limitleri açık ve doğrulanmış olmalıdır.

## K3 — Kısmi dolum ve kapanış muhasebesi: gömülü broker
- **Kaynak:** `file_128_make_bot_v2.py` L592–631. Bekleme döngüsü `filled` değerini yalnız terminal statüde okuyor; süre dolunca `filled <= 0` ise iptal deneyip `False` döndürüyor. Kısmen dolu ve hâlâ açık emirde, iptal sonrası nihai durum/dolum burada yeniden sorgulanmıyor.
- **Risk:** Kod yolunun statik okuması, kısmi dolumun yerel pozisyona yansımadan belirsiz kalabileceği bir senaryo gösteriyor. Gerçek bir borsada yeniden üretilmedi; borsa/ccxt semantiği ve çağıran katman ayrıca incelenmeli.
- **Kaynak:** aynı dosya L659–680. Market kapama yanıtından sonra dolan miktar/status doğrulanmadan yerel pozisyon siliniyor; kayda `pnl_gross`, `fees`, `pnl_net` sıfır yazılıyor. Bu kod yolu yanlış raporlama ve kısmi dolumda pozisyon kaybı riski taşır; tamamının başka yerde telafi edildiği gösterilmedi.
- **Karar:** Bu yürütme kodu yeni PAPER çekirdeğine aktarılmaz. Gelecekte dolum-sadece muhasebe, pending/idempotency, iki taraflı mutabakat ve crash/timeout/partial-fill testleri zorunludur.

## K4 — Bilinmeyen funding sıfıra dönüşebiliyor
- **Kaynak:** `file_185_bot.py` L319–336 ve L1486–1490: Binance ve Gate parser'ı eksik `rate` alanını `0.0` yapıyor; parse sonucu sözlük olduğundan sonraki `if not f` kontrolü bunu UNKNOWN saymayabilir. Yakın-settlement kapısı yine ayrı olarak çalışabilir.
- **Doğrulama:** Yalnız `parse_funding` AST'si izole edilerek, zaman alanı mevcut ama rate eksik iki sözlükle yerel denendi: her ikisi de rate `0.0` döndürdü. Ağ kullanılmadı.
- **Kaynak:** `file_147_unified_engine.py` L66–87: funding helper `None` değerini 0'a çeviriyor ve NaN için finiteness kontrolü yok. İzole helper deneyinde yakın uzlaşma zamanında `None` ve NaN için `allowed=True` gözlendi. Bu, başka üst katmanların bütün senaryolarda engellemediğini **kanıtlamaz**; helper'ın tek başına fail-closed olmadığını gösterir.
- **Yeni tasarım:** `market_safety.funding_gate` eksik/NaN/sonsuz/bayat/gelecekten gelen gözlemi reddeder ve `0` ile bilinmeyeni ayırır. **Bu yardımcı henüz çevrimdışı simülatörün işlem kararına bağlı değil; simülatör funding'i modellemiyor.**

## K5 — Defter sağlığı ve operasyon durumunu birbirine karıştırma
- **Kaynak:** `file_146_state_store.py` L414–432 PENDING niyetlerini strict doğrulamada hata olarak ele alıyor. L641–654 mevcut finansal durum için recovery kilidi politikasını anlatıyor. `file_148_v9.4.2_test_raporu.md` §3 canlıdaki bir 503 ile ayrı bir sentetik PENDING deneyini tartışıyor; `file_150_v943_final_report.md` canlıda IN_FLIGHT anı yakalanmadığını belirtiyor.
- **Yorum:** Sağlıklı akış ≠ mutabakatlı defter; process-owned kısa süreli PENDING ≠ tamamlanmış işlem. Eski rapor olası nedeni gösteriyor, canlı olaydaki PENDING nedenini kesin ispatlamıyor.
- **Yeni tasarım:** Giriş kilidi, strict recovery, anlık sağlık, veri tazeliği ve PENDING yaşı ayrı durumlar olacak; v0.3'ün SQLite rapor kaydı bu işlem defteri değildir.

## K6 — Kaynaklar eksik; sürümleri karıştırıp doğrudan çalıştırmak güvenilir değil
- **Kaynak:** `file_147_unified_engine.py` L26–44 ve L432/L1275; `file_151_v94_core.py` L8; `file_146_state_store.py` L411. Örneğin `adaptive_policy`, `health_reporting`, `scanner.*`, `quant_rule_council`, `ten_agent_debate`, `flow_exit_manager` gibi import adları düzleştirilmiş arşivde bağımsız aynı adlı modül olarak tespit edilmedi. İsim eşleşmesi yokluğu dosyanın hiçbir gömülü metinde veya dış bağımlılıkta bulunamayacağını kanıtlamaz.
- **Kanıt:** Dosya AST ve import/isim envanteri. Bu grup bağımlılıkları tamamlanarak çalıştırılmadı. Sürümler arasında aynı adlı modüllerin AST'leri farklı; `SURUM_AST_FARKLARI.md`.
- **Karar:** Eski rapordaki geçen test sayıları mevcut arşivin yeniden kurulup geçtiğini kanıtlamaz; bağımlılıkları uydurmamak ve geçmiş kanıtla yeni testi ayrı tutmak gerekir.

## K7 — Kanıt ile getiri iddiaları
- **Kaynak:** `file_149_v941_nihai_detayli_rapor.md` §1 ve §5, geçmiş denemesinde 378 işlemde negatif net ve stres kollarında da negatif sonuç rapor ediyor. Bu rakamlar arşiv yazarının kaydıdır; veri ve deney bu incelemede yeniden çalıştırılmadı. Aynı belgenin kendisi gerçek para onayını reddediyor.
- **Karar:** Daha çok gösterge, daha çok oylama veya başka bir sürümden fonksiyon almak kârlılık kanıtı değildir. Önceden dondurulmuş maliyetli walk-forward, eş zamanlı ortak-kasa testleri ve ileriye dönük gözlem gerekir.

## K8 — Üst zaman diliminin sınırları
- **Kaynak:** `file_151_v94_core.py` L23–40 UTC kovası, tam aralık ve kapanış zamanını denetlemeye çalışır. Önceki yeni prototipin ilk halinde gruplar CSV başından başlıyordu ve takvim hizalı değildi; bu kapsamlı incelemede düzeltildi.
- **Yeni tasarım:** `closed_htf_closes` yalnız epoch-katlı tam, kesintisiz kovanın kapanışını alır; baştaki/sondaki eksik kova atılır. Eksenin borsaya özgü takvimle birebir uyumunu iddia etmez. Üç yeni birim testi var.

## K9 — Artımlı emir defteri için sıra geçerliliği
- **Kaynak:** `file_85_market_data.py` L40–85 snapshot ve `prevSeqId` sıralamasıyla artımlı defter tutar. Ek borsa checksum kuralları ve yeniden bağlanma davranışı farklı bölümlerde ayrıca araştırılmalıdır; yalnız bu sınıfa bakmak uçtan uca güvence değildir.
- **Yeni tasarım:** bağımsız `SequenceBook` örneği atomik güncelleme, geçersiz/crossed book ve sıra boşluğunda snapshot gereğini test eder. **Bu sınıf canlı akışa bağlı değildir; OKX/Binance protokol uyumluluğu iddia edilmez.**

## K10 — Metin uzantısı içindeki HTML ve veri güvenliği
- `.txt` uzantılı dört dosya aslında HTML içeriyor: `file_165`, `file_166`, `file_173`, `file_174`; bunlar HTML olarak da indekslendi. `file_153` büyük bir kaydedilmiş Arena sayfası; içerdiği potansiyel kişisel görüşmeler yeniden dağıtılmadı.
- Tüm 191 dosyada 166.526 satırın otomatik desen taraması, 109 Python dosyasında AST çözümlemesi ve HTML'de yapısal tarama yapıldı. Bu, her satır için insan düzeyinde semantik güvenlik denetimi, her JS fonksiyonunun çalıştırılması veya resmi doğrulama değildir.

## K11 — HTML ve NOVA belgelerinde strateji açıklaması tutarsızlığı
- `file_6_acarbot-system final.html` L2112–2140 10 oylu confluence içinde MACD kesişimi (olay) kullanıyor. `file_184_yetenek.py` L195–231 de MACD kesişimini kullanıyor. Ancak `file_188_MIMARI.md` §5, bu oyun çizginin sinyal ve sıfırın uygun tarafında olması biçiminde değiştirildiğini anlatıyor. Aynı ZIP'teki kod ile bu belge açıklaması arasında fark var; belgenin hangi ara sürümü anlattığı doğrulanmadı.
- Karar: Kod/belge ve sürüm tarihlerine bakılmadan "aynı özellik" veya "birebir parite" kabul edilmemeli. EMA ısınması, eksik değerler, zaman hizası ve tüm oylar için ayrı HTML↔Python testleri gerekir. Yeni prototipin 4 oylu stratejisi bu 10 oylu stratejinin birebir portu değildir.

## K12 — HTML hacim ve funding varsayımları
- `file_6_acarbot-system final.html` L2158–2166, hacim/ortalama veri alanları yoksa kontrolü `true` döndürebiliyor. Çağıranın ek bir veri kapısı olup olmadığı ayrıca incelenmelidir; helper tek başına fail-closed değildir.
- Aynı dosya L2582–2600, funding sayısal değilse varsayılan konfigürasyon oranını ve fiyat yoksa giriş fiyatını kullanır; bu, gözlenmiş gerçek funding veya settlement fiyatı ile aynı şey değildir. L2588 sekiz saat varsayımını gösterir. Gerçek ürün sözleşmesi ve geçmiş veri buna uygun değilse simülasyon sapabilir.
- `file_6` L5572–5595 çok sayıda strateji/parametre kombinasyonu için grid üretiyor. Aynı veride çok deneme yapıp en iyisini seçmek örneklem-dışı kanıt değildir; bağımsız zaman bloğu ve çoklu-deneme düzeltmesi gerekir.

## K13 — NOVA mum denetiminde sıralama ve boşluk toleransı
- `file_184_yetenek.py` L307–330 önce barları sıralıyor, `d <= max_gap_ms` koşuluyla sıfır farkı da geçebiliyor; tek eksik mum toleransı amaçlı. Üç mumlu yinelenen zaman örneğiyle yalnız fonksiyon izole edilerek denendi ve `(True, "")` döndürdü. Bu, fonksiyon düzeyindeki bulgudur: tüm giriş noktalarının ayrıca aynı veriyi reddetmediği kanıtlanmış değildir.
- Yeni çevrimdışı çekirdekte veri yükleyici sırası bozuk, eşit zamanlı veya herhangi bir eksik mumda tüm seriyi reddeder. Bu daha sıkı bir tercih olup iki uygulamanın birebir eşdeğer olduğu iddiası değildir.
