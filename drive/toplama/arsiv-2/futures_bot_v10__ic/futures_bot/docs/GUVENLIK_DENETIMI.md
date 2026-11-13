# Güvenlik Denetimi — futures_bot

**Tarih:** 2026-10-27 · **Kapsam:** `futures_bot/` (35 kaynak dosya, 3.909 satır)
**Ölçek:** Her kategori için **PASS / SORUN BULUNDU / DOĞRULANMADI** üçlüsünden
biri kullanılmıştır; PASS yalnızca **doğrulama yöntemi belirtilerek** verilmiştir.

---

## 1. Gerçek Emir Önleme — **PASS**

**Yöntem:** AST taraması (`tests/test_security.py::test_no_write_http_methods`)
— tüm `.py` dosyalarında `ast.Call` düğümlerinde `post/put/delete/patch/head`
aranır. Ek olarak `requests.Session` üzerinden yalnızca `session.get(...)`
kullanıldığı yerel taramayla görüldü.

**Sonuç:** Kullanılan tek HTTP metodu `get`. Sipariş/hesap/çekim uç noktası
(`/order`, `/trade`, `/withdraw`, `/account`) kodda **hiç geçmiyor**.

## 2. Kimlik Bilgisi Sızıntısı — **PASS** (bu depo) / **SORUN BULUNDU** (crew projesi)

**Yöntem:** AST düğümlerinde `api_key`, `secret`, `passphrase`, `private_key`
isim/kwarg taraması; `os.environ` erişimi yasağı; regex ile `sk-…`,
`AKIA…` desen taraması; `dotenv` importu yasağı.

**Sonuç (futures_bot):** Hiçbiri bulunmadı. Kimlik bilgisi okunmuyor,
istenmiyor, saklanmıyor.

**SORUN (crew projesi):** `binance_okx_paper_futures_bot/knowledge/user_preference.txt`
içinde yer tutucu kişisel veri vardı:

```
User name is John Doe.
User is based in San Francisco, California.
```

**Düzeltme:** Dosya gerçek kullanıcı bilgisiyle değiştirildi ve kişisel veri
içermeyecek şekilde sadeleştirildi (bkz. `crew/` klasörü). Bu dosya ajan
backstory'lerine sızabileceği için **temizlenmesi zorunludur**.

## 3. Ağ Yüzeyi — **PASS**

**Yöntem:** AST ile tüm `http://` / `https://` sabitleri çıkarıldı.

**Sonuç:** Tam olarak 4 URL, tamamı allowlist'te:

| URL | Kullanım |
|---|---|
| `https://fapi.binance.com/fapi/v1/klines` | Binance mumları |
| `https://fapi.binance.com/fapi/v1/exchangeInfo` | Binance tick/step |
| `https://www.okx.com/api/v5/market/candles` | OKX mumları |
| `https://www.okx.com/api/v5/public/instruments` | OKX ctVal/lotSz |

`ensure_url_allowed()` her istekten önce host + path kontrolü yapar; **şema
`https` olmalı**, ayrıca sorguda `api_key/apikey/signature/secret` geçen URL
reddedilir. Kullanıcı girdisinden f-string ile URL üretimi yoktur.

## 4. Canlı Mod Koruması — **PASS**

**Yöntem:** `tests/test_security.py::test_live_and_testnet_modes_exit` ve
`test_no_network_before_mode_guard`. `--mode live|testnet` verildiğinde
`guard_mode()` herhangi bir feed oluşturulmadan `sys.exit(1)` çağırır; testte
`BinanceFuturesFeed` yapıcısı "çağrılırsa patla" şeklinde mock'lanmıştır ve
çağrılmadığı doğrulanmıştır.

**Sonuç:** Sessiz geri düşüş (silent fallback) yok; bilinmeyen mod da exit 1.

## 5. Risk Yönetimi Bütünlüğü — **PASS**

**Yöntem:** `tests/test_pnl_accounting.py` (18 test) + kod okuması.

