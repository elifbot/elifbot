# Konsey durumu — 2026-11-13 gece raporu

Bu dosya, gece boyunca süren konsey çalışmasının **ölçülmüş** durumunu kaydeder.
Kural: ölçülmeyen hiçbir şey "iyileşme" diye sunulmaz.

## 1. Değişmez kurallar (konsey bunları değiştiremez)

| Kural | Değer |
|---|---|
| Kasa | 1.000 $ |
| Giriş | 50 $ teminat × 10x = 500 $ notional |
| Pozisyon | sınırsız, CROSS teminat |
| Stop | pozisyon başına net −10 $ |
| Evren | tüm Binance + OKX vadeli pariteleri |

Kod tarafında `tartisma.KURAL_IHLALI` deseni bu sayıları değiştirmeye çalışan
kararları otomatik olarak `dusen` listesine atar.

## 2. Konsey nasıl çalışıyor

6 rol × 3 tur: `mimar, risk_subayi, icra, test, olcum, ops` → öneri → itiraz → sekreter.

```
python3 -m kadro.konsey.calistir --gorev "..." --saglayici nvidia --butce 24 --tur 3
```

- Roller **paralel** (3 eşzamanlı) çalışır; model yavaş olduğu için süre kritik.
- Her karar `(dosya, eski_kod, yeni_kod)` üçlüsüne çevrilir, sonra `yama.py` doğrular:
  1. dosya gerçekten repoda mı,
  2. `eski_kod` dosyada **tam 1 kez** geçiyor mu,
  3. yama sonrası `ast.parse` geçiyor mu.
- Doğrulamadan geçmeyen karar `kararlar.json → dusen` altına **nedeniyle** yazılır.
- Doğrulanan yama `yama.diff` olarak çıkar; **yalnızca** bunlar uygulanabilir.

## 3. Model durumu (ölçülmüş)

