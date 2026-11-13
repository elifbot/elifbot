# ACARBOT · 6 bot + v8

Binance USDT-M ve OKX USDT-SWAP vadeli işlemlerde çalışan, **kullanıcı kuralına sabitlenmiş**
bir araştırma ve otomasyon deposu.

> ⚠️ **Bu bir yatırım tavsiyesi değildir.** Kâr garantisi yoktur; kasa kaybı mümkündür.
> Bu depodaki varsayılan mod **simülasyondur**, gerçek emir göndermez.

---

## 1. Değişmez kural

| Kalem | Değer | Not |
|---|---|---|
| Başlangıç kasası | **1.000 $** | |
| Pozisyon teminatı | **50 $** | her işlemde sabit |
| Kaldıraç | **10x** | → pozisyon başına **500 $** notional |
| Marjin modu | **CROSS** | izole **değil** |
| Pozisyon limiti | **yok** | emir sayısı sınırsız |
| Zarar kes | **−10 $ net** | komisyon dahil, fiyatta ≈ **%1.95** |

Bu altı sayı `bot/v8/config.py` içinde tanımlıdır ve testlerle kilitlidir
(`bot/tests/test_v8_kural.py`). Değiştiren PR reddedilir — gerekçe: kullanıcı kararı.

### Türetilmiş sayılar (aritmetik, görüş değil)

- Gidiş-dönüş taker komisyonu: **0.50 $** (500 $ × %0.05 × 2)
- Stop için gereken fiyat mesafesi: **(10 − 0.5) / 500 = %1.90** (+5 bps kayma payı)
- Bir kasanın taşıyabileceği eşzamanlı pozisyon: **~19–20** (1.000 / 50, komisyon düşünce 19)
- CROSS tasfiye mesafesi: 20 pozisyonda **%9.5**, 40'ta **%4.5**, 100'de **%1.5**

> **"Sınırsız pozisyon" ne demek?** Emir sayısı sınırsızdır; ama hiçbir borsa bakiyede olmayan
> teminatla pozisyon açtırmaz. 1.000 $ kasa, 50 $ teminatla *fiziksel olarak* ~20 pozisyon taşır.
> Bu sınırı yok sayan simülatör, kâğıt üzerinde kâr üretir; gerçek borsada emirlerin çoğu reddedilir.

---

## 2. Hızlı başlangıç

```bash
pip install -r requirements.txt

# 1) Paneli aç (6 botu tek ekranda dikey kart olarak gösterir)
python3 panel/server.py --port 8000 --host 0.0.0.0

# 2) 6 botu 60 dakikalık piyasa zamanında koştur
python3 bot/tools/replay_6bot.py --dakika 60 --etiket 2026-11-13_6bot_60dk

# 3) v8 (kurala sabitlenmiş motor) simülasyonu
python3 -m bot.v8.cli kurallar
python3 -m bot.v8.cli paper --dakika 60 --sembol 120

# 4) Testler
python3 -m pytest bot/tests -q
```

Panel: `http://localhost:8000`

---

## 3. Gerçek piyasa verisi (önemli)

Bu depo iki besleme modunu destekler:

| Mod | Komut | Ne ölçer |
|---|---|---|
| `sentetik` (varsayılan) | `replay_6bot.py --dakika 60` | Motorun **davranışı**: stop, kâr koruması, kaldıraç dinamiği |
| `csv` (**gerçek**) | `replay_6bot.py --besleme csv --ticks arsiv.csv` | **Kenar (edge)**: strateji gerçek piyasada para kazandırır mı |

Gerçek veri dosyası biçimi:

```csv
ts,symbol,price,delta_usd,buy_usd,quote_vol_24h
1791000000.0,BTC-USDT-SWAP,60030.92,15747.94,6331.11,500000000
```

- `ts` saniye (milisaniye verirsen otomatik çevrilir), hacimler **USD**
- Kaynak: Binance `aggTrades` / OKX `trades` dökümü, `data.binance.vision`, ya da kendi
  kaydettiğin tick jurnalın
