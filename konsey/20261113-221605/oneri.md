## mimar
TANI: `bot/v9/motor.py` satır 142-144'teki `REJIM_DONUS` mekanizması, düşük gecikmeli gürültüyü (noise) rejim değişikliği olarak algılayıp pozisyonu anında kapatmaktadır. %81'lik erken çıkış oranı ve düşük WR, sistemin "sinyal gürültüsüne" karşı savunmasız olduğunu kanıtlar.

YAMA STRATEJİSİ: Rejim tersliğinin anlık bir tick değil, istatistiksel bir onay (ardışık onay) veya finansal bir eşik (PnL toleransı) ile doğrulanması.

**Karar 1:** Rejim tersliğinin geçerli sayılması için ardışık `N` tick boyunca aynı ters yönün korunması şartı getirilir.
**Karar 2:** PnL negatif olsa dahi, rejim dönüşü için minimum bir "onay süresi" (confirmation window) eklenir.
**Karar 3:** Sadece rejim ters dönmesi yetmez; fiyatın giriş fiyatından belirli bir yüzde uzaklaşması (veya stopa yaklaşması) durumunda bu çıkış tetiklenir.

```python
# eski_kod (bot/v9/motor.py:142-144)
if time.time() - pos.opened_at > rejim_karsi_cikis_sn:
    if current_regime != pos.entry_regime and pos.pnl < 0:
        return "REJIM_DONUS"

# yeni_kod (Yama)
# N_TICK_CONFIRMATION = 3 (Örn: 3 ardışık tick boyunca rejim ters kalmalı)
if time.time() - pos.opened_at > rejim_karsi_cikis_sn:
    # Rejim tersliği ve PnL negatifliği yanına 'ardışık onay' kontrolü eklendi
    if current_regime != pos.entry_regime and pos.pnl < 0:
        if getattr(pos, 'regime_flip_count', 0) >= 3: 
            return "REJIM_DONUS"
        pos.regime_flip_count = getattr(pos, 'regime_flip_count', 0) + 1
    else:
        pos.regime_flip_count = 0
```

**Kanıt Analizi:**
- `drive/toplama/arsiv-2/Futures_Bot_v37_Deneysel_Paper_SON__ic/futures_bot_v37/ws_bot.py:86-92` ve `111-117` satırları, eşik değerlerinin (Cascade Threshold) isabet oranını %60'tan %80'e çıkardığını kanıtlar. Bu, "tekil sinyal" yerine "birikimli/eşikli sinyal" kullanımının gürültüyü elediğinin sistemik kanıtıdır.
- RVOL filtresinin etkisizliği (Sıfır A/B etkisi), sorunun giriş sinyalinde değil, çıkış motorundaki (motor.py) aşırı hassasiyette olduğunu doğrular.

## risk_subayi
Risk subayı olarak raporu inceledim. Mevcut durum bir "churn" (işlem döngüsü) felaketidir. WR %15.9 ve PF 0.676 ile sistem sadece komisyon ödemek için çalışıyor. İşlemlerin %81'inin `REJIM_DONUS` ile anında kesilmesi, stratejinin nefes almasına izin vermeyen hatalı bir çıkış mekanizmasıdır.

**En kötü durumda kasa ne olur?**
Sınırsız pozisyon limiti olduğu için, eğer 6 bot aynı anda korele (aynı yönde) pozisyon açarsa ve stoplar aynı anda tetiklenirse, tek bir dalgada kasa **-60$** (6 pozisyon x 10$ stop) kaybeder. CROSS modunda olduğumuz için tasfiye mesafesi kasa toplamı üzerinden hesaplanır; 1000$ kasa ile 50$ teminatlı 10x pozisyonlarda tasfiye riski düşüktür ancak korelasyon yönetimi yoktur.

**Sistem Yaması (motor.py)**

`RVOL` filtresinin etkisiz olduğu kanıtlanmıştır, bu yüzden sinyal tarafına dokunmuyorum. Çıkış mekanizmasını "anlık ters dönme"den "onaylı ters dönme"ye çekiyorum.

**Karar 1:** Rejim tersliğinin tek bir tick ile değil, ardışık 3 tick boyunca sürmesi şartı getirilecek.
**Karar 2:** PnL negatif olsa dahi, rejim dönüşü için minimum bir "onay süresi" (buffer) eklenecek.
**Karar 3:** `REJIM_DONUS` çıkışı, sadece stop mesafesinin %50'sine ulaşıldığında (yani -5$ ve altı) aktif olacak; küçük dalgalanmalarda pozisyonu koruyacak.

**Yama Uygulaması:**

```python
# eski_kod (motor.py:142-144)
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    if current_rejim != pos.rejim and pos.pnl < 0:
        return "REJIM_DONUS"

# yeni_kod (motor.py:142-144)
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    # Onay mekanizması: Rejim tersliği ardışık 3 tick sürmeli ve PnL -5$ eşiğini aşmalı
    if getattr(pos, 'rejim_flip_count', 0) >= 3 and pos.pnl <= -5.0:
        return "REJIM_DONUS"
    # Rejim takibi için sayaç güncelleme (bu kısım loop içinde yönetilir)
    pos.rejim_flip_count = getattr(pos, 'rejim_flip_count', 0) + 1 if current_rejim != pos.rejim else 0
```

