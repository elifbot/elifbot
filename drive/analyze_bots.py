#!/usr/bin/env python3
"""
16 BOTU ANALIZ ET - Nemotron 3 Ultra
Tam bot kodunu okur, analiz eder, SUPER BOT uretir.

Kullanim:
  python analyze_bots.py
"""

from openai import OpenAI

NVIDIA_API_KEY= "***REDACTED***"
nvidia = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=NVIDIA_API_KEY)

# Tam birlesik bot kodunu oku
with open("BOTLAR_BIRLESIK.py", "r") as f:
    bot_code = f.read()

PROMPT = f"""Asagida 16 trading botunun TAM sinyal, config ve engine kodlari var.

GOREV:
1. Her botu tek tek analiz et - sinyal mantigi, config degerleri, risk yonetimi, emir tipi
2. Hatalari bul - sinyal uretemeyenler, kar alamayanlar, stop sorunlari, maker dolmama, chase
3. En iyi ozellikleri sec
4. SUPER BOT kodunu yaz

BILINEN SORUNLAR:
- Maker emirler dolmuyor (V23 KGEN PENDING)
- Market emirler pump tepesinden giriyor (V28 chase)
- TP_R 2.2 cok yuksek, 118 pozisyonda 0 target
- Trailing stop pasif
- Bazi botlar sinyal uretemiyor (V23, V28_SINGLE, ZERO)
- Stop mantigi ATR bazli ama mesafe yanlis

SUPER BOT OZELLIKLERI:
- 5 grup ensemble: trend, momentum, breakout, volume_flow, fade
- Fade tersine cevirme: pump sonrasi SHORT, dump sonrasi LONG
- Pump-tepe filtresi: RSI > 70 ise LONG engelle
- Market emir (maker degil)
- TP_R 1.0 (yakin hedef)
- Trailing stop: kar %2'de aktiflesir
- Break-even: kar %1.5'te stop'u girise cek
- ATR bazli stop (2.2x ATR), min %1.2, max %4.5
- OKX + Binance Futures, ccxt, paper mod
- Tek dosya, calisir kod, Python 3.10+

BOT KODLARI:
{bot_code}

Once her bot icin kisa analiz yaz (2-3 cumle), sonra SUPER BOT kodunu ver."""

print("16 bot analiz ediliyor (Nemotron 3 Ultra 550B)...\n")
print(f"Bot kodu: {len(bot_code)} karakter, {len(bot_code.splitlines())} satir\n")

resp = nvidia.chat.completions.create(
    model="nvidia/nemotron-3-ultra-550b-a55b",
    messages=[{"role": "user", "content": PROMPT}],
    max_tokens=32000,
    timeout=900
)

result = resp.choices[0].message.content
print(result)

with open("ANALIZ_VE_SUPER_BOT.py", "w") as f:
    f.write(result)
print("\n\nANALIZ_VE_SUPER_BOT.py dosyasina kaydedildi!")
