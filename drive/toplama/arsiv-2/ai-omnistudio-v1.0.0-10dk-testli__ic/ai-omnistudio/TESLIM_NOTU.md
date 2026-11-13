# AI OmniStudio v1.0.0 — Teslim Paketi

**Teslim tarihi:** 3 Kasım 2026
**Hazırlanan hesap:** omeracar56@gmail.com
**Mod:** PAPER — gerçek piyasa verisi, borsaya emir YOK

---

## Paket içeriği

| Dosya | İçerik |
|---|---|
| `ai-omnistudio-v1.0.0-kaynak-kod.zip` | Tüm kaynak kod, testler, config, pano, belgeler |
| `ai-omnistudio-10dk-kanit.zip` | 10 dakikalık koşunun ham kanıtları |
| `TESLIM_NOTU.md` | Bu dosya |

## Kurulum

```bash
unzip ai-omnistudio-v1.0.0-kaynak-kod.zip
cd ai-omnistudio
pip install -r requirements.txt

# 1) Ağsız bütünlük kontrolü
python3 cli/main.py check

# 2) Testler (150 test, ağ gerektirmez)
python3 -m pytest -q

# 3) 20 YZ sağlayıcısının durumu
python3 cli/main.py providers

# 4) 10 dakikalık doğal PAPER koşusu
python3 cli/main.py run --config configs/natural-10m.json

# 5) Canlı pano
python3 web/server.py --port 8080
```

## YZ anahtarları (opsiyonel)

```bash
cp .env.example .env
# .env içine anahtarlarınızı yazın, örn:
# OPENROUTER_API_KEY=sk-or-...
# OPENAI_API_KEY=sk-...
```

Anahtar yoksa konsey `RULE_BASED_QUANT` modunda çalışır ve bunu çıktıda
**açıkça belirtir**. Sahte YZ cevabı üretilmez. Anahtar girildiğinde otomatik
olarak `LIVE_LLM` moduna geçer.

## Config profilleri

| Dosya | Profil | Kullanım |
|---|---|---|
| `configs/natural-10m.json` | `natural` | **10 dk doğal koşu** — üretim eşikleri |
| `configs/default.json` | `natural` | Genel doğal koşu |
| `configs/quick-test.json` | `natural` | Hızlı duman testi |
| `configs/lifecycle-diagnostic.json` | `lifecycle-diagnostic` | **Yalnız** aç/kapat yolu sınamak için |

> `lifecycle-diagnostic` profilinde eşikler gevşetilir. Bu profilin çıktısı
> `evidence_class: LIFECYCLE_DIAGNOSTIC_NOT_NATURAL` olarak işaretlenir.
> İşlem sayısı/PnL'i strateji kanıtı olarak **kullanılamaz**.

## Bu sürümde ne var

### Arşivden devralınan sağlam davranışlar
- Kör fail-open yasağı (v9.1)
- Genişlik kapısının bağlamdan bağımsızlığı (v20 düzeltmesi)
- Mum başına tek deneme hakkı
- Dedektörün piyasa yönünü döndürmesi sözleşmesi
- Tekrar sayacının ekonomik retten ayrılması (v9.4.4)
- Görev ölümünde giriş kesme, pozisyonu zorla kapatmama (v9.4.5)
- Monotonic süre + boşlukta DISCONTINUOUS
- Writer lease hatasının yutulmaması
- Eski DB'nin devralınmaması
- Kabul ölçütlerinin koşudan önce beyanı

### Yeni çözülen işler
| İş | Yöntem |
|---|---|
| Fiyat araması O(n) darboğazı | Ön-ek maksimum + ikili arama → O(log n) |
| Hacim oranı döngüsü | Kayan pencere toplamı → amortize O(1) |
| Genişlik tekrar maliyeti | İndeksli arama + 250 ms önbellek |
| Tekil karar kimliği | `signal_id` + `decision_id` + `closed_bar_key` |
| 20 gerçek YZ entegrasyonu | 4 protokol adapter + devre kesici + quorum |

Tüm optimizasyonlar **eşdeğerlik testiyle** korunur; eski doğru yola düşüş
(fallback) vardır. Tick atlanmaz, eşik değişmez.

## Güvenlik

- LIVE mod `LiveTradingBlocked` istisnasıyla **kilitli**.
- Config doğrulayıcı `mode: LIVE`'ı baştan reddeder.
- YZ anahtarları rapora, panoya, config dökümüne **yazılmaz**.
- Pano **salt okunurdur**; yazma/emir ucu yoktur.
- `PaperExecutor` içinde borsaya yazan hiçbir ağ kodu yoktur.

## Dürüstlük sınırları

1. **Kârlılık iddiası yoktur.** Arşivin v9.4.1 hükmü (strateji komisyon
   öncesi net negatif) bu sürümde değişmedi.
2. Küçük PAPER örneklemi yürütme güvenilirliği veya kârlılık kanıtı değildir.
3. Açık unrealized **gerçekleşmiş kâr değildir**; çıkış ücretleri düşülmemiştir.
4. Stop mesafesi **maksimum zarar garantisi değildir** (gap/slippage hariç).
5. Maker dolumu iyimser olabilir; gerçek kuyruk önceliği bilinmez.
6. **Uptime garantisi yoktur.** Bütün VM durduğunda gözlemci de durur.
7. Ölçümler kapsayıcı duvar süresidir, CPU profili değildir; iç içe ölçümler
   toplanmaz.
8. Gerçek YZ API çağrısı **henüz yapılmadı** (anahtar yok). Adapter'lar
   yazıldı; anahtar girildiğinde ilk canlı doğrulama gerekir.

## Yapılmayanlar

- Uzun süreli (saatler/günler) bellek soak testi
- Büyük gerçek defter yük testi
- Docker/Compose dağıtım doğrulaması
- Tam transitif bağımlılık kilidi
- Eşleştirilmiş kontrollü performans kıyası
- 5,22 s tarihsel boşluğun kök nedeninin kanıtlanması (hâlâ açık)

## Dosya bütünlüğü

Paket SHA-256 değerleri mail gövdesinde verilmiştir. İndirdikten sonra:

```bash
sha256sum ai-omnistudio-v1.0.0-kaynak-kod.zip
```

çıktısını mail'deki değerle karşılaştırın.