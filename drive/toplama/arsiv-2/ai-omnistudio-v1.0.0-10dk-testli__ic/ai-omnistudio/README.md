# AI OmniStudio

**20 gerçek YZ sağlayıcılı, birleşik kripto işlem araştırma platformu.**
Mail arşivindeki **v8 → v9.4.5** hattının doğrulanmış davranışlarından temiz inşa.

> **PAPER MODU:** Gerçek piyasa verisi okunur, işlemler **sanal deftere** yazılır.
> Borsaya **emir gönderilmez**. LIVE kod yolu kilitlidir.
> **Kârlılık iddiası yoktur.** Arşivin v9.4.1 hükmü (strateji komisyon öncesi net
> negatif) bu sürümde değişmedi.

---

## Hızlı başlangıç

```bash
cd ai-omnistudio
pip install -r requirements.txt

# Ağsız bütünlük kontrolü
python3 cli/main.py check

# 20 YZ sağlayıcısının durumu
python3 cli/main.py providers

# Kısa gerçek veri koşusu (2 dk + 20 sn drenaj)
python3 cli/main.py run --config configs/quick-test.json

# Uzun koşu, geniş evren
python3 cli/main.py run --config configs/default.json \
    --duration 600 --drain 60 --symbols 70

# Testler (ağ gerektirmez)
python3 -m pytest -q

# Canlı pano
python3 web/server.py --port 8080
```

## Ne yapar

```
Gerçek piyasa verisi (WS + REST)
        ↓
SpikeDetector    — ani hareket + 3 dk bağlam + piyasa genişliği
        ↓
EntryPolicy      — 11 sert kapı, mum başına tek deneme
        ↓
RiskManager      — portföy limitleri, ATR stop/TP, boyut
        ↓
AICouncil        — 20 üye, 3 turlu çapraz teftiş
        ↓
PaperExecutor    — sanal maker dolumu, ücret, PnL
        ↓
StateStore       — SQLite WAL + JSONL kanıt + rapor
```

## 20 YZ sağlayıcısı

Hepsi **gerçek API uçlarıdır**. Anahtar yoksa çağrılmaz.

| # | Sağlayıcı | Rol | Ortam değişkeni |
|--:|---|---|---|
| 1 | OpenAI | hakem | `OPENAI_API_KEY` |
| 2 | Anthropic Claude | hakem | `ANTHROPIC_API_KEY` |
| 3 | Google Gemini | hakem | `GEMINI_API_KEY` |
| 4 | xAI Grok | denetçi | `XAI_API_KEY` |
| 5 | DeepSeek | denetçi | `DEEPSEEK_API_KEY` |
| 6 | Mistral AI | denetçi | `MISTRAL_API_KEY` |
| 7 | Groq | hızlı eleme | `GROQ_API_KEY` |
| 8 | Together AI | denetçi | `TOGETHER_API_KEY` |
| 9 | Fireworks AI | hızlı eleme | `FIREWORKS_API_KEY` |
| 10 | Perplexity | denetçi | `PERPLEXITY_API_KEY` |
| 11 | Cohere | denetçi | `COHERE_API_KEY` |
| 12 | OpenRouter | denetçi | `OPENROUTER_API_KEY` |
| 13 | Cerebras | hızlı eleme | `CEREBRAS_API_KEY` |
| 14 | SambaNova | hızlı eleme | `SAMBANOVA_API_KEY` |
| 15 | Hyperbolic | denetçi | `HYPERBOLIC_API_KEY` |
| 16 | DeepInfra | denetçi | `DEEPINFRA_API_KEY` |
| 17 | Novita AI | denetçi | `NOVITA_API_KEY` |
| 18 | Alibaba Qwen | denetçi | `DASHSCOPE_API_KEY` |
| 19 | Moonshot Kimi | denetçi | `MOONSHOT_API_KEY` |
| 20 | Zhipu GLM | denetçi | `ZHIPU_API_KEY` |

### Anahtar ekleme

```bash
cp .env.example .env
# .env içine anahtarlarınızı yazın
```

**İki mod asla karıştırılmaz:**

- `LIVE_LLM` — en az bir anahtar var, gerçek API çağrısı yapılır.
  Yeterli yanıt gelmezse `INSUFFICIENT_QUORUM` → **ret** (fail-closed).
- `RULE_BASED_QUANT` — anahtar yok. 20 deterministik kantitatif denetçi çalışır.
  Çıktıda `ai_generated: false` yazar. **YZ cevabı diye sunulmaz.**

Model kimlikleri geçilebilir: `OPENAI_API_KEY_MODEL=gpt-4o-mini` gibi.

## Gerçek veri kaynakları

Bulut ortamında Binance ana ucu HTTP 451, OKX 403 veriyor (coğrafi kısıt).
Bu yüzden resmî alternatifler kullanılır:

| Uç | Tür | Durum |
|---|---|---|
| `data-api.binance.vision` | spot | Binance'in **resmî public-data** aynası |
| `api.gateio.ws` | USDT vadeli | gerçek perp tick + funding |
| `contract.mexc.com` | USDT vadeli | alternatif |
| `api.bitget.com` | USDT-FUTURES | alternatif |
| `api-futures.kucoin.com` | vadeli | yalnız REST |

