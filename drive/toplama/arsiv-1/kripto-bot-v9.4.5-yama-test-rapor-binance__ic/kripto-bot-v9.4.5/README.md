# Kripto Bot v9.4.5 — Faz 1.5 / PAPER

Giriş, çıkış, strateji, ATR/risk, maker ve muhasebe kuralları değişmedi.
Altı ana arka plan görevi aktif/drenaj boyunca denetlenir. Beklenmedik exception,
normal return veya cancellation: yeni girişler kesilir, runner FAILED kapanır;
pozisyonlar zorla kapatılmaz ve supervisor otomatik restart yapmaz.
Sinyal olmaması görev ölümü değildir: evaluation_calls ilerlemesi (30s) ve
başarıyla tamamlanan strateji çevrimi heartbeat'i (15s) ayrı HTTP503 alarmlarıdır.
Writer lease yenileme hatası artık yutulmaz; görev hatasına yükseltilir.

Süre/drenaj monotonic saatlidir. Poll >5s veya wall/mono farkı >2s süreklilik
olayıdır; normal süre bitişi DISCONTINUOUS olarak raporlanır, düz COMPLETED değil.
Duvar saati elapsed_sec eski alanı korunur; elapsed_monotonic_sec ayrıca vardır.
İç gözlemci tüm makine durmuşken kayıt yazamaz; dönüşte boşluğu kaydeder. Güç
kesilirse final yazması garanti değildir. Tam uptime garantisi yok.

poll/saat olayları, strategy_prepare_sync, strategy_cycle_including_awaits,
analytics_snapshot_including_ledger ve health_render süreleri raporlanır.
Bunlar nedensel CPU profili veya büyük gerçek defter yük testi değildir.

## Kontrol
python -m pytest -q
python -m scripts.check_v945_integrity

Eski v944/v943 doğrulayıcılar tarihsel sürümler içindir. Güncel rapor
reports/v945/FINAL_REPORT.md ve RELEASE_STATUS.json. Eski reports/v94/v941/v943/v944
belgeleri tarihsel olarak korunur. Binance bağlantısı src/live_runner.py içinde
_binance_single_ws ve binance_ws_loop, URL ayırımı src/feed_health.py içindedir.
Ayrı bir Binance-only strateji/yapılandırma oluşturulmadı.

Bridge/Compose ağı, thread-token yarışı, büyük gerçek ledger yükü, tam transitif
lock, unique_signal_count/olgun kohort altyapısı tamamlanmış değildir.
Gerçek borsa emri ve gerçek para onayı yok. Önceki negatif araştırma hükmü değişmedi.