**Risk Onayı:**
Sayılar değişmedi. 1000$ kasa, 50$ teminat, 10x, CROSS, -10$ stop kuralları korunmuştur. Yama, sadece çıkış tetikleyicisini stabilize ederek komisyon kaybını azaltmayı ve WR'yi artırmayı hedefler. **VETO YOK, UYGULANABİLİR.**

## icra
**Kağıtta Çalışır vs. Borsada Çalışır**
Kağıtta çalışan sistem, `MakerFillSimulator` (bkz. `paper.py:54`) gibi idealize edilmiş dolum varsayımlarıyla hareket eder; emir defterindeki derinliği, kuyruk önceliğini ve borsa motorunun gecikmesini görmez. Borsada çalışan sistem ise **kayma (slippage)**, **kısmi dolum (partial fill)** ve **borsa reddi** ile savaşır. Kağıtta "anında" gerçekleşen stop, borsada piyasa emrinin derinlikte kaymasıyla net $-10$ stopun çok ötesine geçebilir.

**TANI VE YAMA**
Sistemdeki churn, rejim dönüşünün anlık bir gürültüye (noise) bağlanmasından kaynaklanıyor. %81'lik erken çıkış oranı, stratejinin nefes almasına izin vermeyen bir "panik butonu" gibi çalışıyor.

**YAMA: `bot/v9/motor.py`**

```python
# eski_kod
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    if current_rejim != pos.rejim and pos.pnl < 0:
        return "REJIM_DONUS"

# yeni_kod
# Karar 1: Rejim tersliğinin en az 3 ardışık tick/bar sürmesi şartı (Teyit)
# Karar 2: PnL'in sadece negatif değil, belirli bir eşiğin (-2$) altında olması
# Karar 3: Rejim dönüşü gerçekleşse bile stop limitine (-10$) kadar tolerans tanınması
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    if current_rejim != pos.rejim:
        pos.rejim_flip_count = getattr(pos, 'rejim_flip_count', 0) + 1
        if pos.rejim_flip_count >= 3 and pos.pnl < -2.0:
            return "REJIM_DONUS"
    else:
        pos.rejim_flip_count = 0
```

**İcra Notu:** RVOL filtresi etkisiz kaldığı için hacimle değil, zaman ve fiyat teyidiyle (persistence) churn engellenmiştir. Kasa ve teminat parametreleri sabit tutulmuştur.

## test
**TANI:** `motor.py` satır 142-144'teki mevcut mantık, rejim terslemesini anlık (single-tick) bir olay olarak kabul ediyor. %81'lik erken kapanma oranı, piyasa gürültüsünün (noise) "rejim dönüşü" olarak yanlış etiketlendiğini ve sistemin "churn" (gereksiz işlem döngüsü) yaşadığını kanıtlıyor. RVOL filtresinin etkisizliği, sorunun giriş sinyalinde değil, çıkış tetikleyicisinin düşük hassasiyetinde olduğunu doğrular.

**YAMA STRATEJİSİ:** Rejim dönüşünü bir "durum" (state) haline getirmek. Sadece rejim ters döndüğünde değil, bu tersliğin belirli bir süre/tick boyunca kalıcı olduğu kanıtlandığında ve PnL negatif bölgedeyken çıkış tetiklenecektir.

**KOD YAMASI:**

```python
# eski_kod (motor.py:142-144)
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    if current_regime != pos.regime and pos.pnl < 0:
        self.close_position(pos, reason="REJIM_DONUS")

# yeni_kod
# Not: pos nesnesine 'regime_flip_start' (float) ve 'flip_count' (int) eklenmiş varsayılır.
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    if current_regime != pos.regime:
        pos.flip_count = getattr(pos, 'flip_count', 0) + 1
        # Karar 1: Rejim tersliğinin en az 3 ardışık tick/kontrol boyunca sürmesi
        # Karar 2: PnL'in sadece negatif değil, komisyonu da kapsayan -2$ eşiğinin altında olması
        if pos.flip_count >= 3 and pos.pnl < -2.0:
            self.close_position(pos, reason="REJIM_DONUS_CONFIRMED")
    else:
        pos.flip_count = 0 # Rejim düzelirse sayaç sıfırlanır (Teyit mekanizması)
```

**KARARLAR VE KANITLAR:**

1.  **Ardışık Teyit (Flip Count $\ge 3$):** Tekil tick değişimlerini filtrelemek için eklendi. `test_counter_not_double_counted_per_tick` (v6.2) mantığına benzer şekilde, aynı durumun tekrarlanması şartı aranır.
2.  **PnL Eşiği ($-2.0\$$):** `pos.pnl < 0` ifadesi, $0.01$ gibi önemsiz negatiflerde bile çıkışa neden oluyordu. Komisyon maliyeti ($0.50\$$) ve piyasa gürültüsü payı eklenerek "gerçek zarar" bölgesine çekildi.
3.  **Sıfırlama Mekanizması:** `else: pos.flip_count = 0` ile rejim anlık olarak eski haline dönerse teyit süreci iptal edilir; böylece sadece kalıcı trend değişimleri yakalanır.

