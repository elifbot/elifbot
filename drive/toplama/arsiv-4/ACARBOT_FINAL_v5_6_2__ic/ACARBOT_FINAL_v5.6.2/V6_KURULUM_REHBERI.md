# ACARBOT — KURULUM REHBERİ (v5.5 / v6.0 hazırlık)

**Durum:** v5.5 teslim edildi. v6.0 yol haritası aşamalı.
**Gerçek işlem varsayılan olarak KAPALIDIR.**

---

## 1. GEREKSİNİMLER

- Python **3.11+**
- ~500 MB disk (90 gün × 6 sembol önbellek)
- 1 yıl × 50 sembol için ~6 GB (Faz 1, henüz kurulmadı)

---

## 2. TEMİZ KURULUM

```bash
unzip ACARBOT_FINAL_v5.5.zip
cd ACARBOT_FINAL_v5.0

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Sürümler sabittir (`requirements.txt`); reprodukabilir kurulum.

### Doğrulama

```bash
python3 -m pytest tests/ -q      # 848 passed beklenir
python3 -m ruff check .          # All checks passed beklenir
python3 -c "import app; print(app.__version__)"   # 5.5-final
```

---

## 3. ORTAM DEĞİŞKENLERİ

API anahtarları **kodda tutulmaz**. `.env` veya ortam değişkeni:

```bash
# Yalnızca OKX (paper/veri için anahtar GEREKMEZ)
export OKX_API_KEY="..."
export OKX_API_SECRET="..."
export OKX_API_PASSPHRASE="..."

# Binance USD-M — DİKKAT: bölge kısıtı olabilir (HTTP 451)
export BINANCE_API_KEY="..."
export BINANCE_API_SECRET="..."
# Testnet için:
export BINANCE_TESTNET=1
```

**Güvenlik kuralları:**
- Anahtarlara **para çekme yetkisi VERMEYİN**
- IP kısıtlaması açın
- Anahtarlar loglara yazılmaz (`safety/security.py`)
- `.env` dosyasını sürüm kontrolüne eklemeyin

### Binance 451 uyarısı

Binance bazı bölgelerde **yasal uygunluk** kısıtı uygular (HTTP 451,
`'b. Eligibility' in Binance Terms`). Bu bir teknik arıza değildir;
endpoint değiştirerek çözülmez. Kullanım şartlarına uyum kararı
kullanıcıya aittir. Kod `BINANCE_BASE_URL` ile özel uç nokta
destekler ama bunu **sessizce yapmaz**.

---

## 4. ÇALIŞMA MODLARI

| Mod | Komut | Gerçek para |
|---|---|---|
| **Backtest** | `python3 -m tools.validate_strategy ...` | Hayır |
| **Paper** | `python3 -m app.main --mode paper --paper` | Hayır |
| **Testnet** | `--live-testnet` + ortam değişkeni | Hayır (test parası) |
| **Canlı** | `--live` + açık onay | **EVET — varsayılan KAPALI** |

**Sıralama zorunlu:** Backtest → Paper → Testnet → (ancak kriterler
geçerse) Canlı. Testnet doğrulanmadan canlıya geçilmez.

---

## 5. İLK ÇALIŞTIRMA (paper)

```bash
python3 -m app.main --mode paper --paper --profile apex --balance 1000
```

Panel metin tabanlıdır (`monitor/dashboard.py`). Web arayüzü **yok**;
Faz 6 işidir.

---

## 6. VERİ ÖNBELLEĞİ

```
data/validation/
  BTCUSDTSWAP_5m_25920.csv          # 90 gün 5m
  fine_targeted/
    OKX_BTCUSDTSWAP_1m_targeted.csv # hedefli 1m
```

İlk koşuda veri indirilir (sembol başına ~45 sn). Sonraki koşular
önbellekten okur.

**Uyarı:** önbellek anahtarları **borsa öneklidir**
(`okx:BTC-USDT-SWAP` → `OKX_BTCUSDTSWAP_...`). Öneksiz verilirse
sessizce boş döner.

---

## 7. SORUN GİDERME

| Belirti | Neden | Çözüm |
|---|---|---|
| `veri boş` | Sembol anahtarı borsa önekli yazılmış | `--exchange okx --symbols BTC-USDT-SWAP` (öneksiz) |
| HTTP 451 | Binance bölge kısıtı | OKX kullanın veya uyum kararı verin |
| 0 işlem | İnce veri yok + dürüst TTL | `--fine-mode targeted` ile 1m indirin |
| Referans bayat | Sürüm değişti | `python3 -m tools.make_reference --from docs/dogrulama_vX.json` |
| Paket yazılmadı | Tutarlılık kapısı | `python3 -m tools.package_release --check-only` |

---

## 8. PAKETLEME

```bash
python3 -m tools.make_reference --from docs/dogrulama_v5.5_rolling.json
python3 -m tools.package_release --check-only
python3 -m tools.package_release --out-dir ..
```

Kapı geçmezse ZIP **yazılmaz**. Manifest ve sha256 otomatik üretilir.
