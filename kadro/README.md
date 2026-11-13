# ACARBOT · AI Kadro

Bu klasör, botu geliştiren **yapay zekâ ekibinin** sözleşmesidir. Her ajan bir rol, her rol
bir çıktı ve bir **kapı (gate)** taşır. Amaç "çok ajan olsun" değil; her değişikliğin ölçülmüş
bir kanıtla gelmesi.

## Nasıl çalışır

1. Görev `ROUTING.md` ile bir ajana atanır.
2. Ajan, `skills/` altındaki ilgili beceri dosyasındaki adımları **sırayla** uygular.
3. Çıktı üretir: kod + test + ölçüm + gerekçe.
4. **Risk Subayı** ve **Kod İnceleyici** onaylamadan `main`'e giremez.
5. Her PR, `CALISMA-KURALLARI.md` içindeki "kanıt zorunluluğu"nu sağlar.

## Ajanlar (14)

| # | Ajan | Tek cümlelik görevi | Veto hakkı |
|---|------|--------------------|-----------|
| 0 | [Baş Denetçi](agents/00-bas-denetci.md) | Görevi böler, ajanları yönlendirir, kapıları tutar | ✅ |
| 1 | [Quant Araştırmacı](agents/01-quant-arastirmaci.md) | Sinyal fikrini ölçülebilir hipoteze çevirir | — |
| 2 | [Veri Mühendisi](agents/02-veri-muhendisi.md) | Tick arşivi, kalite, tekrar üretilebilirlik | ✅ |
| 3 | [Backtest Mühendisi](agents/03-backtest-muhendisi.md) | Walk-forward, komisyon/kayma/funding dahil ölçüm | ✅ |
| 4 | [Risk Subayı](agents/04-risk-subayi.md) | 1000/50/10x/−10$ kuralının bekçisi | ✅ |
| 5 | [İcra Mühendisi](agents/05-icra-muhendisi.md) | Emir yaşam döngüsü, kayma, idempotency | ✅ |
| 6 | [Borsa Entegratörü](agents/06-borsa-entegrator.md) | Binance/OKX adaptörleri, CROSS, ctVal | ✅ |
| 7 | [ML Mühendisi](agents/07-ml-muhendisi.md) | Özellik/rejim modelleri, overfit nöbetçisi | — |
| 8 | [Güvenlik](agents/08-guvenlik.md) | Anahtar, sır, izin, kaçak sızıntı | ✅ |
| 9 | [DevOps](agents/09-devops.md) | CI, gözlemlenebilirlik, runbook | — |
| 10 | [Kod İnceleyici](agents/10-kod-inceleyici.md) | Doğruluk, okunabilirlik, sınır durumları | ✅ |
| 11 | [Test Mühendisi](agents/11-test-muhendisi.md) | Kural kilitleri, regresyon, kaos | — |
| 12 | [Uyum/Hukuk](agents/12-uyum-hukuk.md) | Borsa ToS, TR mevzuatı, risk bildirimi | ✅ |
| 13 | [Ürün Sahibi](agents/13-urun-sahibi.md) | Kabul kriterleri, kapsam, öncelik | — |
| 14 | [Ölçüm Analisti](agents/14-olcum-analisti.md) | WR/PF/başabaş WR/maksDD, atıf | ✅ |

## Beceriler (10)

`skills/` altında, adım adım yapılacaklar: walk-forward, tick replay, emir yaşam döngüsü,
stop doğrulama, marjin fiziği, veri kalitesi, sinyal kıyaslama, canlıya alma kapısı,
olay müdahale, raporlama.

## Değişmez ilkeler

1. **Kural kutsaldır:** 1.000 $ kasa · 50 $ teminat · 10x · CROSS · pozisyon limiti yok · −10 $ stop.
   Bu sayıları değiştiren PR, gerekçesi ne olursa olsun reddedilir.
2. **Ölçülmeyen iyileştirme yoktur.** "Daha iyi olur" cümlesi kanıt değildir.
3. **Simülatör borsadan iyimser olamaz.** Teminat reddi, kayma, komisyon, funding modellenir.
4. **Tek doğruluk kaynağı testlerdir.** Kural testi kırılırsa iş durur.
5. **Canlı para varsayılan olarak kapalıdır.**