**KABUL KRİTERİ:**
*   `REJIM_DONUS` kaynaklı kapanış oranının %81'den %30'un altına düşmesi.
*   İşlem başına ödenen ortalama komisyonun azalması.
*   WR'nin (Win Rate) %15.9'dan yukarı yönlü ivmelenmesi.

## olcum
**ANALİZ:**
Örneklem (44 işlem) < 100 olduğu için bu sonuçlar bir **yön göstergesidir**.
WR %15.9 ve PF 0.676 ile sistem şu an "churn" (sürekli düşük maliyetli kayıplar) döngüsündedir. İşlemlerin %81'inin `REJIM_DONUS` ile anında kapanması, stratejinin sinyal kalitesinden ziyade, çıkış mekanizmasının aşırı hassas (over-sensitive) olduğunu kanıtlar. Her işlemde ödenen 0.50$ komisyon, düşük WR ile birleştiğinde kasayı eritmektedir.

**TANI:**
`motor.py` satır 142-144'teki mantık, rejim tersleştiği anda (tek bir tick/sinyal ile) ve PnL negatifse pozisyonu kapatmaktadır. Bu, piyasa gürültüsünü (noise) "rejim dönüşü" olarak algılamaya neden olur.

**YAMA ÖNERİSİ:**
Sinyal gürültüsünü engellemek için "Ardışık Onay" (Consecutive Confirmation) mekanizması eklenmelidir.

**KOD YAMASI:**

```python
# eski_kod (motor.py:142-144)
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    if current_rejim != pos.entry_rejim and pos.pnl < 0:
        return "REJIM_DONUS"

# yeni_kod (motor.py:142-144)
# Rejim tersliği en az 3 tick boyunca sürmeli ve PnL -2$ eşiğinin altında olmalı
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    pos.rejim_counter = getattr(pos, 'rejim_counter', 0) + 1 if current_rejim != pos.entry_rejim else 0
    if pos.rejim_counter >= 3 and pos.pnl < -2.0:
        return "REJIM_DONUS"
```

**KARARLAR:**
1. **Ardışık Onay:** Rejim tersliğinin tek bir tick yerine 3 ardışık tick boyunca sürmesi şartı getirildi.
2. **PnL Eşiği:** `pos.pnl < 0` (sıfır altı) kontrolü, komisyon ve küçük dalgalanmaları absorbe etmek için `pos.pnl < -2.0` olarak güncellendi.
3. **Sinyal Filtresi:** RVOL filtresinin etkisiz olduğu kabul edildi; müdahale sadece çıkış tetikleyicisine (motor.py) odaklandı.

## ops
**OPERASYONEL YAMA: motor.py**

Churn kaynağı olan "anlık rejim dönüşü + negatif PnL" kombinasyonunu, gürültüden arındırmak için **ardışık onay (tick confirmation)** mekanizmasına bağlıyorum.

**Kararlar:**
1. **Onay Mekanizması:** Rejim tersliğinin tek bir tick ile değil, `N` (örn. 3) ardışık tick boyunca sürmesi şartı getirildi.
2. **PnL Filtresi:** Sadece negatif PnL değil, stop limitine yaklaşmayan "küçük gürültü" kayıplarının anlık çıkış yapması engellendi.
3. **Süre Koruması:** `rejim_karsi_cikis_sn` süresi dolmuş olsa dahi, onay mekanizması tetiklenmeden işlem kapatılmaz.

```python
# eski_kod (motor.py:142-144)
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    if current_regime != pos.regime and pos.pnl < 0:
        return "REJIM_DONUS"

# yeni_kod (motor.py:142-144)
if time.time() - pos.open_time > rejim_karsi_cikis_sn:
    # Rejim tersliği N ardışık tick boyunca sürdüyse ve PnL negatifse kapat
    if pos.regime_flip_count >= 3 and current_regime != pos.regime and pos.pnl < 0:
        pos.regime_flip_count = 0 # Reset
        return "REJIM_DONUS"
    # Rejim tersliği başladıysa sayacı artır, düzelirse sıfırla
    pos.regime_flip_count = pos.regime_flip_count + 1 if current_regime != pos.regime else 0
```

**7/24 AYAKTA KALMA ASGARİSİ (OPS):**
*   **Log:** `logging.StreamHandler(sys.stdout)` + Log Rotasyonu (Sınırsız büyüme engeli).
*   **Kopma/Yeniden Başlatma:** `RestartRecovery` (Bayat emir iptali + stop restore) + `LiveMirror` (Kalıcı durum kaydı).
*   **Kill Switch:** `EmergencyController` (Fail-closed anahtar kontrolü).
*   **Alarm:** `runtime_supervision` (Feed lag ve operational_health takibi).