# ACAR FUTURES APEX v1.1 — değişiklikler

- Sabit maksimum pozisyon adedi kaldırıldı. `--max-positions` eski komut satırlarıyla uyumluluk için kabul edilir ancak uygulanmaz. Yeni pozisyon açılışını kullanılabilir bakiye/teminat ve işlem risk hesabı sınırlar.
- Günlük 100 USDT zarar circuit breaker kaldırıldı. Günlük PnL, yeni işlemlerin otomatik kapısı değildir.
- PAPER başlangıcında işlem profili konsola yazdırılır: bakiye, 50 USDT teminat, 10x, 500 USDT azami nominal, 25 USDT pozisyon risk bütçesi, sınırsız pozisyon adedi ve günlük zarar freni kapalı durumu.
- Windows başlatıcısı sabit pozisyon adedi argümanını kullanmaz.
- Regresyon testleri yeni kurallara göre güncellendi.

## Doğrulama

`python -m pytest -q` sonucu: **102 passed**.

## Sınırlar

- 25 USDT, pozisyon başına risk bütçesidir; gerçekleşen zararın her koşulda bu tutarı aşmayacağı garantisi değildir.
- Pozisyon adedi sınırsızdır, fakat kullanılabilir teminat sınırsız değildir. 1.000 USDT başlangıç bakiyesiyle bot sınırsız sayıda pozisyonu aynı anda açamaz; serbest bakiye ve komisyon ihtiyacı doğal sınırdır.
- Paket PAPER ONLY'dir; gerçek borsaya emir göndermez. Kârlılık kanıtı değildir.
- 1h/4h trend doğrulaması, funding işlem kapısı, tüm portföye korelasyon filtresi, ana broker maker kuyruğu entegrasyonu ve uzun dönemli çoklu coin walk-forward doğrulaması tamamlanmış değildir.
