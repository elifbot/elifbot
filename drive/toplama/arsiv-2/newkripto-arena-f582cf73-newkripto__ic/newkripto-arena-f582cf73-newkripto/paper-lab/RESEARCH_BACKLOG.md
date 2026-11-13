# Paper Lab — Araştırma Backlog'u

Bu liste karar değil, sıradaki ölçüm hipotezleridir. Her maddede önce veri toplanır;
tek run sonucu doğrudan canlı kural veya parametre değişikliği yapılmaz.

## P0 — Önce ölçüm bütünlüğü

- [x] Üçüncü 1.000 USDT run'ının nihai artifact, closeout ve Shadow raporunu doğrula.
- [ ] Her run'da giriş/kapanış UUID, gerçekleşen miktar, giriş/çıkış ücreti, funding,
      MFE/MAE, stop ve çıkış nedenini aynı kayıt üzerinde mutabık tut.
- [ ] Erken iptal/checkpoint dosyasını nihai closeout'tan açıkça ayır.
- [ ] Binance ve OKX'in hem katalog hem OHLCV/ticker/funding/OI kanıtını sakla.

## P1 — Giriş kalitesi

- [ ] **Data Readiness:** minimum trade sayısı, akış kapsama süresi ve defter yaşı
      sağlanmadan güçlü akış skorunu giriş kanıtı sayma; Shadow'da retlerin baseline
      sonuçlarını ölç.
- [ ] **Teknik + akış uyumu:** aynı yönü destekleyen ve karşıt teknik bileşenleri
      leave-one-out ile karşılaştır; tek bir RSI/MACD/ML skorunu günah keçisi ilan etme.
- [ ] **Maliyet eşiği:** beklenen hareket alanı ile round-trip ücret + kayma + funding
      karşılaştır; brüt küçük kârın net zarara dönüştüğü adayları ayrı raporla.
- [ ] **Rejim ve borsa:** TREND/RANGE/BREAKOUT, LONG/SHORT ve Binance/OKX kırılımlarını
      örtüşen kohortlar olarak sun; satırları toplayıp yapay örneklem büyütme.

## P1 — PDF v2 teknik paketi

- [x] Üç PDF metnini çıkar ve mevcut indikatörlerle karşılaştır; envanteri
      `PDF_INDIKATOR_ANALIZI.md` içinde tut.
- [x] Kapanmış OHLCV ile hesaplanabilen eksik teknik paketi `src/pdf_indicators.py`
      içine ekle; baseline skorunu değiştirme.
- [x] `pdf-confluence` varyantını opt-in Shadow olarak bağla; dört aile uyumu ve
      karşıt aile sayısını karar JSON'una yaz.
- [ ] 120 dakikalık 1.000 USDT v2 run'ında kabul/ret, elenen/kaçırılan kazanan,
      maliyet, PF, median net ve borsa/rejim kırılımını baseline ile karşılaştır.
- [ ] Harici veri gerektiren on-chain, Deribit/DVOL, makro/ETF, sosyal medya,
      ekonomik takvim, token unlock, long/short ratio ve gerçek spoofing/iceberg
      doğrulamasını ancak gerçek kaynak/zaman hizasıyla ele al; şimdilik değer uydurma.
- [ ] JMA/FRAMA/VIDYA/T3 ve HMM/KMeans için tanım, eğitim ve walk-forward/OOS
      protokolünü ayrıca netleştir; PDF listesinde bulunması canlı kural gerekçesi değildir.

## P1 — Çıkış kalitesi

- [ ] Net Exit'i gerçek giriş/çıkış maliyeti ve funding ile baseline'a eşleştirilmiş
      pozisyonlarda karşılaştır.
- [ ] Trailing stopun brüt ≥0 iken net <0 ürettiği işlemleri ayrı ölç; çıkış gecikmesi
      ile giriş kalitesini birbirine karıştırma.
- [ ] MFE/MAE ve kaçırılan kazananları kullanarak erken çıkış/kaçırılan fırsat dengesini
      değerlendir; tek bir büyük kazancın PF'yi şişirmesini kontrol et.

## P2 — Portföy ve güvenlik

- [ ] Aynı yön ve yüksek korelasyonlu pozisyonların toplam marj ve drawdown etkisini
      Portfolio Guard Shadow varyantıyla ölç.
- [ ] Çapraz kurtarma kapalı baseline'ı koru; yeniden test edilirse aynı duplicate-close
      koruması ve iki-bacaklı net mutabakat zorunlu olsun.
- [ ] Flash-crash'ın tek sembolde bütün portföyü kilitleme etkisini, koruma seviyesini
      kaldırmadan ayrı bir risk araştırması olarak incele.
- [ ] WebSocket kopma/yeniden bağlanma ve bayat defter durumlarını giriş kalitesiyle
      ilişkilendir; eksik veriyi sıfır sinyal gibi kullanma.

## Deney tasarımı

- Yeni varyantlar baseline'dan bağımsız sanal kasa ve aynı piyasa/fill bağlamıyla ölçülür.
- Kabul/ret kararı için en az şu alanlar gerekir: korunan/elenen işlem, elenen kazanan,
  kaçırılan kazanan oranı, net fark, median net, PF, max DD, maliyet ve borsa/rejim.
- Yeterli bağımsız örnek ve çoklu piyasa dönemi olmadan “en iyi indikatör”, “zararsız”
  veya “canlıya hazır” sonucu yazılmaz.
- İşlem sayısını artırmak için eşik düşürmek ancak kaçırılan kazanan ve maliyet etkisi
  birlikte raporlanırsa araştırılır.
