# ACARBOT — KULLANIM KILAVUZU (v5.5)

**Önemli:** Bu bot **kârlılığı kanıtlanmış bir sistem değildir.**
5m ve 15m'de giriş kenarı istatistiksel olarak elendi; 1h'de ölçülemedi.
Gerçek para ile çalıştırılması önerilmez.

---

## 1. ARAÇ HARİTASI

| Araç | Ne yapar |
|---|---|
| `tools.entry_edge` | Giriş kenarı testi (bağımsız tarama + küme istatistiği) |
| `tools.exit_geometry` | Çıkış geometrisi karşılaştırması |
| `tools.validate_strategy` | 90 günlük backtest + walk-forward + Monte Carlo |
| `tools.gate_attribution` | Hangi kapı ne kadar engelledi |
| `tools.ablate_gates` | Kapıları tek tek kapatıp etkisini ölçer |
| `tools.measure_costs` | Gerçek spread/kayma ölçümü |
| `tools.make_reference` | Regresyon referansı üretir |
| `tools.package_release` | Tutarlılık kapısı + ZIP |

---

## 2. GİRİŞ KENARI TESTİ (v5.5'in ana aracı)

```bash
python3 -m tools.entry_edge --exchange okx --days 90 \
    --resample-minutes 60 \
    --costs docs/maliyet_olcum_v5.2.json \
    --permutations 500 --bootstrap 3000 --tests-m 15 \
    --out docs/kenar_1h.json
```

### Bayraklar

| Bayrak | Varsayılan | Anlamı |
|---|---|---|
| `--resample-minutes` | 5 | 5m önbellekten 15m/1h üretir |
| `--legacy-probe` | kapalı | ESKİ bulaşık evren (yalnız karşılaştırma) |
| `--cluster-bars` | 12 | Aynı sembolde kümeleme penceresi |
| `--min-n` | 300 | Kenar iddiası için asgari bağımsız örneklem |
| `--tests-m` | 15 | Bonferroni için toplam hipotez sayısı |
| `--bootstrap` | 2000 | Gün küme bootstrap tekrar sayısı |

### Çıktıyı okuma

```
summary.simetrik_1R_brut   → MALİYET DÜŞÜLMEMİŞ
summary.simetrik_1R_net    → maliyet düşülmüş + küme GA
summary.kumeleme           → kaç aday tekilleşti
summary.stoplu_ufuklar     → 1R stop uygulanmış (GERÇEKÇİ olan)
summary.ufuklar            → stopsuz (yalnız yön teşhisi)
summary.saglam_hukum       → dört durumlu hüküm
verdict                    → nihai karar
```

**Hangi sütuna bakılır?** Karar için **`stoplu_ufuklar`** ve
**`simetrik_1R_net`**. Stopsuz ufuk yanıltıcıdır — 15m'de 48 bar
stopsuz +0,106R, stoplu **−0,111R**.

### Hükümler

| Hüküm | Anlamı | Ne yapmalı |
|---|---|---|
| `GIRIS_KENARI_VAR` | GA alt >0, n≥300, düzeltilmiş p<0,05 | Çıkış tasarımı başlanabilir |
| `GIRIS_KENARI_YOK` | GA üst ≤0, n≥300 | Sinyal yeniden tasarlanmalı |
| `YETERSIZ_ORNEKLEM` | n<300 | **Örneklem büyüt** — "kenar yok" DEME |
| `BELIRSIZ` | GA sıfırı kapsıyor, n yeterli | Daha fazla veri veya daha güçlü sinyal |

---

## 3. BACKTEST

```bash
python3 -m tools.validate_strategy --exchange okx --days 90 \
    --fine-mode targeted --fine-passes 2 --fine-max-requests 900 \
    --windows 6 --profile apex --balance 1000 \
    --costs docs/maliyet_olcum_v5.2.json \
    --data-dir data/validation \
    --out docs/dogrulama.json
```

### Drawdown tepe penceresi (yeni)

```bash
--drawdown-peak-mode rolling --drawdown-peak-days 7
```

| Mod | Davranış |
|---|---|
| `all_time` | Tepe hiç sıfırlanmaz (v5.4 davranışı). İlk büyük DD ölçekleyiciyi dönem sonuna kadar kilitler. |
| `rolling` | Son N günün tepesi. Kilit dönemsel çözülür. |
| `daily` | Her UTC günü sıfırlanır. |

Rapor `drawdown_peak` alanında sıfırlama anlarını ve
`taban_alti_red` sayısını verir.

---

## 4. KAPSAM SINIRLARI — BİLİNMESİ GEREKENLER

Bunlar **eksiklik**tir, özellik değil:

1. **Funding backtest'e dahil DEĞİL.** `validate_strategy` funding
   iletmiyor. Net PnL bu yüzden eksik.
2. **Evren 6 majör.** Canlı tarama mikro altları da kapsıyor; orada
   maliyet ölçülmedi.
3. **90 gün tek rejim.** Boğa/ayı/çöküş çeşitliliği yok.
4. **15m/1h, 5m'den toplandı.** Bağımsız borsa verisiyle doğrulanmadı.
5. **En ince yol 1m.** 45 sn TTL tam çözülemiyor; dolum üst sınır.
6. **Testnet koşulmadı.** Emir akışı gerçek ortamda kanıtlanmadı.
7. **Binance maliyeti VARSAYIM**, ölçülmedi.
8. **Kısmi çıkış yok.** TP1'de tam çıkış modelleniyor.

---

## 5. RİSK AYARLARI

`core/config.py` → `PortfolioConfig`:

| Parametre | Varsayılan | Not |
|---|---|---|
| `max_positions` | 6 | `0` = sınırsız — **Faz 3'e kadar değiştirmeyin** |
| `total_open_risk_cap` | 150 USDT | Σ pozisyon başı net risk |
| `daily_soft_loss` | 100 USDT | Yeni giriş durur |
| `daily_hard_loss` | 150 USDT | Kill switch, hepsi kapatılır |
| `portfolio_drawdown_pct` | %8 | Güvenli mod eşiği |
| `drawdown_peak_mode` | `all_time` | v5.5 yeni |

**Uyarı:** `max_positions=0` yapmak, portföy tavanları sıkılaşmadan
**riski sınırsızlaştırır**. Likidasyon mesafesi, haftalık/aylık zarar
denetimi ve stres testi (Faz 3) bitmeden açılmamalı.

**25 USDT garantisi yoktur.** Planlanan risk 25 USDT'dir; boşluk, ani
hareket veya borsa kesintisinde gerçekleşen zarar bunu **aşabilir**.
Borsada koruyucu stop bu yüzden zorunludur.

---

## 6. SIK YAPILAN HATALAR

| Hata | Doğrusu |
|---|---|
| Stopsuz ufka bakıp "kenar var" demek | Stop'lu sütuna bak |
| 15 hipotezden birinin p<0,05'ini kanıt saymak | Bonferroni uygula |
| n=67 ile "kenar yok" demek | `YETERSIZ_ORNEKLEM` — örneklem büyüt |
| Brüt beklentiyi net sanmak | `simetrik_1R_net` kullan |
| `all_time` DD ile "90 günlük örneklem" demek | Kilit sayısını kontrol et |
| Backtest sonucunu canlı performans saymak | Ayrı şeyler; testnet gerekir |

---

## 7. MEVCUT HÜKÜM

**Gerçek para YASAK.** Pozisyon başına azami kayıp **2,5–5 USDT**.

Sıradaki iş: `V6_GELISTIRME_PLANI.md` Faz 1 — örneklem altyapısı.
