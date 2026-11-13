# PHOENIX FINAL — Karşılaştırma ve Sentez Kararları

Bu dosya, 4 sistemin dürüst karşılaştırmasını ve final sürümde hangi fikirlerin
alınıp hangilerinin neden reddedildiğini özetler. (Detaylı rapor: sohbette teslim edilen DOCX.)

## Sistem karşılaştırması

| Boyut | AcarBot v7.2 | FUSION_PRO 4.0 (ChatGPT) | sentez-bot (Claude) | Phoenix v2.0 | Gemini (2 paket) |
|---|---|---|---|---|---|
| Boyut | ~190 dosya, devasa | ~800 satır py | ~1300 satır + 75 test | ~1200 satır | 154–254 satır |
| Strateji | 4-bileşen ağırlıklı skor (ind/flow/news/ML) | 10+ faktör + microstructure | 10 oy confluence | 6 faktör confluence | **YOK** |
| Backtest | Event-driven + OOS | **sahte** (sonraki kapanış, SL/TP yok) | örnek ders: kötümser, gerçekçi | kötümser | YOK |
| Walk-forward | var (walkforward.py) | yok | **var, baz-karşılaştırmalı** | yok | YOK |
| Risk | 5% SL @20x (likidasyon riski!), sınırsız piramitleme, çapraz kurtarma | $20 bütçe, cross 10x, pozisyon limiti yok | örnek ders: kırpma mantığı, kesiciler | %1 risk, isolated, kesiciler | YOK |
| Canlı emir | var (karmaşık) | var (Binance+OKX ham httpx) | **YOK (yalnız paper)** | var (ccxt) | YOK |
| Durum kalıcılığı | SQLite WAL | yok (bellekte) | yok | yok | yok |
| Test | az | 3 minik dosya | **75 test** | yok (kod hiç çalıştırılmadı) | 1 minik |
| Dürüstlük | orta | orta | **yüksek** (negatif beklentiyi bile yazar) | orta | ilgisiz |

## Final sürüme ALINANLAR

1. **Phoenix v2.0 iskeleti** — modüler yapı, ccxt canlı yol, dry→testnet→live merdiveni.
2. **sentez-bot**: kötümser motor semantiği (stop-once, sonraki-açılış giriş, kayma+makas), edge/maliyet kapısı, mum boşluğu koruması, ardışık-zarar duraksaması, **walk-forward**, katkı analizi, nedensel göstergeler, test disiplini.
3. **FUSION_PRO**: HTF oybirliği, rejim-özel dinamik eşik, hacim-z ve sıkışma vetoları, **kısmi TP + runner trail**, spread/funding koruması, enstrüman limitleri.
4. **AcarBot**: oynaklığa uyarlanmış kaldıraç (GÜVENLİ bant), durum kalıcılığı (JSON), kill-switch dosyası, çoklu-veri-kaynağı failover.

## Final sürüme ALINMAYANLAR (gerekçeyle)

- **Sınırsız piramitleme** (AcarBot): düşen marjla artan maruziyet = nokta-likidasyon davranışı.
- **Çapraz kurtarma / pair rescue** (AcarBot): kaybedeni kurtarmak yerine zararı çiftleyebilir.
- **20x kaldıraç + %5 SL** (AcarBot): %5 × 20x = %100 marj → SL tam likidasyon noktası.
- **Cross margin + pozisyon limiti yok** (FUSION_PRO): $1000 kasada birkaç ters pozisyon hesabı bitirir.
- **FUSION_PRO'nun backtest'i**: SL/TP simülasyonu olmadığı için sonuçları yanıltıcıdır; yerine sentez disiplini alındı.
- **Gemini paketleri**: kripto trading botu değildir (polimer/pigment ERP aracı); kod tabanına katkı sağlamaz.
- **ML predictor / news / LLM konseyi** (AcarBot): anahtarsız çağrılamayan iskeletler; sahte onay üretirdi (sentez'in gerekçesi benimsendi).

## Phoenix v2.0'ın dürüst zayıflıkları (kendi işim)

1. Kod o oturumda hiç çalıştırılmadı — FINAL sürümde 30 test yazıldı ve **çalıştırıldı**.
2. Tek zaman çerçevesiydi — FINAL'e HTF oybirliği eklendi.
3. Kısmi kâr alma yoktu — FINAL'e tp1 + runner eklendi.
4. Durum kalıcılığı ve kill dosyası yoktu — FINAL'e eklendi.
5. Microstructure (taker/OI/derinlik) yok — hâlâ yok; dürüst sınırlar altında belirtildi.
