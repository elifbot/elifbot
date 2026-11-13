# ACARBOT × OmniStudio — 5 Kasım 2026 entegrasyonu

Maildeki **ACARBOT V10** paketi (anlık akış + sözleşme denetimi, KISMİ) ile
**OmniStudio** çekirdeği tek bir PAPER motorunda birleştirildi.

> **PAPER:** gerçek piyasa verisi okunur, emirler **sanal deftere** yazılır.
> **Gerçek emir yolu yoktur** (`real_orders = 0`). **Kârlılık iddiası yoktur.**

---

## 1. Ne yapıldı (özet)

| Maildeki eksik | Bu sürümde çözüm |
|---|---|
| `contract_math.py` motora bağlı değildi; 614 sözleşme "desteklenmiyor" | `acarbot/contracts.py` — gerçek `exchangeInfo`/`instruments` alanlarından `ContractSpec`; **2.880 sözleşmenin 2.112'si** gerekçeli olarak PAPER'a uygun (%73,3) |
| Akış / genişlik / 15dk "bilinmiyor, sıfır nötr" | `acarbot/flow.py` — gerçek `aggTrades`/`trades` CVD, 5dk→15dk EMA rejimi, gerçek genişlik oranı |
| "Funding muhasebesi yok" | `PaperBook.apply_funding()` — borsanın oranı ve GERÇEK funding anında; `FUNDING_UNKNOWN` → giriş reddi |
| Likidasyon modeli yok | `1/kaldıraç − bakım marjı` mesafesi + `LIQUIDATION_TOO_CLOSE` kapısı (tahmin, etiketli) |
| Üç ayrı veri yolu (Gate adaptörü / Binance-OKX REST / ham WS) | `acarbot/marketdata.py` — 6 pazar için tek REST+WS arayüzü, `UNREACHABLE` açıkça işaretli |
| "Sadece sentetik parite testi" | `acarbot/backtest.py` — gerçek mumlarla 5 katmanlı A/B testi |
| Strateji anlık akışa bağlı değil | `--mode ws`: WS kapanmış mumu → strateji → konsey → defter |

## 2. Kurulum

```bash
cd acarbot-omnistudio
pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest -q          # 138 test, ağ GEREKTİRMEZ
```

## 3. Komutlar

```bash
# A) Yalnız tarama + ölçüm (emir yok)
python3 -m acarbot.engine --mode observe --per-market 60 --symbols 80 --duration 2 --out runs/olcum-1

# B) Anlık akışla PAPER (WS kapanmış 5dk mumları)
python3 -m acarbot.engine --mode ws --duration 900 --symbols 40 --per-market 20 \
        --strategy trend --out runs/paper-ws-1

# C) REST anlık görüntülerle PAPER
python3 -m acarbot.engine --mode paper --duration 600 --symbols 30 --out runs/paper-rest-1

# D) Gerçek mumlarla geriye dönük 5 katman testi
python3 -m acarbot.backtest --out runs/geriye-donuk-1 --symbols 240

# E) OmniStudio'nun kendi CLI'ı (maildeki paket)
python3 cli/main.py check        # (paketle birlikte gelmiyorsa atlanır)
python3 web/server.py --port 8080
```

`--out` her koşuda **yeni** klasör olmalıdır.

## 4. Çıktılar

`runs/<ad>/`: `SONUC.json`, `RAPOR.md`, `events.jsonl`, `OLCUM.json`,
`measure.json`, `konsey/konsey.json`.

## 5. Ölçülen sonuçlar (5 Kasım 2026, bu ortam)

**Kapsam (tam evren taraması):** 2.880 sözleşme / 6 pazar, 2.112 PAPER uygun.
Binance USD-M 942 (522) · Binance COIN-M 30 (0 — inverse bağlı değil) ·
OKX SWAP 540 (510) · OKX FUTURES 287 (0 — X-PERP/vadeli) · Gate USDT 1.080 (1.080) ·
Gate BTC 1 (0). Retlerin hepsi gerekçeli (`runs/kapsam-tam-evren/`).

**Anlık akış (15 dk canlı PAPER, WS):** 40 sembol, Binance USD-M + OKX SWAP
WS'ten 120 kapanmış mum; kayıt medyanı ~890 ms, en uzun 3,0 sn. 102 mum
değerlendirildi, 5 sinyal, 5'i maliyet kapısında reddedildi → 0 pozisyon
(kârlılık değil, **disiplin** göstergesi). Gate.io WS bağlantısı açıldı fakat
kapanmış mum göndermedi; raporda `closed=0` olarak açıkça yazılı.
Dosya: `runs/final-ws-paper-15dk/`.

**Geriye dönük test (240 sembol, ~25 saat, trend stratejisi):**

| Katman | İşlem | Net USDT | PF | Kazanma |
|---|--:|--:|--:|--:|
| A temel (maildeki gibi) | 372 | −839,44 | 0,226 | %18,6 |
| B + gerçek funding | 372 | −842,05 | 0,224 | %18,6 |
| C + konsey (ölçülmüş bağlam) | 147 | −381,53 | 0,245 | %28,6 |
| D + portföy riski & 1R | 21 | −31,90 | 0,174 | %28,6 |
| E + funding kaçışı | 21 | −31,90 | 0,174 | %28,6 |

**Yorum:** trend takibinin bu pencerede komisyon sonrası kenarı **yok**.
Katmanlar zararı küçültüyor, kâra çevirmiyor. E katmanı hiç tetiklenmedi →
"ölçülmedi", "yararsız" değil. Ayrıntılı tartışma ve öneriler:
`docs/OMNISTUDIO_TARTISMA.md`.

## 6. Bilinen sınırlar (dürüstçe)

- Derinlik (L2) yok: taker + makas + 2 bps kayma varsayımı; ince likit sözleşmelerde iyimser.
- Geçmiş tick arşivi yok: geriye dönük testte konseyin **akış** boyutu nötr kaldı.
- Likidasyon ve bakım marjı kademeleri yaklaşık.
- COIN-M/inverse, USDC marjlı, X-PERP, vadeli/teslimat ve TRADIFI ürünler **bilinçli olarak PAPER dışı** — hesap kuralları doğrulanmadan işlem açılmaz.
- Konsey anahtarsız modda `RULE_BASED_QUANT`; YZ çağrısı yapılmadı (`ai_generated=false`).
- Kısa örneklem (25 saat) kârlılık kanıtı değildir.
