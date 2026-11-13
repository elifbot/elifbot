# ACARBOT — BOT 4 APEX + BOT 3 HYBRID v2

Tek başına çalışan paket. Eski `turbo_engine.py` yaması **gerekmez**; dört dosya kendi kendine yeter.
13 Kasım 2026 · Kasa 1.000 $ · teminat 50 $ × 10x **ÇAPRAZ** · pozisyon başına kesin **−20 $ net stop**

## Dosyalar

| Dosya | İçerik |
|---|---|
| `cekirdek.py` | Ortak motor: filtre, mikro-tape, pozisyon, kâr motoru, rapor |
| `apex_bot.py` | **BOT 4 APEX** — kazanan kovalar + portföy risk tavanı |
| `hybrid_bot.py` | **BOT 3 HYBRID v2** — çift hat + vali + kuyruk + zaman hasadı |
| `canli.py` | Canlı besleme (Binance USDⓈ-M + OKX SWAP, gerçek WS akışı) + dosya replay |
| `requirements.txt` | Sadece `websockets` (canlı mod için) |

`cekirdek.py` standart kütüphane dışında hiçbir şey kullanmaz. `websockets` yoksa iki bot yine çalışır, sadece `canli.py` çalışmaz.

## 1. Kurulum

```bash
mkdir acarbot_v2 && cd acarbot_v2
# 5 dosyayı bu klasöre indir
pip install -r requirements.txt      # sadece canlı akış için
```

## 2. 10 saniyelik doğrulama (ağ gerekmez)

```bash
python apex_bot.py --self-test
python hybrid_bot.py --self-test
```

**APEX** beklenen çıktı:
- `open_count: 1` → sentetik patlama tickinde LONG açıldı
- `filtre_veto` içinde `VOL_ZAYIF` → ilk 50 zayıf tick reddedildi
- `ek.risk_tavani_usd ≈ 249,9` → kasanın %25'i
- `closed_count: 0` → pozisyon henüz kapanmadı (giriş anında net −0,50 $ komisyon)

**HYBRID v2** beklenen çıktı:
- `ek.tracks.COUNCIL_TRACK.opened: 1` → 11x hacim + 0,82 akış konsey hattını seçti (doğru davranış)
- `ek.tracks.FAST_TRACK.opened: 0`
- `ek.kuyruk.bekleyen: 0`, `ek.vali.edge` alanı dolu

> Bu test **sentetik** tick kullanır; performans iddiası değil, sadece kodun ayakta olduğunu gösterir.

## 3. Canlı çalıştırma (gerçek piyasa verisi)

```bash
# APEX, Binance + OKX, 80 likit kontrat izle, her 10 sn özet
python canli.py --bot apex

# HYBRID v2, 120 kontrat, 600 saniye, durumu dosyaya yaz
python canli.py --bot hybrid --izleme 120 --sure 600 --state hybrid_durum.json

# sadece Binance (OKX coğrafi engelliyse)
python canli.py --bot apex --borsalar binance

# iki botu ayrı terminallerde aynı anda çalıştır
python canli.py --bot apex   --state apex_durum.json
python canli.py --bot hybrid --state hybrid_durum.json
```

Tick kaydı alıp sonra tekrar oynatmak (iyi anları saklamak için):

```bash
python canli.py --bot apex --record 13kasim.jsonl --sure 3600
python canli.py --bot apex --kaynak dosya --dosya 13kasim.jsonl
```

## 4. Parametreler (ajan konseyi K1–K9 kararları)

| Kapı | Değer | Gerekçe |
|---|---|---|
| `min_vol_mult` | **5,0x** | 2–5x kovası −28,14 $ → yasak |
| `min_ivme_pct` | **0,18 %** | K3 tabanı |
| `max_ivme_pct` | **0,60 %** | %0,60+ kovalama −32,74 $ → yasak |
| `min_akis` | 0,15 | alıcı/satıcı dengesizliği |
| `min_burst_usd` | 8.000 $ | gürültü filtresi |
| `max_chop` | 64 | testere piyasa |
| dedupe / cooldown | 15 sn / 25 sn | aynı varlığa üst üste giriş engeli |
| açık risk tavanı (APEX) | kasanın **%25** | 4.200 $ = 6,62x kasa dersi |
| BE / kilit | 4,50 $ / 1,20 $ | kârı koru |
| trail | 7,50 $ | otonom TP |
| giveback (APEX) | 0,25 / 0,16 / 0,12 | TurboConfig 0,30/0,20/0,16'dan sıkılaştırıldı |
| giveback (HYBRID) | 0,28 / 0,18 / 0,14 | daha geniş nefes |
| HYBRID FAST_TRACK | 5x · 0,15 akış · 8.000 $ | BOT 1 tetikleyicisi |
| HYBRID COUNCIL_TRACK | 7x · 0,30 akış · 12.000 $ · testere<55 · skor≥0,56 | BOT 2 disiplini |
| vali | DD %8 → hızlı hat kapanır · edge<1,6 → giriş yok | hayatta kalma |
| kuyruk | 30 sn TTL, %0,6 kayma toleransı | marjin doluyken sinyal kaybolmasın |

## 5. Tick formatı (kendi beslemenizi bağlamak için)

Her satır bir JSON nesnesi (JSONL) ya da tick listesi:

```json
{"exchange":"binance","symbol":"BTCUSDT","price":65000.0,
 "ts":1794563956.0,"delta_usd":1200.0,"buy_usd":900.0}
```

- `price` ve `delta_usd` zorunlu.
- `buy_usd` yoksa `delta_usd/2` varsayılır → akış yönü 0 olur → **AKIS_TERS** reddi. Gerçek alıcı-agresif hacim şart.
- Alternatif: `kline_q` + `kline_ts` (24s hacim farkından delta üretilir).

Mevcut altyapınıza bağlamak için motor arayüzü:

```python
from apex_bot import Apex
m = Apex()
m.ingest_batch(ticks)      # list[dict]
m.ingest_ticks(ticks)      # aynı
m.snapshot()               # panelin beklediği tam state
m.ozet()                   # kısa özet
```

`three_bot_panel.py` tarafında `TurboEngine` yerine `Apex()` / `HybridV2()` koymak yeterli — `snapshot()` şeması aynı alanları taşır (`account`, `open_positions`, `closed_trades`, `filtre`, `governor`, `universe`, `ek`).

## 6. Dürüst notlar

1. **Bu paket yeni yazıldı.** Mantık ve parametreler 57 testlik APEX build'iyle ve 1 saatlik 3-bot yarışının sonuçlarıyla aynı, ancak bu 4 dosya benim tarafımdan çalıştırılıp test edilmedi (sandbox erişimi kapalıydı). `--self-test` komutları bunu 10 saniyede doğrular; hata çıkarsa bana iletin, düzeltilir.
2. **CANLI modda emir gönderilmez.** Bu motorlar sinyal/pozisyon simülasyonu üretir (paper). Borsa API anahtarı istemez, hiçbir yere bağlanmaz. Gerçek emir için ayrı bir yürütme katmanı gerekir.
3. **1 saatlik yarışta** BOT1 kasada kazandı (+2,58 %) ama teminatı 2.400 $'a çıkardı; BOT2/BOT3 serbest marjin kapısı sayesinde 950 $'da kaldı. APEX bu yüzden portföy risk tavanını koda gömdü.
4. **OKX coğrafi engel** verirse `--borsalar binance` kullanın; evren yine 800+ kontrat.

## 7. Zip olarak indirme

Drive'da `ACARBOT_APEX_HYBRID_v2` klasörünü açın → sağ tık → **İndir** → Drive klasörü zip olarak verir.