| Sağlayıcı | Sonuç |
|---|---|
| NVIDIA | 83 model tarandı; **yalnızca `google/gemma-4-31b-it`** yanıt verdi |
| GitHub Models | katalog boş, uç 4 bayt `"OK\r\n"` döndürüyor — kullanılamaz |
| gemma-4-31b-it | yanıt süresi 16–290 sn; **kararsız** (bazı çağrılar 300 sn'de zaman aşımı) |

Kalıcı ders: model kimliği koda gömülmez (NVIDIA 410 EOL), `/models` keşfi şart,
ama keşif de tek başına yetmez (404 = hesaba açık değil).

## 4. Konseyin ürettiği yamalar ve ÖLÇÜLEN etkileri

| # | Yama | Durum | Ölçüm |
|---|---|---|---|
| 1 | `sinyaller.komite()` RVOL filtresi (`hacim_orani < 1.5` → giriş yok) | uygulandı | **ETKİ SIFIR** — A/B (5 dk/60 sembol) tüm metrikler birebir aynı |
| 2 | `Poz`'a `regime_flip_count` alanı | reddedildi | alanı kullanan mantık yok → eksik yama |
| 3 | REJIM_DONUS teyidi (çok parçalı) | üretilemedi | sekreter şemayı tutturamadı (dosya alanı boş) → 3 karar düştü |
| 4 | REJIM_DONUS teyidi, ikinci deneme | üretilemedi | 14 çağrı, 0 karar; sekreter yine `dosya/eski_kod` doldurmadı |

Ölçüm aracı: `python3 -m kadro.konsey.olcum --kararlar konsey/<etiket>/kararlar.json`
Geçici kopyada yamasız/yamalı iki koşu yapar, aynı seed, farkı raporlar.

## 5. Churn teşhisi (asıl problem)

`bot/v9/motor.py:140-144`: pozisyon açıldıktan `rejim_karsi_cikis_sn = 120` sn sonra
rejim ters dönerse ve PnL negatifse pozisyon **anında** kapatılıyor.

Sonuç: 44 işlemin **36'sı** REJIM_DONUS ile kapanıyor, ortalama kayıp −2.02 $,
her işlem 0.50 $ komisyon ödüyor (toplam 24.66 $). WR %15.9, PF 0.676.
Bu bir "kenar" değil, **komisyon öğütme** deseni. Düzeltme yönü: ters rejim
N ardışık tick sürmeli (teyit) veya ek PnL eşiği aranmalı.

## 6. Dürüstlük notu

- Koşular **SENTETİK** veriyle yapıldı (CI'da borsa ağı kapalı). Bu bir **davranış**
  ölçümüdür, **kenar** ölçümü değildir. Gerçek kenar ancak gerçek borsa verisiyle ölçülür.
- WR tek başına anlamsızdır; PF, başabaş WR ve maksDD ile birlikte okunmalıdır.
- Konsey "en iyiyi buldu" demiyoruz: bir yama **ölçüldü ve sıfır çıktı**, bu da sonuçtur.

## 7. Sıradaki adımlar

1. **RVOL filtresi geri alındı** (ölçülen fayda sıfır, ek karmaşıklık).
2. Sekreterin şema disiplini: `dosya` boş geldiğinde `kanit` alanından dosyayı çıkar;
   ikinci aşama onarım çağrısına *dosya seçimini* de bırak. Bu, kalan tek darboğaz.
3. Model yükseltmesi: gemma-4-31b-it 250–290 sn/çağrı ve kararsız; 3 oturumun 2'si
   zaman aşımıyla kararsız kaldı. Daha hızlı bir model (veya ikinci sağlayıcı) şart.
4. Gerçek borsa verisiyle koşu: ağ erişimi olan bir ortamda `--dakika 60 --sembol 120`.
5. Kenar bulunana kadar canlıya çıkmak yok.

## 8. Gece 2. yarı — şema savaşı (ölçülmüş kayıt)

Konsey konuşuyor ama **uygulanabilir yama** üretmekte zorlanıyor. Nedeni modelin
şema disiplini; her turda yeni bir biçim geldi ve her biri koda bağlandı:

| Oturum | Çağrı | Karar | Ne oldu | Yapılan düzeltme |
|---|---|---|---|---|
| `20261113-215441` | 7 | 0 | `eski_kod` uyduruldu (dosya içeriği verilmemişti) | dosya kaynağıyla onarım çağrısı |
| `20261113-220516` | 14 | **1** | RVOL yaması çıktı | (A/B: etki sıfır → geri alındı) |
| `20261113-223147` | 8 | 0 | sekreter zaman aşımı | sekretere 2 deneme, küçük istem |
| `20261113-233015` | 14 | 0 | `dosya` alanı boş | `kanit` metninden dosya çıkarma |
| `20261114-002804` | 14 | 0 | şema farklı: `uygulanabilir_yama/hedef/kod` | alternatif şema uyarlayıcı |
| `20261114-004954` | 14 | 0 | şema bir kat iç içe: `karar.degisiklikler` | iç içe sarmalayıcı çözümü |
| `20261114-011339` | 8 | 0 | model 300 sn zaman aşımı (4 çağrı düştü) | — (model sorunu) |

**Kritik bulgu:** son iki oturumda model **doğru içeriği** üretti
(`ters_rejim_sayaci` sayacı, `_izle` içinde güncelleme, kapatma koşulu) ama bizim
şemamızla değil. İçerik doğru, kılıf yanlış. Bu, modelin anlamadığı değil,
**formatı tutturamadığı** anlamına gelir; şema uyarlayıcı bu yüzden yazıldı.

**Kalan tek darboğaz:** `google/gemma-4-31b-it` saat ilerledikçe yavaşlıyor
(16 sn → 250-290 sn → 300 sn zaman aşımı). Ücretsiz kota tükeniyor olabilir.
Daha hızlı bir model/anahtar olmadan konsey turları tamamlanmıyor.