| Kural | Durum | Test |
|---|---|---|
| Giriş komisyonu marjla tek adımda | ✅ | `test_single_entry_fee_deduction` |
| Kaldıraç PnL'e ikinci kez çarpılmaz | ✅ | `test_leverage_not_multiplied_into_pnl_twice` |
| Toplam 6 pozisyon (açılış sonrası) | ✅ | `test_total_position_limit_post_open` |
| Aynı yönde 4 pozisyon (borsa bazlı) | ✅ | `test_same_direction_limit_post_open` |
| Marj kullanımı ≤ %45 | ✅ | `test_utilisation_cap_post_open` |
| Bakiye tabanı 100 USDT | ✅ | `test_balance_floor_blocks_entry` |
| Bakiye negatife düşmez (izole marj likidasyonu) | ✅ | `test_balance_never_negative` |
| Günlük zarar limiti (%5, özsermaye bazlı) | ✅ | `test_daily_loss_limit_blocks_new_positions` |
| Kaldıraç tavanı 20x | ✅ | `test_leverage_cap_enforced` |
| Sharpe < 30 işlemde bastırılır | ✅ | `test_sharpe_suppressed_for_29_trades` |
| Bayat fiyatla giriş engeli | ✅ | `test_stale_price_guard` |
| Son 7 dakikada giriş engeli | ✅ | `test_entries_blocked_in_last_minutes` |

**Düzeltilen hata:** Günlük zarar limiti ilk sürümde **bakiyeye** bakıyordu;
pozisyon açılışında marj bakiyeden düştüğü için normal bir açılış "zarar"
gibi görünüp sonraki tüm girişleri bloke ediyordu. Limiti **özsermaye**
(bakiye + kilitli marj + gerçekleşmemiş PnL) üzerinden ölçecek şekilde
düzeltildi.

## 6. Hata Yönetimi — **PASS**

**Yöntem:** AST/grep ile `except:` ve `except Exception` taraması + kod okuması.

**Sonuç:** Çıplak `except:` yok; geniş `except Exception` yok. Ele alınan
durumlar: `Timeout`, `429` (geri çekilmeli yeniden deneme), `451`, diğer
non-2xx, bozuk JSON, boş yanıt, bozuk satır (atılır + uyarı), doğrulanmamış
Phase C verisi (`DataUnavailableError`), şema hataları (loglanır, döngü sürer).
Ana döngü bir pair hatasında **durmaz**.

## 7. Girdi Doğrulaması — **PASS**

**Yöntem:** `tests/test_feed_utils.py` + `tests/test_feeds.py` + kod okuması.

Doğrulananlar: `open_time > 0` ve sayısal, OHLC sonlu ve pozitif,
`high ≥ max(open, close)`, `low ≤ min(open, close)`, `high ≥ low`,
`volume ≥ 0` ve sonlu, OKX `confirm == "1"`, OKX `ctVal > 0` (aksi halde
enstrüman atlanır), Binance `tickSize/stepSize > 0`, DataFrame zorunlu
kolon kontrolü, `open_time` sıralama/tekilleştirme.

## 8. Log / CSV Güvenliği — **PASS**

**Yöntem:** `tests/test_trade_logger.py` — başlık kümesi `FIELDS` allowlist'i
ile birebir karşılaştırılır; içerikte `http` ve mutlak yol aranır.

**Sonuç:** Yalnızca 16 alan yazılır. HTTP başlığı, yanıt gövdesi, kimlik
bilgisi veya mutlak iç yol CSV'ye yazılmaz. `funding_fee` alanı sayısal `0`
değil **`bilinmiyor`** olarak yazılır.

## 9. Bağımlılık Güvenliği — **PASS** (canlı tarama yapıldı)

**Yöntem:** `pip-audit -r requirements.txt` (PyPI advisory veritabanı,
2026-10-27) — gerçek tarama, gerçek çıktı:

```
No known vulnerabilities found
```

Çözümlenen sürümler (bu ortam): `requests 2.33.0`, `pandas 2.2.3`,
`numpy 2.3.5`, `tabulate 0.10.0`.

