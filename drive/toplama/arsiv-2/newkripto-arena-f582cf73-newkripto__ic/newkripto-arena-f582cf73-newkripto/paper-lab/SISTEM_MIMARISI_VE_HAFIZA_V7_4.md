# 🧠 KRIPTO-BOT v7.5 — Saf Kripto Futures + Çapraz Ortak Kasa + Anlık Akış Mimarisi

- **Sürüm:** `v7.5` (`%100 Saf Kripto USDT-M Futures + Çapraz Ortak Kasa [Bakiye + Açık K/Z] + Anlık Para Girişi/Çıkışı WS Tetiği + Flow-Confidence v2`)
- **Tarih:** `25.10.2026`
- **Doğrulama:** `134/134 pytest (-W error)` + `101/101 test_hizli` + `27/27 test_bot_v7` + `ruff check .` (`0` hata)

---

## 1. İki Gerçek 1 Saatlik Testten Çıkan Mühendislik Sentezi

| Oturum | Kasa Sonucu | Ne Doğru Çalıştı? | Ne Yanlış Çalıştı & v7.4 Çözümü |
|---|---:|---|---|
| **Run #1 (`40174169361`)** | **`+$31.89` (`+%3.19`, PF `4.23`)** | Saf kriptoda `13W / 3L` (`%81.25`), `KÂR KOŞUSU` modülü **`7/7` (`+$30.36`)** | Kripto-dışı sentetik kontratlar (`-$4.82`), `SATS`/`1000SATS` ikizi, sığ altcoin `LIGHT/USDT` global sigorta tetiklemesi -> **Tamamı çözüldü.** |
| **Run #2 (`40179959680`)** | **`-$35.06` (`-%3.51`)** | BTC/ETH kapsamlı sigorta `0` yanlış tetikleme; **`flow-confidence` kohortu zarar eden `11/11` işlemi reddedip `$0.00` kayıpla korudu**; Türev modülü en kötü 2 zararda (`ALLO`, `CFX`) `TOP_TRADER_LONG` uyarısını yakaladı. | İlk 80 sn soğuk başlangıç + A-B-C alfabetik tarama + `RSI 23–27` dip SHORT + `11/11` tek yön yığılma + 59 dk rehin kalan marj + yeni ABD hisse/ETF kontratları -> **v7.4 ile 5'i de kökten çözüldü.** |

---

## 2. v7.4'teki 5 Ana Kazanma Kalkanı

1. **%100 Saf Kripto USDT-M Futures Evreni (`src/futures_catalog.py`):**
   - ABD hisse senetleri (`AAPL`, `NVDA`, `AMZN`, `TSLA`, `MU`, `MRVL`, `WDC`, `JNJ`, `RIVN`, `RKLB`, `SHOP`, `CRCL`, `CRDO`, `CIEN`, `FLNC`, `IREN`, `MARA`, `COIN`, `MSTR`, `ONDS`, `MP`, `MRNA` vb.), Asya/Global senetler (`TENCENT`, `BABA`, `POPMART`, `HANMI`, `DRAM`, `RAM`), tekil hisse ve sektör kaldıraçlı ETF'leri (`SQQQ`, `TQQQ`, `TSLL`, `MSTU`, `MUU`, `MVLL`, `INTW`, `SHAZ`, `SKUU`, `SPCX`, `SMH`, `SOXS`, `EWY`, `SPY`, `QQQ`, `BITO`, `IBIT`) ve döviz/emtia/sabit-coin pariteleri **hem sembol listesi hem borsa `info` metaverisi (`underlyingType`, `underlyingSubType`, `assetClass`) üzerinden %100 dışlanır**.
   - `BTC`, `ETH`, `SOL`, `XRP`, `SUI`, `TAO`, `NEAR`, `INJ`, `AVAX`, `DASH`, `STX`, `AI`, `ONDO`, `AR`, `CELR`, `BONK`, `PEPE` dahil tüm gerçek kripto vadeli kontratları eksiksiz korunur.

2. **90 Saniye Başlangıç Isınması + Canlı `Flow Confidence v2` Giriş Kapısı (`src/main.py`, `src/trade_quality.py`):**
   - İlk `90` saniyede tüm evrenin OHLCV, MTF (`1h/4h`) ve canlı WebSocket defter/işlem akışı doldurulur; soğuk başlangıçta acele işlem açılmaz.
   - Her yeni adayda en az `60 sn` akış kapsaması, `>= 10` gerçek işlem, `>= $2,500` işlem hacmi, `<= 15 sn` taze 20 kademe emir defteri ve kanıt-ağırlıklı `adjusted_flow_score` onayı zorunludur.

