# Futures bot teslim paketi — 29 Ekim 2026

## İçerik
- bot/futures_bot_v34: temel bot ve test kaynakları. H-01 açık; paper-only.
- bot/futures_bot_v35n: H-01 adayı, KABUL EDİLMEDİ. Canlı kullanmayın; 19 saniye için daha sıkı fail-closed testi başarısız, tam regresyon yapılmadı. tests/test_v35m_guvenlik_kapsam.py eski sayaç adını bekliyor.
- islem_ve_sinyal_kayitlari: seçili erişilebilir paper/smoke kayıtları; alt klasörler kaynak çalışmayı gösterir. tarihsel_analiz CSV'leri backtest/taramadır; gerçek işlem değildir.
- Her botun logs/ws_state.json ve erişilebilir işlem CSV'leri korunmuştur. 103 ultra-gevşetilmiş tanı sinyali v34_5dk_ultra_kayit/logs/ws_olay.csv içindedir; bunlar işlem değildir.

Çalışma alanında .db veya .sqlite veritabanı bulunmadı; oluşturulmadı. Gerçekten var olan CSV/JSON veri ve durum dosyaları tutuldu. Pakette geçmiş analiz çıktıları da kaynaklarıyla etiketlenmiştir. Bu paket bütün bilgisayar veya tüm eski sürümlerin yedeği değildir.

## Kurulum ve güvenlik
Python 3.10+ ve bot dizininde `pip install -r requirements.txt`; kaynak README'de eski sürüm notları bulunabilir. Hazır olduğunun veya Windows uyumluluğunun kanıtı değildir. Gerçek emir amacıyla kullanmayın; önce P0/H-01, ardından P1, sonra en az 300 ileriye dönük işlem. Eşikler kullanıcı onayı olmadan değişmemiştir.

Temiz paket, kaynak dosyalarının kopyasıdır; önbellekler, kilit dosyaları, geçmiş yedek kaynaklar, eski notlar, geçici loglar ve gizli anahtar dosyaları çıkarıldı. Kaynak klasörleriniz silinmedi. Ön-temizlik yedeği ayrı gönderildi.

## v35n kopyasındaki eksik ortak dosyalar

Teslim doğrulamasında v35n kaynak klasöründe eksik olan aşağıdaki ortak dosyalar, çalışır durumdaki v34 kaynaklarından YALNIZCA bu ZIP içerisindeki v35n kopyasına tamamlandı. Orijinal v35n klasörüne dokunulmadı. Bu onarım v35n H-01 kabulü veya davranış regresyonu değildir.

- `data/fixtures/okx_BTC-USDT-SWAP_1m_real_snapshot.csv`
- `data/fixtures/synthetic_btc_1m.csv`
- `data/fixtures/okx_ETH-USDT-SWAP_1m_real_snapshot.csv`
- `data/extended/__init__.py`
- `data/extended/markprice_feed.py`
- `data/extended/funding_events.py`
- `data/extended/funding_feed.py`
- `data/extended/_http.py`
- `data/extended/oi_feed.py`
- `scripts/okx_replay/replay_flow.py`
- `scripts/okx_replay/fetch_okx_replay.py`
