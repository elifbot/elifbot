# futures-flow-bot

Binance ve OKX **USDT-marjinli sürekli (perpetual) futures** piyasalarında yüzlerce coini aynı anda tarayıp
**para girişi / çıkışı (akış)** sinyaline göre long/short pozisyon açıp kapatan bot.

> **Varsayılan mod `paper` (sanal emir).** Gerçek paraya dokunmaz. Gerçek emir için sıra: backtest/paper →
> `testnet` → küçük `live`. Bu yazılım kâr garantisi vermez; 10x kaldıraçta sermaye hızla kaybedilebilir.
> Yatırım tavsiyesi değildir.

## Durum (dürüst özet)

| Parça | Durum |
|---|---|
| Özellik hesabı (delta, hacim patlaması, RSI, MACD), giriş/çıkış puanlama | Yazıldı, birim testli |
| Risk motoru (50$ marjin, 10x, isolated, 25$ stop, rezerv, cooldown, isteğe bağlı limitler) | Yazıldı, birim testli |
| Teknik arıza koruması (veri bayat, API hatası, uyumsuzluk) | Yazıldı, birim testli |
| Paper broker (maker/stop/komisyon/kayma modeli) | Yazıldı, birim testli |
| Çevrimdışı simülasyon (tüm boru hattı, sentetik veri) | Çalışıyor, CI'da duman testi |
| Binance/OKX WebSocket akışı, coin listesi (REST) | Yazıldı, **ağ olmadan yazıldığı için canlı test edilmedi** |
| CCXT emir katmanı (testnet/live) | Yazıldı, **hiç test edilmedi** — önce testnet |
| Haber / makro / analist ajanları | **Henüz yok** — `Engine.entry_filters` kancası hazır |
| Telegram komutları | Yok (alarm var; kontrol için dosya: bkz. `docs/OPERATIONS.md`) |

Simülasyon çıktıları sentetik veridir; **gerçek performans göstermez**, sadece yazılımın çalıştığını doğrular.

## Mimari

```
WebSocket (Binance + OKX, ~800 coin)
   → normalize işlem akışı → SymbolState (saniyelik kovalar, RSI/MACD)
   → giriş puanı → [entry_filters: haber/makro ajanları] → RİSK MOTORU → Broker (paper | ccxt)
   → çıkış puanı / trailing / breakeven / zaman stopu / borsada duran stop-market
   → SQLite kayıt + Telegram alarm        Güvenlik izleyici: arıza → yeni giriş durur
```

Neden Freqtrade değil? Freqtrade mum tabanlıdır ve tek borsa/örnek çalışır; 800 coinde saniyelik akış ve iki borsa
için ayrı bir motor gerekti. İhtiyaç olursa emir katmanı sonra Freqtrade/NautilusTrader'a taşınabilir.

## Hızlı başlangıç

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # canlı/testnet için: pip install -e ".[live]"
python -m unittest discover -s tests -v
cp config/config.example.yaml config/config.yaml
python -m tradebot check-config
python -m tradebot simulate --minutes 90      # ağ gerektirmez
python -m tradebot universe                   # taranacak coin sayısı (ağ gerekir)
python -m tradebot run                        # paper mod, gerçek veri akışı, sanal emir
```

İlk çalıştırmada göstergeler ısınır (~36 dk, 1 dakikalık mumlarla); bu sürede sinyal üretilmez.
Paper modda bot yeniden başlarsa sanal pozisyonlar sıfırlanır.

## Ayarlar

Hepsi `config/config.yaml` içinde: 50$ marjin, 10x, 25$ stop (≈%5 fiyat), borsa başına 500$ sanal bakiye,
günlük kayıp limiti ve pozisyon sınırı **kapalı** (`null`), giriş/çıkış eşikleri. Yanlış yazılmış ayar anahtarı hata verir.
Stop mesafesi tasfiyeye yakınsa (örn. 10x'te %9+) bot başlamaz.

## Güvenlik

Bkz. `SECURITY.md` ve `docs/GITHUB_SETUP.md`. Özet: anahtarlar yalnızca `.env`; çekim izni kapalı; IP kısıtı;
bot için alt hesap; `mode: live` için ayrıca `LIVE_TRADING_CONFIRM` ortam değişkeni gerekir.

## Yol haritası

1. (Burada) Çekirdek + paper + simülasyon
2. Canlı veriyle sadece-sinyal ve paper çalıştırma, eşik ayarı (gerçek akışta; OI ve emir defteri özellikleri eklenir)
3. Testnet/demo ile emir katmanının doğrulanması
4. Haber, makro, analist ajanları (filtre olarak, A/B testle)
5. Bulut (Docker), izleme paneli, Telegram komutları
6. Küçük canlı test → kademeli artış
