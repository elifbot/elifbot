# 08 · v9 ORTAK AKIL ve Konsey

## 1. v9 nedir

v8'in borsa fiziği (SimuleBorsa, boyut_hesapla, KasaKurallari) üstüne üç katman:

| Katman | Dosya | Ne yapar |
|---|---|---|
| Rejim | `bot/v9/rejim.py` | Piyasayı trend / sıkışma / dağılma diye sınıflar; sinyalleri kapılar |
| Sinyal | `bot/v9/sinyaller.py` | 4 dedektör + oy birliği; çelişki varsa işlem yok |
| Portföy | `bot/v9/motor.py` | Adayları skora dizer, teminat bitene kadar en iyileri girer |

Değişmez kural aynen korunur: 1.000 $ · 50 $ · 10x · CROSS · limitsiz · −10 $.

### Rejim eşiği neden göreli

İlk sürümde eşik mutlaktı (`oynaklik < 0.0015`). 0.5 sn'lik bucket'ta tek tick getirisi
~0.00002 olduğu için **78.516 tick'in 78.516'sı** "sıkışma" çıktı; 4 dedektörden 2'si hiç
konuşmadı. Yeni sürüm eşiği sembolün **kendi oynaklık medyanına** göre ölçüyor
(`oynaklik < 0.70 × medyan`), böylece veri sıklığından bağımsız.

### İki muhasebe hatası (v8'de de vardı)

1. **Çift komisyon:** kapanışta komisyon hem `emir_gonder` içinde hem `_pozisyon_kapat`
   içinde düşülüyordu. Düzeltildi (`bot/v8/broker.py`).
2. **Yanlış net:** v9 net'i "global realize farkı" ile yazıyordu; eşzamanlı pozisyonlarda
   birbirinin kâr/zararını yazıyordu (−2 $'lık hareket −14 $ görünüyordu). Artık her işlem
   kendi fiyatından ve iki komisyondan hesaplanıyor. Ölçüm: ortalama sapma **0.007 $**.

## 2. 20 dakikalık smoke (60 sembol, sentetik)

| Metrik | v9.1 (düzeltilmiş) |
|---|---|
| Kapanan | 44 |
| WR / PF | 15.9 % / 0.68 |
| En kötü işlem | **−6.02 $** (bütçe −10 $) |
| Teminat / hesap kaldıracı | 547 $ / 5.46x |
| Tasfiye | 0 |
| Muhasebe sapması | 0.007 $ |

**Dürüst okuma:** sinyal seti bu veride komisyondan sonra negatif. 44 işlemde 24.66 $
komisyon ödendi; 36 çıkış "rejim dönüşü" ile küçük zararla kapatıldı. Bu bir "kötü bot"
hükmü değil — **kenar ölçülmedi**, çünkü veri sentetik. Konseyin ilk işi bu churn'ü azaltmak.

## 3. Havuz

| | |
|---|---|
| Kaynak | `drive/toplama` (2.414 dosya) + `bot`, `docs`, `kadro`, `panel`, `yamalar` |
| İndeks | `havuz/indeks.jsonl` — 2.494 dosya, 31.8 MB, 726.747 satır, 10 etiket |
| Demetler | `havuz/digest/*.md` — 6 konu, her biri ~22.000 karakter (~6.3K token) |
| Kaynak izi | Her kanıt parçası `dosya:satır` ile işaretli |

Neden 22 KB: GitHub Models **8.000 girdi token** sınırı koyuyor. 32 MB'lık arşiv modele
verilemez; havuz, kaybetmeden süzüyor. Süzgeç `log(1+n)` ile ölçeklenir — 5.000 kez "stop"
geçen bir JSON, 40 kez geçen tasarım notunu ezmez.

## 4. Konsey

```
havuz/digest  →  Tur 1: 6 rol öneri  →  Tur 2: çapraz itiraz  →  Tur 3: sekreter/oy
                                                                        ↓
                                                        karar.md + yama.diff + oturum.json
```

| Bileşen | Dosya |
|---|---|
| Sağlayıcı (GitHub Models / NVIDIA NIM / Ollama) | `kadro/konsey/saglayici.py` |
| 6 rol, 3 tur istemleri | `kadro/konsey/roller.py` |
| Orkestrasyon + kural vetosu | `kadro/konsey/tartisma.py` |
| Çıktı | `kadro/konsey/cikti.py` |
| CLI | `python3 -m kadro.konsey.calistir` |
| CI | `.github/workflows/konsey.yml` (workflow_dispatch) |

**Kural vetosu kodla:** teminat/kaldıraç/stop/kasa sayılarını değiştiren karar, model ne
derse desin `dusen` listesine atılır (`KURAL_IHLALI` deseni + test).

### Neden GitHub Actions

Bu geliştirme ortamı model uç noktalarına çıkamıyor (NVIDIA/OpenAI/Anthropic/Ollama = HTTP 000).
Actions runner'ının interneti var; ayrıca GitHub Models `GITHUB_TOKEN` + `permissions: models: read`
ile **anahtarsız** çalışıyor. NVIDIA anahtarı varsa ikinci görüş olarak ekleniyor.

### Sır hijyeni

- Anahtar yalnızca ortamdan (`NVIDIA_API_KEY`) okunur, repoya yazılmaz.
- `bot/tools/sir_tara.py` CI'da kapı: bulgu varsa build kırmızı.
- Bu turda arşivde **2 gerçek NVIDIA anahtarı** bulundu ve maskelendi; anahtar sahibi
  iptal edip yenilemeli.
