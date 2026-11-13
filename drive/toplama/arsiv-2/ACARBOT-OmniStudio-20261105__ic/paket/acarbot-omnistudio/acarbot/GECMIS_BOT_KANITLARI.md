# Maildeki eski botların incelenmesi

## Kaynaklar ve bütünlük
- v8.4 arşivindeki `scanner/binance_flow.py`: Binance'in kamu USD-M katalog yolunda `https://www.binance.com/fapi/v1/exchangeInfo`, üretim aggTrade akışında `wss://fstream.binance.com/market/stream?streams=` kullanıyor. Aynı arşivde OKX swap data/stream modülleri var.
- Mail: `Kripto Bot v9.5.3 — saat kesintisinde ACTIVE kalma düzeltmesi`, `v9.5.3-SUREKLILIK-DUZELTME-KOD-TEST-VE-GOZETIM.zip`, SHA-256 `ed2172c8b5cdc9892217753135c32ba8e1c0ba3c2d5727695ae0f2fdbc74827e`. SHA-256 ve ZIP CRC doğrulandı; iç kaynak ZIP'i güvenli ayrı klasöre açıldı.
- v9.5.3 `src/exchanges.py`: `BINANCE_PUBLIC_WWW=1` opt-in ile fapi public URL'lerini `www.binance.com` alanına çeviriyor; private/emir URL'lerini çevirmiyor. `scanner/ws_scanner.py` gerçek vadeli WebSocket'i kullanıyor.
- v9.5.3 `src/futures_catalog.py` ve `scanner/universe.py`: katalog **USDT lineer perpetual** ile sınırlandırılmış; saf kripto ve ek filtreler var. Yani iki borsa bağlantısı gerçektir ama tüm inverse/vadeli/USDC kontratlarda işlem desteği kanıtlanmaz.
- Maildeki `v9.5.3-GOZETIMLI-10DK-SONUC-VE-HAM-KANIT.zip` SHA-256 `4dc4d7e5bec1051bc63df38a3d606e128f3c3e1b2e8f13fc67e8412faecc84cc`, SHA ve ZIP CRC doğrulandı. İç rapor: 600,631798 sn, sıfır PAPER emir/dolum; 5 sinyal eski mum nedeniyle reddedildi. Bu veri kârlılık veya doğal dolum kanıtı değil. Eski e-postadaki 271 test sonucu tarihsel beyandır, burada yeniden çalıştırılmış olarak sunulmaz.

## V10'a uygulanan düzeltme
Eski kodun kanıtladığı Binance kamu `www` veri yolu USD-M için kullanıldı. COIN-M kamu veri yolu burada ayrıca test edildi. `contractStatus` alanı COIN-M için doğru okunacak şekilde düzeltildi; USD-M için `status` korunuyor. Bu çalışma özel anahtar, özel hesap veya emir çağrısı yapmaz. `fapi.binance.com` ve `dapi.binance.com` doğrudan alanları bu ortamda 451 döndürdü; Binance'in genel API dokümanında listelenen asıl uçlar bunlardır. `www` kamu yolu gözlemde çalışmış olsa da Binance tarafından belgelenmiş standart futures API temeli olarak doğrulanmış değildir; kalıcılığı ve kullanım uygunluğu garanti edilmez. Testnet ya da spot futures yerine geçirilmez.

Son test ayrıntısı `GECMIS_BOT_DUZELTME_RAPORU.md`. Binance/OKX farklı sözleşme türleri için işlem/PnL uygulaması, sürekli tüm evren tazeliği ve gerçek para yetkisi tamamlanmış değildir.
