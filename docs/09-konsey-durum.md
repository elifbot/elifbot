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
| 3 | REJIM_DONUS teyidi (çok parçalı) | koşuyor | sonuç bekleniyor |

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

1. REJIM_DONUS teyit yaması çıkarsa A/B ile ölç, etkili ise uygula.
2. Etkisiz yamayı geri al (RVOL filtresi) — ölçülen fayda yok, ek karmaşıklık var.
3. Gerçek borsa verisiyle koşu: ağ erişimi olan bir ortamda `--dakika 60 --sembol 120`.
4. Kenar bulunana kadar canlıya çıkmak yok.
