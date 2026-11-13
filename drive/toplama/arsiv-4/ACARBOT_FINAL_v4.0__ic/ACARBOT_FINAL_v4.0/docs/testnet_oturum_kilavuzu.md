# ACARBOT v4.0 — Testnet/Demo Oturum Kılavuzu (madde 24)

> **Dürüstlük notu:** 24-48 saatlik kesintisiz oturum, botun çalışacağı
> gerçek makinede (kendi bilgisayarınız / VPS) koşulmalıdır. Bu paketin
> hazırlandığı geliştirme ortamında uzun süreli süreç yaşatılamaz; bu
> yüzden burada SAHTE bir "24 saatlik rapor" üretilmedi. Bunun yerine
> aşağıda birebir uygulanabilir senaryo + kontrol listesi + rapor
> çıkarım komutları verilmiştir. Oturumu çalıştırıp `session_report.json`
> dosyasını paylaştığınızda, Analist ajanı çıktısıyla birlikte değerlendirmeyi
> birlikte yapabiliriz.

## 1. Önkoşullar

```bash
pip install -r requirements.txt
python -m pytest tests/ -q        # 483 test — hepsi geçmeli
```

API anahtarları (para çekme izni KAPALI, IP kısıtı AÇIK):

```bash
# Binance Futures Testnet: https://testnet.binancefuture.com
export BINANCE_TESTNET_API_KEY=...
export BINANCE_TESTNET_API_SECRET=...

# veya OKX Demo: https://www.okx.com/trs/v2/quick-start/demo (demo trading)
export OKX_DEMO_API_KEY=...
export OKX_DEMO_API_SECRET=...
export OKX_API_PASSPHRASE=...
```

## 2. Önerilen oturum senaryosu (Binance testnet, 24-48 saat)

```bash
python -m app.main --mode paper --paper \
  --live-testnet --live-exchange binance \
  --scan-all --motors trend \
  --live-entry-style post_only_market_fallback \
  --duration-minutes 1440 \
  --report-file session_24h.json 2>&1 | tee paper_24h.log
```

Notlar:
- `--scan-all`: tüm USDT perpetual evreni (hacimsel sıralı).
- `--motors trend`: dış v1.4 bulgusu gereği TREND-only önerilir; FADE'i
  denemek isterseniz `--motors both`.
- `--live-entry-style post_only_market_fallback`: post-only maker giriş;
  60 sn dolum süresi aşılırsa MARKET yedek (varsayılan). Saf maker için
  `post_only` (dolum yoksa borsa tarafı atlanır), eski davranış için
  `market`.
- 48 saat için `--duration-minutes 2880`.
- Süreç dayanıklılığı için `tmux`/`screen` içinde çalıştırın veya
  `nohup ... &` + `run_testnet_session.sh` kullanın.
- Aynı komutla `--live-exchange okx` → OKX demo TAM eşleme.

## 3. Saat saat ne izlenir (kontrol listesi)

| Zaman | Kontrol | Komut / yer |
|---|---|---|
| İlk 5 dk | Saat senkronu + pozisyon modu logları | `SAAT SENKRONU` / `POZİSYON MODU` satırları |
| İlk 5 dk | Restart kurtarma raporu | `RESTART KURTARMA: {...}` |
| Süreç boyunca | 429 sayısı | `grep -c "HTTP 429" paper_24h.log` (retry sonrası 0 hata beklenir) |
| Her panel | Bayat sinyal iptalleri + DCA + para akışı satırları | panel `SİSTEM SAĞLIĞI` bölümü |
| Giriş olduğunda | `TESTNET EŞLEME:` satırları (entry/stop) | post-only fallback logları: `EŞLEME:` |
| Saatlik | Mutabakat | paper vs testnet pozisyon adedi |
| Her gün | Günlük rapor + `equity_point` | `OTURUM RAPORU` / SQLite |

Kill switch / HARD_HALT görürseniz: `emergency-flatten` komutu
(`python -m app.main --emergency-flatten --live-testnet --live-exchange binance`).

## 4. Oturum sonunda rapor çıkarımı

```bash
# Otomatik yazılan özet
python - <<'PY'
import json
r = json.load(open("session_24h.json"))
print("versiyon:", r["version"])
print("işlem:", r["entries"], "giriş /", r["closes"], "kapanış")
print("net:", r["realized_pnl_session"], "| equity:", r["end_equity"])
print("bayat iptal:", r["stale_entry_cancels"])
print("ajanlar:", {k: v.get("flag") for k, v in r["agents"].items()})
print("analist:", r.get("analyst", {}).get("observations"))
PY

# Hata taraması
grep -E "ERROR|CRITICAL|KRİTİK" paper_24h.log | sort | uniq -c | sort -rn
```

## 5. Kabul kriterleri (yayına alma öncesi)

1. **Korumasız pozisyon yok:** `KRİTİK:` satırı 0.
2. **429 kalıcı hata yok:** retry sonrası `akış hatası` 0.
3. **Mutabakat sapması yok:** `local_only`/`exchange_only` beklenmedik büyümez.
4. **Stop her girişte kurulmuş:** her `entry:` için karşılık gelen `stop:`.
5. **Giriş/çıkış yönleri:** LONG→SELL kapanışlar doğru.
6. **Rapor tutarlı:** bakiye/equity matematiksel tutarlı, analist gözlemleri
   mantıklı.
Bu beş madde sağlamsa bir sonraki adım küçük gerçek sermaye + aylık
izlemedir; sağlam değilse logları paylaşıp düzeltme turu yapılır.

## 6. Çok rejimli doğrulama (madde 23) — oturumdan önce/sonra

```bash
python tools/download_history.py --exchange okx --symbol BTC-USDT-SWAP \
    --out-symbol BTCUSDT --bars 6000 --funding --funding-periods 90
python -m app.main --mode backtest --data-dir data --symbols BTCUSDT
# → REJİM BAZLI DÖKÜM tablosu: TREND_UP / TREND_DOWN / RANGE ayrı satırlar
```

`--funding` ile indirilen `<SYM>_funding.csv` varsa backtest GERÇEK funding
oranlarını uygular; `regime_breakdown` tablosu stratejinin hangi rejimde
kazandırdığını/kaybettirdiğini ayrıştırır (boğa/ayı/yatay).
