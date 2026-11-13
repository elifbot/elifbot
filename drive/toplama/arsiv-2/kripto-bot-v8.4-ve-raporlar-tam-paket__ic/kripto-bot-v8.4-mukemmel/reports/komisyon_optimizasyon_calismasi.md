# 🧾 Kripto Bot v8.3 — Ayrı Komisyon Ücretleri Analizi & Optimizasyon Çalışması

**Sorumlu YZ Yardımcıları:** `Claude Sonnet 5.5` (Komisyon & Net-Edge Baş Denetçisi) • `GPT-5.6 Codex` (Akıllı Maker/Taker İcra Mühendisi) • `GLM-5.3 Coding` (Anti-Churn Soğuma Kilidi)

---

## 1. Sorunun Tespiti: Canlı Borsa Verilerinde Komisyon Neden Kârı Yedi?

15 dakikalık (`v8.0`, 13 işlem) ve 10 dakikalık (`v8.2`, 11 işlem) **gerçek canlı borsa oturumlarında** (`165,248` canlı OKX WS + Binance `aggTrade` işlemi) komisyon verileri incelendiğinde kritik bir bulgu ortaya çıktı:

| Oturum | İşlem Sayısı | Brüt Fiyat K/Z | Ödenen Toplam Komisyon | Net K/Z | İşlem Başı Ortalama Ücret |
|---|---:|---:|---:|---:|---:|
| **15dk Canlı Test (`v8.0`)** | `13` | `-$17.51` | **`-$11.78`** | `-$29.27` | `$0.906` / işlem |
| **10dk Canlı Test (`v8.2`)** | `11` | **`+$9.38`** *(8/11 brüt kârlı!)* | **`-$10.70`** *(Brüt kârın %114'ü!)* | `-$1.33` | `$0.973` / işlem |
| **Toplam (`24` Canlı İşlem)** | `24` | `-$8.13` | **`-$22.48`** | `-$30.60` | **`$0.937` / işlem** |

> **Çarpıcı Kanıt:** `10DK_V82` testinde bot **10 dakikada `+$9.38` brüt kâr üretti** (seans içi kapanan **8 işlemin 8'i de `%100` brüt kârlıydı**: `+$15.63` brüt!), ancak **`-$10.70` komisyon** ödendiği için net bakiye `-$1.33` oldu. Üstelik `#6 BZ/USDT` (`+$0.47` brüt → `-$0.53` net) ve `#7 ZEC/USDT` (`+$0.89` brüt → `-$0.12` net) fiyat yönünü doğru bildiği halde **yalnızca komisyon yüzünden net zarar yazdı!**

---

## 2. Kod Seviyesinde Bulunan 4 Kök Neden

1. **`paper_realistic` Modunda Maker İcra Atlaması (`src/exchanges.py:1100-1105`)**:
   `Executor` emir tipini `order_type="maker"` (`prefer_maker=True`) göndermesine rağmen, `paper_realistic=True` olduğunda kod doğrudan `await self.market_order(...)` çağırarak her girişte `%0.02` Maker (`$0.20`) yerine **`%0.05` Taker (`$0.50`)** komisyon kesti (`2.5 kat` fazla maliyet!).
2. **Kâr Kilidi ve TP Çıkışlarında Zorunlu Market Emri (`src/executor.py:1833`)**:
   Acil zarar durdurma olmayan **Kâr Kilidi (`KÂR KİLİDİ STOPU`) ve Kâr Al (`TP`)** çıkışlarında bile her zaman `%0.05` Taker Market (`$0.50`) kullanıldı; böylece gidiş-dönüş komisyon **`$0.40` yerine `$1.00`** oldu.
3. **`exit_fee_pct = 0.0` Eksikliği ve Brüt MFE Kilidi (`src/risk.py:650-658`)**:
   `Position` oluşturulurken tahmini çıkış komisyonu (`exit_fee_pct`) sıfır kaldığı için `net_breakeven_price` çıkış ücretini hesaba katmadı ve `mfe_lock_min_usdt = $1.20` brüt kârda erken tetiklenip `$1.00` gidiş-dönüş ücret düşüldüğünde işlemi net zararla kapattı.
4. **Aynı Sembolde Aşırı İşlem / Churn (`BZ` 3 kez, `ZEC` 3 kez)**:
   10 dakikada sadece `BZ` ve `ZEC` üzerinde 6 işlem açılıp `$6.00` komisyon yakıldı.

---

## 3. v8.3 Komisyon Optimizasyon Mimarisi (`src/commission_optimizer.py`)

`$100 Marj × 10x Kaldıraç = $1,000` pozisyon büyüklüğü için yapılan mühendislik iyileştirmeleri:

| İcra Senaryosu | Giriş Ücreti | Çıkış Ücreti | Toplam Gidiş-Dönüş | İşlem Başı Tasarruf |
|---|---:|---:|---:|---:|
| **Eski (`v8.0 / v8.2` Taker + Taker)** | `$0.50` (`%0.05`) | `$0.50` (`%0.05`) | **`$1.00`** (`%0.10` = Marjın `%1.0`'i!) | Baz |
| **v8.3 Kazanan İşlem (Maker Giriş + Maker Kâr-Al)** | **`$0.20`** (`%0.02`) | **`$0.20`** (`%0.02`) | **`$0.40`** (`%0.04` = Marjın `%0.4`'ü) | **`-%60.0` (`+$0.60` / işlem)** |
| **v8.3 Acil Stop İşlemi (Maker Giriş + Taker Acil Stop)** | **`$0.20`** (`%0.02`) | `$0.50` (`%0.05`) | **`$0.70`** (`%0.07`) | **`-%30.0` (`+$0.30` / işlem)** |

### Devreye Alınan 4 Kod Zırhı:
1. **Gerçek Canlı Tahta (`bid`/`ask`) Pasif Maker Giriş (`ExchangeManager.execute_entry`)**: Canlı makas `<= %0.08` olduğunda alımda canlı `bid`, satışta canlı `ask` seviyesinden `maker_post_only` (`%0.02` = `$0.20`) icra edilir.
2. **Akıllı Çıkış Yönlendiricisi (`ExchangeManager.execute_exit`)**:
   - `KÂR KİLİDİ STOPU`, `KAR AL`, `TP`, `ÇAPRAZ KURTARMA` → Dar makasta **`%0.02` Reduce-Only Maker (`$0.20`)**
   - `STOP LOSS`, `ZAMAN ÇÜRÜMESİ`, `SİGORTA`, `TASFİYE` → Sıfır gecikmeli **`%0.05` Taker Market (`$0.50`)**
3. **Ücret-Dahil 3 Kademeli MFE Kâr Kilidi (`RiskManager.update` + `exit_fee_pct=0.05`)**:
   - MFE kilidi asla `giriş_ücreti + tahmini_çıkış_ücreti + net_kâr_tamponu ($0.35)` altına yerleşmez; **kâr kilidinden net zararla kapanma matematiksel olarak imkânsız hale getirildi**.
   - Koşucu trendlerde kilit oranı otomatik büyür: `MFE >= $3.20` için **`%64`**, `MFE >= $6.00` için **`%76`** kâr kilidi!
4. **Minimum Beklenen Hareket Çarpanı (`>= 3.0x`) & Churn Soğuması (`65sn / 160sn`)**: Beklenen ATR hareketi gidiş-dönüş maliyetin 3 katından küçükse giriş reddedilir.
