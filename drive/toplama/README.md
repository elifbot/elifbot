# Drive `toplama` arşivleri — açılmış içerik

Drive'daki **4 `toplama` zip'i** (250 MB) indirildi, açıldı ve içindeki **kaynak kod +
doküman + konfig** buraya alındı. İkili dosyalar (zip, pdf, png, exe, .db) ve 300 KB üstü
dosyalar repoya konmadı — Drive'da duruyor, listesi `excluded.csv`'de.

## Ne var

| Klasör | Dosya | Boyut | Kaynak |
|---|---|---|---|
| `arsiv-1/` | 348 | 2.3 MB | `toplama 1.zip` — v9.4.5 / v9.5.2 / v9.5.3 arşivleri + patch'ler |
| `arsiv-2/` | 970 | 19.0 MB | `toplama 2.zip` — V10 denemeleri, omnistudio, paneller, analizler |
| `arsiv-3/` | — | — | `toplama 3.zip` — **2'nin üst kümesi**, içerik tekrarı olduğu için boş |
| `arsiv-4/` | 1096 | 10.5 MB | `toplama 4.zip` — sürüm arşivleri, test kanıtları, mimari notlar |
| **Toplam** | **2.414** | **31.9 MB** | |

İç içe zip'ler de açıldı: `..._<zipadı>__ic/` klasörleri, bir zip'in içinden çıkan kod.

## Tekilleştirme

Aynı içerik (sha256) birden fazla arşivde varsa **bir kez** yazıldı; ilk görüldüğü arşive.
`excluded.csv` her dosya için neden yazıyor: `kopya`, `>300 KB`, `ikili/arşiv`.

## Neden hepsi yok

- 108 tekil iç zip (92 MB) ve 22 PDF (6.5 MB) repoya girmedi — GitHub 100 MB dosya sınırı
  ve depo şişmesi.
- `GeminiSetup.exe` (12.7 MB), `.db` dosyaları, `.indir` (tarayıcı kaydı) alınmadı.
- İç zip'lerden 25 MB'lık tavana kadar alındı; tavan sonrası kalan içerik Drive'da.

## Bunlar ne işe yarar

Sürüm geçmişi: hangi motorun hangi sürümde nasıl değiştiği. Özellikle
`arsiv-1` altındaki patch'ler ve `arsiv-4`'teki test kanıtları, bugünkü yamaların
(`yamalar/`) kaynağını anlamak için. **Bu dosyaların hiçbiri gerçek piyasa tick verisi
değildir** — backtest için kullanılamaz.

## Sır temizliği

Arşivlerde **gerçek API anahtarları** vardı (Google AI Studio). Push koruması yakaladı;
17 anahtar maskelendi, kod korundu. Ayrıntı ve yapılması gerekenler: [`GIZLILIK.md`](../../GIZLILIK.md).

## Doğrulama

```bash
sha256sum -c drive/MANIFEST/sha256.txt   # orijinal 4 zip
```