**Sınır:** `pip-audit` yalnızca **bilinen** CVE'leri görür; sıfırıncı gün
açıkları kapsamaz. Üretim öncesi kendi ortamınızda tekrar çalıştırın:
`pip-audit -r requirements.txt`.

## 10. GitHub / Deploy İzolasyonu — **PASS**

**Yöntem:** AST import taraması + grep.

**Sonuç:** `subprocess`, `git`, `smtplib`, `socket`, webhook, cron/scheduler,
APScheduler, celery **yok**. Otomatik tetikleyici (`run_with_trigger`)
**uygulanmamıştır**; `tests/test_security.py` bunu zorlar. Crew projesindeki
`run_with_trigger` kısayolu bilinen sorun olarak belgelenmiştir.

## 11. Strateji İzolasyonu — **PASS**

**Yöntem:** `tests/test_strategies.py`.

**Sonuç:** Üç aday da `STATUS = "SHADOW"`; hiçbiri kendiliğinden ACTIVE'e
geçmez. Her örnek kendi `_state` sözlüğüne ve kendi `disabled_families`
kümesine sahiptir. `build_candidates()` her çağrıda yeni örnek döndürür.
Girdi DataFrame'i **mutasyona uğratılmaz** (`test_strategy_does_not_mutate_input`).

## 12. Lookahead Koruması — **PASS**

**Yöntem:** `tests/test_indicators.py`, `tests/test_backtests.py`,
`tests/test_session.py`.

- Sinyal yalnızca `filter_closed_candles()` sonrası **kapalı** mumlardan üretilir.
- Stratejiler `df.iloc[-1]` (en son kapanmış mum) dışına bakmaz.
- `BacktestEngine._assert_no_lookahead()` pencereye karar anından sonraki mum
  girerse `LookaheadError` fırlatır; testte kasıtlı ihlal doğrulanmıştır.
- Walk-forward'da parametre izi (SHA-256) pencere içinde sabit kalır.

**Sınır:** Bu, "geleceği kullanmıyor" iddiasının **kod düzeyinde** kanıtıdır;
istatistiksel overfitting'i tek başına engellemez.

## 13. Sahte Veri Yasağı — **PASS**

**Yöntem:** dosya adları + üretim betiği + doküman taraması.

**Sonuç:** Sentetik veri yalnızca `scripts/make_synthetic_fixture.py` ile
üretilir, dosya adında `synthetic` geçer ve üretildiği anda ekrana
"gerçek piyasa verisi DEĞİLDİR" yazar. Gerçek veri anlık görüntüleri
`*_real_snapshot.csv` adıyla ve UTC zaman aralığıyla belgelenmiştir.
Hiçbir yerde uydurma backtest sonucu, uydurma funding değeri veya "canlı
performans" iddiası yoktur.

---

## Özet

| # | Kategori | Sonuç |
|---|---|---|
| 1 | Gerçek emir önleme | PASS |
| 2 | Kimlik bilgisi sızıntısı | PASS (depo) · SORUN BULUNDU → düzeltildi (crew) |
| 3 | Ağ yüzeyi | PASS |
| 4 | Canlı mod koruması | PASS |
| 5 | Risk yönetimi | PASS |
| 6 | Hata yönetimi | PASS |
| 7 | Girdi doğrulaması | PASS |
| 8 | Log/CSV güvenliği | PASS |
| 9 | Bağımlılık güvenliği | PASS (pip-audit, 2026-10-27) |
| 10 | GitHub/deploy izolasyonu | PASS |
| 11 | Strateji izolasyonu | PASS |
| 12 | Lookahead koruması | PASS |
| 13 | Sahte veri yasağı | PASS |

**Kalan bilinen riskler:** Binance erişimi bu ortamda 451 (bölgesel);
canlı Binance parser'ı yalnızca mock ile doğrulandı. Funding/OI/mark verisi
yok — muhasebe bu kalemler **hariç** hesaplanır.
