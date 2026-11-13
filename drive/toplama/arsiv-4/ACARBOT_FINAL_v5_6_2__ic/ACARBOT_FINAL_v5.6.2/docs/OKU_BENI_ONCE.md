# Önce bunu oku (v5.6.2 hijyen paketi)

Kökte ve `docs/` altında çok sayıda eski sürüm belgesi var. Güncel durum için
yalnızca şunlara bak:

| Ne öğrenmek istiyorsun | Dosya |
|---|---|
| Botu nasıl çalıştırırım | `README.md` |
| Son sürümde ne değişti | `DEGISIKLIKLER_FINAL_v5.6.md` ve `DEGISIKLIKLER_v5.6.2.md` |
| Son backtest sonucu ve hüküm | `V55_BACKTEST_RESULTS.md` (hüküm: NO_EDGE) |
| Ham doğrulama çıktısı | `docs/dogrulama_v5.6_final.json` |

Diğer `ANALIZ_*`, `V6_*`, `V55_*`, `DEGISIKLIKLER_FINAL_v1..v5.5` dosyaları
geçmiş kaydıdır; silinmedi, çünkü birbirlerine bağlantı veriyorlar.
Eski analiz belgelerinde geçen bazı ham kanıt dosyaları v5.6.2'de silindi (bkz. `DEGISIKLIKLER_v5.6.2.md`); bu bağlantılar tarihsel kayıttır.

## Durum özeti
- Test: `python -m pytest tests/ -q` (sayı burada sabitlenmez).
- Strateji: kenar kanıtı YOK (0/3 walk-forward penceresi kârlı).
- Gerçek para modu kapalı ve kapalı kalmalı; yalnızca paper/testnet.
