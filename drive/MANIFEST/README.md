# Büyük Drive arşivleri — manifest

Drive'da bugün yüklenen **4 büyük arşiv (250 MB)** repoya giremez ve bu ortamdan GitHub
Release'e de yüklenemedi: `uploads.github.com` erişilemez durumda (5 baytlık deneme bile
`EOF` ile düştü). Bu yüzden arşivlerin **doğrulanabilir izi** buraya kondu; ikili dosyalar
Drive'da kalıyor.

| Arşiv | Sıkıştırılmış | Açılmış | Dosya | İçerik |
|---|---|---|---|---|
| `toplama 1.zip` | 47 MB | 78 MB | 10 | v9.4.5 / v9.5.2 / v9.5.3 arşivleri + 3 patch |
| `toplama 2.zip` | 49 MB | 68 MB | 387 | V10 denemeleri, omnistudio, HTML paneller, PDF, ekran görüntüleri |
| `toplama 3.zip` | 96 MB | 145 MB | 396 | sürüm arşivi (en büyük; 2'nin üst kümesi) |
| `toplama 4.zip` | 55 MB | 82 MB | 145 | sürüm arşivleri + 4 sqlite db + png |

Dosyalar:

- `sha256.txt` — dört arşivin hash'i (indirdiğin dosyayla karşılaştır)
- `toplama-<n>-icerik.txt` — arşiv içindeki her dosyanın tam listesi + boyutu
- `ozet.json` — makine okunur özet (boyut, dosya sayısı, uzantı dağılımı)

## Açılmış içerik

Dört arşiv açıldı; içindeki kod/doküman/konfig (`2.414` dosya, `31.9 MB`) repoya alındı:
`drive/toplama/`. İç içe zip'ler de açıldı. İkili dosyalar ve 300 KB üstü içerik Drive'da
kaldı; nedeni `drive/toplama/excluded.csv`'de satır satır yazılı.

## Neden önemli

Bu arşivlerde **gerçek piyasa tick verisi yok** (`.indir`, `.py`, `.zip`, `.html`, `.pdf`,
`.png`, `.db`). Backtest için kullanılamazlar; tarihsel sürüm koleksiyonudur.

## Elle taşıma (gerektiğinde)

```bash
# Drive'dan indir, sonra doğrula:
sha256sum -c drive/MANIFEST/sha256.txt
# GitHub'a yükle (gh CLI, tarayıcı açıkken):
gh release create veri-2026-11-13 toplama-*.zip --notes "Drive arşivi"
```
