# Crew Projesi ↔ Bot ZIP Arasındaki Farklar (ve kapatılma durumu)

Bu doküman, `crew/` altındaki **CrewAI üretim hattının** (`agents.yaml` +
`tasks.yaml`) vaat ettiği çıktılar ile `futures_bot/` **fiili teslimatı**
arasındaki farkı kayıt altına alır.

---

## 1. Kök sorun

Crew projesinin önceki sürümünde `tasks.yaml` şunu söylüyordu:

> "Real file writing and ZIP creation tools are NOT available in this environment.
> Do not present the Crew project ZIP as the bot source code ZIP.
> Deliver all files as plain text with path labels: `# === FILE: ...`"

**Sonuç:** Crew, "bot" değil **botun metni** üretiyordu. Teslim edilen ZIP ise
Crew projesinin kendisiydi; içinde çalışan bot kodu yoktu. Kullanıcı her
seferinde kodu metinden kopyalamak zorunda kalıyordu.

## 2. Fark tablosu

| # | Crew görevi | Vaat edilen çıktı | Önceki ZIP'te durum | Şimdi |
|---|---|---|---|---|
| 1 | `research_exchange_apis...` | Veri/API araştırma raporu | ❌ Yok | ✅ `docs/VERI_ARASTIRMA_RAPORU.md` (gerçek HTTP sonuçlarıyla) |
| 2 | `develop_..._source_code` | Phase A–D kaynak kod | ⚠️ Sadece prompt metni | ✅ `futures_bot/` (35 dosya, 3.909 satır) |
| 3 | `design_backtest_framework...` | `backtests/{engine,walk_forward,ablation,report}.py` | ❌ Yok (yalnızca arayüz) | ✅ Dördü de yazıldı + çalışır |
| 4 | `write_..._pytest_test_suite` | Tam pytest paketi | ❌ Yok | ✅ 11 dosya, **119 test**, hepsi geçiyor |
| 5 | `security_audit_and_final_...` | 13 kategori denetim + 8 bölümlü Türkçe rapor | ❌ Yok | ✅ `docs/GUVENLIK_DENETIMI.md` + `docs/TESLIM_RAPORU.md` |
| 6 | Dosya üretimi | Diske yazılan gerçek dosyalar | ❌ Sadece metin | ✅ `FileWriterTool` eklendi, görev metinleri güncellendi |
| 7 | `user_preference.txt` | Kullanıcı tercihleri | ⚠️ `John Doe / San Francisco` yer tutucusu | ✅ Temizlendi (kişisel veri yok) |
| 8 | Model adı | Geçerli bir LLM | ⚠️ `openai/gpt-5.6-luna` (var olmayan model) | ✅ `openai/gpt-4o-mini` (değiştirilebilir) |

## 3. Yapılan düzeltmeler (crew tarafı)

### 3.1 `FileWriterTool` eklendi
`crew/src/binance_okx_paper_futures_bot/tools/file_writer.py`

- Ajan dosyayı **gerçekten diske** yazar (varsayılan `output/` dizini).
- Path traversal koruması: mutlak yol ve `../` reddedilir.
- Her yazmada satır/bayt raporu döner.

### 3.2 `crew.py` yeniden yazıldı
- Dosya üreten dört ajana (geliştirici, QA, denetçi, veri araştırmacısı)
  `FileWriterTool` verildi.
- Var olmayan model adı düzeltildi; model tek yerden (`MODEL`) değiştirilebilir.
- Gereksiz `max_reasoning_attempts`, `max_rpm=None` gibi gürültü temizlendi.

### 3.3 `tasks.yaml` güncellendi
- Dört ayrı yerdeki "kodu düz metin olarak dök" talimatı, "dosyayı yaz"
  talimatına çevrildi.
- "ZIP / FILE PRODUCTION NOTE" → "DOSYA ÜRETİM NOTU": ajan dosyayı yazar,
  operatör `output/` klasörünü zipleyip GitHub'a atar.

### 3.4 Kişisel veri temizliği
`knowledge/user_preference.txt` içindeki `John Doe / San Francisco` yer
tutucusu kaldırıldı. Bu dosya ajan bağlamına girdiği için gerçek bir
sızıntı riskiydi.

## 4. Hâlâ eksik olanlar (dürüst liste)

| Konu | Durum | Neden |
|---|---|---|
| Crew'in **kendisi** çalıştırılmadı | ⚠️ | `OPENAI_API_KEY` yok; crew çalıştırmak ücretli API çağrısı gerektirir. Bot kodu crew'e **bağımlı olmadan** elle üretildi. |
| Funding / OI / mark price | ❌ | Public uç noktaları bu projede doğrulanmadı → `DataUnavailableError`. Muhasebe funding **hariç**. |
| Binance canlı doğrulaması | ❌ | Ortamdan 451 dönüyor; Binance parser'ı yalnızca mock ile test edildi. |
| Sembol çakışması filtresi | ⚠️ | Kural belgelendi, canlı fiyat karşılaştırması Binance engeli nedeniyle yapılamadı. |
| Gerçek para / canlı emir | 🚫 | **Tasarım gereği yok.** `--mode live` → `exit 1`. |
| 30+ işlemli Sharpe | ⚠️ | 1 saatlik oturumda 30 kapalı işlem oluşmaz; Sharpe bastırılmış kalır. |

## 5. Çalıştırma sırası (crew kullanılacaksa)

```bash
cd crew
pip install "crewai[tools]"
echo "OPENAI_API_KEY=..." > .env        # kendi anahtarınız
crewai run                              # output/ altına dosyalar yazılır
```
Crew bittiğinde `output/` klasöründe gerçek dosyalar olur; bunlar
`futures_bot/` ile karşılaştırılıp birleştirilebilir.