3. **Alfabetik A-B-C Önyargısını Bitiren Likidite & Sinyal Öncelikli Tarama (`rank_symbols_for_scan`):**
   - Tarama sırası: **(1) Açık pozisyonlar -> (2) Makro liderler (`BTC`, `ETH`, `SOL`) -> (3) Canlı işlem hacmi + emir defteri derinliği + sinyal gücü en yüksek saf kripto pariteleri**.
   - Tarama paralelliği `8`'e çıkarıldı, tur bekleme süresi `300 sn`'den `90 sn`'ye indirildi.

4. **Dip/Tepe Tükenme Koruması + Tekil Akıllı Para Engeli + Yön Tavanı (`src/trade_quality.py`, `src/main.py`, `src/risk.py`):**
   - `RSI <= 27` (veya `RSI <= 30` & `MFI <= 18` veya dipte pozitif RSI uyumsuzluğu) varken likidasyon şelalesi yoksa geç `SHORT` açılmaz; simetrik olarak `RSI >= 73` tepesinde geç `LONG` açılmaz.
   - `DerivativesIntelEngine` üzerinde **`TOP_TRADER_LONG_PERAKENDE_SHORT`** yakalandığında `crowding_state == "DENGELI"` olsa bile perakende tuzağına karşı `SHORT` doğrudan engellenir (simetrik `LONG` koruması dahil).
   - Paper modda `paper_ayni_yon_max_pozisyon: 6` ve `paper_max_pozisyon: 10` ile tek yöne `11/11` yığılma kalıcı olarak engellenir.

5. **Akıllı Kâr Kilidi + Rehin Marj Kurtarıcı (`src/exit_rules.py`, `src/executor.py`, `config.yaml`):**
   - **Kâr tarafı:** `KÂR KOŞUSU` (`+%0.45` fiyat = `+$2.25` brüt / `+$1.75` netten itibaren order-flow dönüşüyle kâr hasadı) korunurken, pozisyon `+%0.90` fiyat (`+%9` ROE = `+$4.50` brüt) gördüğünde stop otomatik olarak `+%0.25` (komisyon üstü garanti net kâr) seviyesine kilitlenir.
   - **Zarar / Rehin marj tarafı (`stagnant_adverse_exit_reason`):** `18+` dakikadır ekside bekleyen ve birleşik skoru veya `5m Supertrend + canlı para akışı` ters yöne dönen (veya `25+` dakikada karşı agresif baskı yiyen) pozisyonlar `-%8` (`-$40`) felaket stopunu beklemeden küçük zararla kapatılır, `300 sn` molaya alınır ve `$50` marj yeni kazanan fırsatlar için serbest bırakılır.

6. **v7.5 Çapraz Ortak Kasa (`marj_modu: "cross"`) + WebSocket Anlık Para Girişi/Çıkışı Tetiği (`src/risk.py`, `src/executor.py`, `src/trade_quality.py`, `src/main.py`):**
   - **Ortak Futures Özsermaye Havuzu (`Bakiye + Açık K/Z`):** İzole `%60` (`$600`) marj kilidi tamamen kaldırıldı. Ortak kasa canlı olarak `Cüzdan Bakiyesi + Açık Pozisyon Kâr/Zararı` üstünden değerlendirilir; açık işlemler kâra geçtiği saniye kasa `$1,000` üstüne çıkar ve ekstra kapasite açar. Stopu kâr kilidine (`locked_profit`) giren pozisyonların aktif risk teminatı `$0` sayılır.
   - **Sıfır Kilitlenme için Akıllı Fırsat Takası (`firsat_takasi_aktif: true`):** Ortak havuz `%95` doluluğa ulaşsa bile yeni güçlü sinyal geldiğinde `8+ dk` durgun kalan en zayıf işlem otomatik takas edilerek taze fırsata anında yer açılır.
   - **Anlık Para Girişi / Para Çıkışı Tetiği (`anlik_akis_tetik_aktif: true`):** Tarama listesi en yüksek `|Alım $ - Satım $|` net para akışına göre sıralanır; ayrıca WebSocket'ten güçlü `PARA_GIRISI` / `PARA_CIKISI` (`|skor| >= 50`, `>= $2,500` hacim, `>= 60sn` kapsama) geldiği saniye sıra beklenmeden `< 1 sn` içinde `evaluate()` tetiklenir.

