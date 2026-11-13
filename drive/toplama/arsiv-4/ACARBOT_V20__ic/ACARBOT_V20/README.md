# ACARBOT V20

Binance Futures + OKX Futures sinyal, risk, paper ve (opsiyonel) canlı emir çekirdeği.
V15_1 (4.5.1-hardened-v15) + `min_score=0.30` paketi + canlı test raporu + yeni bulgular birleştirildi.
Python paketi adı `phoenix` olarak kaldı (komutlar değişmedi): `python -m phoenix.live ...`

> Bu paket kârlılık iddiası taşımaz. Yazılım doğruluğu ≠ strateji kârlılığı. Canlıya geçmeden önce OOS/walk-forward gerekir.

## Modlar (kaza ile değişmez)

| Mod | Nasıl | Ne yapar |
|---|---|---|
| READ_ONLY | varsayılan | Veri çeker, skorlar, rapor yazar. Hiçbir şey simüle etmez/göndermez |
| PAPER | `--paper` | `SIZING → RISK → CORRELATION → PAPER ACCEPT/REJECT`; her red `(aşama, neden)` ile raporlanır |
| LIVE | `--live` + `PHOENIX_CONFIRM_LIVE=YES` + API anahtarları | Gerçek emir. `--live` ve `--paper` birlikte kullanılamaz |

## Kurulum

```bash
python -m pip install -r requirements.txt
cp .env.example .env     # READ_ONLY/PAPER için anahtar gerekmez
```

## Yarınki test: 10 dk READ_ONLY → 10 dk PAPER

```bash
./run_v20_plan.sh                 # Linux/macOS
RUN_V20_PLAN.bat                  # Windows
```

Sonra tek tek okumak için: `python tools/read_report.py reports/paper_10min.json`
Zinciri nasıl okuyacağın: `docs/V20_TEST_PLAN.md`.

## Hızlı komutlar

```bash
python -m phoenix.live --duration 600 --poll 15 --max-cycle-sec 240 --report reports/readonly.json --score-log reports/scores.jsonl
python -m phoenix.live --paper --duration 600 --poll 15 --max-cycle-sec 240 --report reports/paper.json
python tools/calibrate_from_scores.py reports/scores.jsonl     # eşik başına geçen aday sayısı (çevrimdışı)
python -m phoenix.live --clear-halt                            # kill switch kilidini elle kaldır
```

## Test

```bash
PYTHONPATH=. pytest -q
python -m compileall -q phoenix tests tools
```

Ayrıntılar: `docs/V20_BUILD_REPORT.md` (ne değişti, neyin test EDİLEMEDİĞİ dahil), `docs/OPERATIONS.md`, `CHANGELOG.md`.
