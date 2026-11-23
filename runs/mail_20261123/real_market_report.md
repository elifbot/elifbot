# Maildeki üç bot — gerçek piyasa verisi kontrol raporu

**Sonuç:** GitHub Actions koşusu başarılı: [Smoke run 45229625681](https://github.com/elifbot/elifbot/actions/runs/45229625681)  
**Koşu zamanı:** 2026-11-23 17:37:10–17:41:06 UTC  
**Commit:** `65f0de62bb48862ccd7b1d5ddda5c671205a19ef`

E-postadaki sürümler ayrı ortamlarda kuruldu ve OKX'in **public** piyasa akışıyla kontrol edildi. API anahtarı kullanılmadı; gerçek emir endpoint'i çağrılmadı.

## Sonuç özeti

| Bot | Sürüm / mod | Gerçek veri kontrolü | Sonuç |
|---|---|---|---|
| Freqtrade | 2026.10 / gerçek dry-run | OKX public USDT-settled linear swap evreni, 5m, 180 sn | Başarılı başlatma; heartbeat görüldü; 0 paper işlem, 0 açık işlem |
| OctoBot | 2.1.1 / simulator-only probe | OKX public future akışı; BTC, ETH, SOL; 15m ve 1h mumlar, 180 sn | Başarılı; 3 kontratta candle teslimi; feed hatası yok; trader kapalı |
| Jesse | 3.7.0 / core research replay | OKX public BTC-USDT-SWAP, kapalı 1m mumlar → 15m strateji | 1.439 mum, 5 test işlemi; 2 kazanç / 3 kayıp; net **−0,7495 USDT** |

## Ayrıntılar

### Freqtrade

- Yapılandırma `dry_run: true`, boş `key/secret/password`, başlangıç cüzdanı 1.000.000 USDT.
- Upstream `SampleStrategy` kullanıldı; short kuralları etkinleştirildi.
- Gözlenen 180 saniyelik çalışma sonunda `running_heartbeat: true`, `paper_trades: 0`, `open_trades: 0`.
- `exit_code: 130`, kontrollü SIGINT ile kapanıştan kaynaklanıyor; bu bir emir veya hata değil.
- Kapsam Freqtrade'in tanıdığı aktif USDT-settled linear swap'larla sınırlı; dated futures/inverse/diğer settlement currency kapsam dışı.

### OctoBot

- `trader.enabled: false`, `trader-simulator.enabled: true`, simüle başlangıç portföyü 1.000.000 USDT.
- OKX future sembolleri: `BTC/USDT:USDT`, `ETH/USDT:USDT`, `SOL/USDT:USDT`.
- 15m ve 1h candle abonelikleri kuruldu; üç sembolden teslim kanıtı alındı.
- `simulator_and_okx_future_seen: true`, `early_exit: false`, `exit_code: 0`, `feed_errors: []`.
- Bu, candle akışının ve simulator başlatmanın kanıtıdır; sinyal, dolum, işlem sayısı veya kârlılık kanıtı değildir.

### Jesse

- Jesse live/paper eklentisi arşivde bulunmadığı için yalnız Jesse core research çalıştırıldı.
- OKX public `BTC-USDT-SWAP` kapanmış 1m mumları kullanıldı; API 3.000 istenmesine rağmen bu koşuda 1.439 kesintisiz kapalı mum döndü: `2026-11-22T17:38:00Z`–`2026-11-23T17:36:00Z`.
- Harness stratejisi: long-only, 50 USDT sabit notional, EMA20/EMA50 + RSI14, yüzde 1 stop/target; strateji e-postadaki üretim stratejisi olarak yorumlanmamalıdır.
- Sonuç: 5 işlem, 2 kazanç, 3 kayıp, yüzde 40 kazanma oranı; başlangıç 1.000.000 USDT, bitiş 999.999,2505 USDT, net −0,7495 USDT. Bir işlem koşu sonunda açıktı (`open_pl`: −0,3372 USDT).
- Bu tarihsel replay'dir; Jesse canlı/paper emri veya geleceğe dönük kârlılık iddiası değildir.

## Güvenlik ve yorum sınırı

Bu koşu **gerçek piyasa verisi** kullandı, ancak **gerçek para veya gerçek emir kullanmadı**. Kısa gözlem süresi, sınırlı sembol evreni, slippage/funding/fill farkları ve Jesse harness stratejisi nedeniyle sonuçlar üretim kararına ya da kârlılık varsayımına dönüştürülemez.

Ham koşu kanıtlarının Actions artifact'leri GitHub run'ına yüklenmiştir. Sandbox'ın ağ izinleri GitHub'ın artifact/blob hostlarına erişmediği için özet ve check-run bildirimleri ayrıca bu rapora yazılmıştır. Makine okunabilir özet: [`real_market_summary.json`](./real_market_summary.json).
