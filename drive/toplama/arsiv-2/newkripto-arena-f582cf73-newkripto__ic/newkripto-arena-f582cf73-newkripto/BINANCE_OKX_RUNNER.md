# Binance + OKX aynı oturum: runner gereksinimi

## Yerel bilgisayarsız seçenek: GitHub Codespaces

Codespaces, tarayıcıda çalışan ücret/kotası GitHub hesabına bağlı bir bulut Linux makinesidir. Bu repository'deki `.devcontainer` profili Futures erişimini ve Actions runner indirmesini otomatikleştirir; Codespaces kullanımı GitHub hesabının kotasına/faturalandırmasına tabidir.

1. Şu bağlantıyı açın: <https://codespaces.new/omeracar56/kripto-bot/tree/arena/787d4de8-kripto-bot>
2. **Branch** `arena/787d4de8-kripto-bot`, **Dev container** `Binance OKX Paper Runner`, makine en küçük seçenek olmalı. İlk deneme için **Region: West Europe** seçin ve **Create codespace** düğmesine basın. Bölge erişimi garanti değildir; otomatik kontrol bunu doğrular.
3. Kurulum bitince tarayıcıdaki VS Code terminalinde `cat ~/exchange-preflight.txt` çalıştırın. `RESULT: PASS` yoksa runner yapılandırılmaz; Codespace'i silip **Southeast Asia** bölgesiyle yeniden deneyin.
4. `RESULT: PASS` ise repository kökünde `bash .devcontainer/configure-runner.sh` çalıştırın. Script geçici runner registration token'ını gizli sorar. Token repository'nin **Settings → Actions → Runners → New self-hosted runner → Linux/x64** sayfasından alınır; sohbete veya dosyaya yazılmaz.
5. Script runner'ı servis olarak başlatır. GitHub runner listesinde `binance-futures-runner = Idle` olduktan sonra 120 dakikalık iki-borsa işi başlatılabilir. Codespace'in oturum boyunca çalışır/uyanık kalması gerekir.

## Ölçülen engel

Resmî USDⓈ-M Futures ucu `https://fapi.binance.com/fapi/v1/exchangeInfo` üç standart GitHub runner işletim sisteminde de HTTP **451** döndürdü. Aynı matriste OKX swap kataloğu HTTP 200 ve 522 pariteydi. Makine tarafından okunan kayıt: `analysis/connectivity/latest.json` (run `40073629443`).

Bu nedenle `ubuntu-latest`, `windows-latest` veya `macos-latest` arasında geçiş yapmak Binance bölgesini değiştirmiyor. Spot `api.binance.com` veya spot market-data uçlarına dönmek çözüm değildir; bot yalnız resmî USDⓈ-M Futures REST/WS uçlarını kullanır.

## Gerekli kullanıcı altyapısı

Binance USDⓈ-M Futures hizmetinin bulunduğu bir bölgede, kullanıcıya ait bir Linux makine gerekir. Makinenin şu adreslere giden HTTPS ve WebSocket bağlantısı olmalıdır:

- `fapi.binance.com`
- `fstream.binance.com`
- `www.okx.com` / `ws.okx.com`

GitHub arayüzünde:

1. Repository → **Settings → Actions → Runners → New self-hosted runner** yolunu açın.
2. GitHub'ın gösterdiği kurulum komutlarını bu makinede uygulayın. Runner kimlik bilgilerini sohbete veya Git dosyalarına yazmayın.
3. Kurulum sırasında ek etiket olarak **`binance-futures`** verin. GitHub'ın `self-hosted`, `linux` ve mimari etiketleri de bulunmalıdır.
4. Runner'ı repository erişimi olacak şekilde çalıştırın ve **Actions → paper-live → Run workflow** ekranından:
   - `duration_minutes`: **120**
   - `runner_label`: **binance-futures**
   seçin.

Workflow, 120 dakikalık oturumu başlatmadan önce her iki borsanın Futures kataloğunu yeniden ister. Binance veya OKX kataloğu yoksa iş temiz kasa açmadan başarısız olur. Başarılı katalog tek başına yeterli kabul edilmez; nihai raporda OHLCV, WS trade/book ve gerçekleşen paper-fill sayaçları borsa bazında ayrıca bulunur.

## Güvenlik ve raporlama

- Mod her zaman **paper**: 100.000 USDT sanal kasa, işlem başına 50 USDT marj, 10x; gerçek emir yok.
- Telegram token/chat ID yalnız GitHub Secrets üzerinden gelir.
- Oturum sonunda yeni girişler durur, açık pozisyonlar kontrollü kapatılır ve brüt/net K/Z, ücret, funding, borsa, çıkış modülü ve giriş bileşeni tabloları yazılır.
- Artifact: `paper-session.log`, `gunluk_*.txt`, `oturum_analizi_*.json`, `islem_gecmisi_*.json`.
- İkinci job bu dosyaları maskeler ve `analysis/run_<run-id>/` altında GitHub dalına kaydeder; `run.json` içindeki `paper_job_result` başarı/başarısızlığı ayrıca doğrulanır.
- Tek oturumluk bileşen ilişkileri nedensellik kanıtı veya otomatik parametre değişikliği gerekçesi değildir.
