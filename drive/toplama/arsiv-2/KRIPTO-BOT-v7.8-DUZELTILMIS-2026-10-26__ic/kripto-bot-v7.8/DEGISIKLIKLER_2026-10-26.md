# KRIPTO-BOT v7.8 — Çalışma Süresi ve Bildirim Düzeltmesi

Tarih: 26 Ekim 2026

## Düzeltilen sorunlar

1. **Yanıltıcı bildirim durumu kaldırıldı.** Telegram/WhatsApp artık yalnız `config.yaml` boole değerine göre “aktif” sayılmıyor. Gerçek `.env` kimlik bilgileri doğrulanıyor.
2. **Fail-closed bildirim ön kontrolü eklendi.** `REQUIRE_NOTIFICATIONS=1` iken etkin bir kanal eksikse bot borsaya bağlanmadan ve işlem açmadan hata verir.
3. **Gerçek açılış teslimat testi eklendi.** `NOTIFICATION_STARTUP_TEST=1` iken Telegram ve WhatsApp'a test mesajı gider; sonuç SQLite `notification_preflight` kaydına yazılır. Teslimat başarısızsa işlem başlamaz.
4. **Bağımsız bildirim testi eklendi.** `python deploy/bildirim_testi.py` stratejiyi çalıştırmadan iki kanalı test eder.
5. **SIGTERM/SIGINT güvenli kapanışı eklendi.** Kapanış isteğinin nedeni hem SQLite'a hem `reports/termination_requested.json` dosyasına yazılır.
6. **Paper pozisyon güvenliği eklendi.** Kontrollü/istisnai kapanışta yeni girişler durdurulur, açık paper pozisyonları son bilinen fiyatla kapatılır ve ara checkpoint yazılır.
7. **Çıkış kanıtı eklendi.** Her kontrollü çıkışta `reports/last_exit.json` oluşur. Süreç yok olmuş ve bu dosya oluşmamışsa SIGKILL/host kaybı gibi Python dışında bir sonlandırma kuvvetlidir.
8. **Systemd davranışı düzeltildi.** `Restart=on-failure`: çökme/SIGKILL sonrası yeniden başlar; bir saatlik planlı oturum `exit 0` ile bittiğinde tekrar başlamaz. Kapanış zaman aşımı 90 saniyedir.
9. **Sağlık alarmı sıkılaştırıldı.** Heartbeat 90 saniyeyi geçtiğinde `/health` artık 503 `stale_heartbeat` döndürür.

## Doğrulama sonucu

- `python -m pytest -q tests`: **141 geçti**
- `python test_hizli.py`: **101/101 geçti**
- Eksik kimlik bilgisi senaryosu: bot **işlem açmadan** exit code 1 ile durdu ve eksik Telegram/WhatsApp alanlarını açıkça bildirdi.
- `deploy/bildirim_testi.py`: mevcut eksik kimlik bilgileriyle exit code 2 ve iki kanal için `EKSİK` sonucu verdi (beklenen fail-closed davranış).

## Bir saatlik kabul testi öncesi zorunlu adımlar

1. `.env` içine gerçek Telegram ve WhatsApp bilgilerini girin; `.env` dosyasını paylaşmayın veya Git'e koymayın.
2. `python deploy/bildirim_testi.py` çalıştırın. İki kanal da `BAŞARILI` olmalı ve iki fiziksel mesaj görülmelidir.
3. Botu geçici terminal/Arena arka planı yerine kalıcı Ubuntu/Debian hostta systemd altında çalıştırın.
4. `.env` içine `PAPER_SESSION_HOURS=1` ekleyin veya systemd `Environment=PAPER_SESSION_HOURS=1` kullanın.
5. Bir saat sonunda: açık pozisyon 0, nihai rapor mevcut, mesaj teslim edilmiş ve `reports/last_exit.json` nedeni `scheduled_paper_session_complete` olmalıdır.

## Bilinen sınır

`SIGKILL` ve fiziksel host kaybı Python tarafından yakalanamaz. Bunlar için systemd yeniden başlatması ve dış `deploy/nobetci.sh` denetimi gerekir. GitHub zorunlu değildir.