Her uç açılışta probing edilir. Erişilemeyen `UNREACHABLE` işaretlenir.
**Sentetik veriye sessizce düşülmez.**

## Arşivden devralınan ilkeler

| İlke | Nerede |
|---|---|
| Kör fail-open yasak (v9.1) | `ai/council.py` |
| Genişlik kapısı bağlamdan bağımsız (v20) | `strategy/detector.py` |
| Mum başına tek deneme | `strategy/policy.py` |
| Dedektör piyasa yönünü döndürür | `core/types.py` |
| Tekrar sayacı ≠ ekonomik ret (v9.4.4) | `PolicyState` |
| Görev ölümünde giriş kes, pozisyon zorla kapatma (v9.4.5) | `runtime/supervisor.py` |
| Monotonic süre, boşlukta DISCONTINUOUS | `core/clock.py` |
| Writer lease hatası yutulmaz | `state/store.py` |
| Eski DB devralınmaz | `StateStore(fresh=True)` |
| Ölçütler koşudan önce beyan edilir | `Engine._criteria()` |

## Arşivdeki açık işlerin çözümü

| İş | Çözüm |
|---|---|
| Fiyat araması O(n) | `PriceHistory` — ön-ek maksimum + ikili arama, **O(log n)** |
| Hacim oranı döngüsü | Kayan pencere toplamı, **amortize O(1)** |
| Genişlik tekrar maliyeti | İndeksli arama + 250 ms önbellek |
| Tekil sinyal/karar kimliği | `signal_id` + `decision_id` + `closed_bar_key` |

Her optimizasyon **eşdeğerlik testiyle** korunur: eski doğrusal aramayla
birebir aynı çıktı. Tick atlanmaz, eşik değişmez.

## Proje yapısı

```
omnistudio/
├── core/          types, clock (monotonic/süreklilik), config
├── ai/            registry (20 sağlayıcı), adapters (4 protokol), council
├── market/        gerçek REST + WS, çoklu borsa, sağlık
├── strategy/      price_history, detector, indicators, policy
├── risk/          boyut, stop/TP, kâr kilidi, devre kesici
├── execution/     paper (sanal defter), live_guard (kilit)
├── state/         SQLite WAL, writer lease, niyet kaydı
├── runtime/       engine (orkestrasyon), supervisor (görev denetimi)
└── reporting/     Markdown + JSON rapor
cli/               komut satırı
web/               salt okunur canlı pano
tests/             150 test, ağ gerektirmez
configs/           default.json, quick-test.json
docs/              ARSIV_DENETIMI.md ve diğer belgeler
_archive/          17 özgün sürüm ZIP'i + v9.4.5 kaynağı (SHA doğrulanmış)
```

## Çıktılar

Her koşu `runs/<run_id>/` altında:

| Dosya | İçerik |
|---|---|
| `SONUC.json` | Makine okunur tam sonuç |
| `RAPOR.md` | İnsan okunur rapor |
| `config.json` | Koşuda kullanılan tam ayar |
| `decisions.jsonl` | Her karar, tüm kapı sonuçlarıyla |
| `events.jsonl` | Sinyal, emir, pozisyon, faz olayları |
| `health.jsonl` | Saniyelik sağlık kaydı |
| `state.db` | SQLite: karar/emir/pozisyon/equity |
| `console.log` | Süreç günlüğü |

## Dürüstlük sınırları

- **Kârlılık kanıtı yok.** Küçük PAPER örneklemi kârlılık veya yürütme
  güvenilirliği göstermez.
- **Açık unrealized gerçekleşmiş kâr değildir.** Çıkış ücretleri düşülmemiştir.
- **Stop mesafesi maksimum zarar garantisi değildir.** Gap, slippage, likidite
  boşluğu ve gelecekteki ücretler hariçtir.
- **Maker dolumu iyimser olabilir.** Gerçek kuyruk önceliği bilinmez; bu yüzden
  `require_trade_through=True` varsayılan (fiyat seviyeyi geçmeli).
- **Uptime garantisi yok.** Bütün VM durduğunda gözlemci de durur; dönüşte
  boşluğu tespit eder.
- **Ölçümler kapsayıcı duvar süresidir**, CPU profili değildir. İç içe ölçümler
  toplanmaz.
- **YZ anahtarları** hiçbir zaman rapora, panoya veya config dökümüne yazılmaz.

## Test

```bash
python3 -m pytest -q          # 150 test
python3 cli/main.py check     # ağsız bütünlük
```

Kapsam: fiyat indeksi eşdeğerliği (1000+ arama), kayan toplam eşdeğerliği
(24.000 kontrol), dedektör kapıları, risk/stop yolu, PAPER muhasebesi,
konsey fail-closed, LIVE kilidi, süreklilik, görev denetimi, SQLite lease,
uçtan uca sanal yaşam döngüsü.

## Lisans / sorumluluk

Araştırma amaçlıdır. Yatırım tavsiyesi değildir. Gerçek para kullanımına
uygunluğu **onaylanmamıştır**.