- Örnek dosya: `data/ornek_tick_formati.csv`

> **Bu geliştirme ortamında borsa API'lerine ağ çıkışı yok** (Binance, OKX, Bybit, Kraken,
> `data.binance.vision` hepsi kapalı). Bu yüzden buradaki koşular **sentetik** besleme ile
> yapıldı ve raporlarda bu açıkça yazılı. Gerçek veriyle koşmak için `--besleme csv` yolunu
> kullan; kod hazır.

---

## 4. Depo haritası

```
bot/acarbot_6bot/      Orijinal 6-bot paketi (posta gelen zip) — yamalı çalışma kopyası
bot/tools/             sentetik piyasa, replay koşucusu, metrikler
bot/v8/                Kurala sabitlenmiş yeni motor (config, sizing, risk, broker, engine, adaptörler)
bot/tests/             Kural + borsa fiziği + adaptör testleri (37 test)
panel/                 Canlı panel (tek ekran, 6 dikey kart)
kadro/                 14 AI ajanı + 10 beceri + yönlendirme + çalışma kuralları
docs/                  Raporlar, mimari, test protokolü, risk matematiği
yamalar/               Orijinal koda yapılan değişikliklerin diff'i (denetlenebilir)
runs/                  Koşu çıktıları: rapor.json, jurnal.csv, metrikler.txt, ozet.md
drive/                 Drive'dan alınan küçük dosyalar (eski sürümler, analizler)
data/                  Tick biçimi örneği
```

---

## 5. Ölçülen bulgular (özet)

Orijinal 6-bot paketinde **koda bakarak** bulunan ve testle kilitlenen hatalar:

1. **Stop −20 $ uygulanıyordu** (kural −10 $): `turbo_engine.py`, `cekirdek.py`,
   `acarbot_omega/config.py`. Üçü de düzeltildi, diff `yamalar/` altında.
2. **Teminat kontrolü kapalıydı** (`enforce_free_equity_check = False`): 1.000 $ kasada
   123 pozisyon / 6.150 $ teminat / **53x hesap kaldıracı** "mümkün" görünüyordu. Açıldı.
3. **Kâr koruması borsada değil Python'da** kontrol ediliyordu: likit olmayan sembolde tek
   print boşluk bırakınca "BE kâr koruma" **−1.76 $** ile kapanıyordu (25 dk dökümünde 7 kez).
   v8 bunu borsada duran reduceOnly stop emriyle çözüyor.
4. **Belgelenen komut çalışmıyordu**: `pip install websockets aiohttp` yetersizdi
   (`numpy`, `pandas` gerekli) ve `PYTHONPATH=motorlar` olmadan import başarısızdı.
5. **OMEGA 60 dakikada 0 işlem kapattı** (19 pozisyon açık kalıyor) — çıkış motoru etkisiz.

Ayrıntı: [`docs/02-veri-analizi.md`](docs/02-veri-analizi.md), [`docs/07-rapor-60dk.md`](docs/07-rapor-60dk.md).

---

## 6. Kadro

`kadro/` altında 14 ajan ve 10 beceri var. Her PR'ın geçmesi gereken kapılar:

**Risk Subayı** (kural bekçisi) · **Kod İnceleyici** · **Ölçüm Analisti** (WR yanında başabaş WR).

Başla: [`kadro/README.md`](kadro/README.md) · [`kadro/ROUTING.md`](kadro/ROUTING.md) ·
[`kadro/CALISMA-KURALLARI.md`](kadro/CALISMA-KURALLARI.md)

---

## 7. Canlı para

Varsayılan **kapalı**. Açmak için `skills/s8-canliya-alma.md` kapısındaki maddelerin hepsi
gereklidir. Kilit:

```bash
export ACARBOT_CANLI_ONAY=EVET-RISKI-ANLIYORUM
```

Bu kilit bilinçlidir: yanlışlıkla canlı emir gönderilmesini engeller.
