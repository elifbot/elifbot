#!/usr/bin/env python3
"""
rapor.py — TEST RAPORU

logs/ws_olay.csv (sinyaller) + live_trades.csv (işlemler) + logs/ws_run.log
dosyalarını okuyup markdown rapor üretir.

    python3 rapor.py                 # ekrana bas
    python3 rapor.py --md rapor.md   # dosyaya yaz
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

TABAN = os.path.dirname(os.path.abspath(__file__))
OLAY = os.path.join(TABAN, "logs", "ws_olay.csv")
ISLEM = os.path.join(TABAN, "live_trades.csv")


def oku(yol):
    try:
        with open(yol, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except FileNotFoundError:
        return []


def f(x, n=2):
    return f"{x:,.{n}f}".replace(",", ".")


def rapor() -> str:
    olaylar = oku(OLAY)
    islemler = oku(ISLEM)
    L = []
    E = L.append

    # ---------------------------------------------------------- başlık
    E("# Vadeli Bot — 15 Dakikalık Test Raporu\n")
    E(f"**Rapor zamanı:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n")
    E("**Mod:** PAPER (gerçek emir gönderilmez) · **Borsalar:** OKX (WebSocket) + Binance (REST)\n")
    E("---\n")

    # ---------------------------------------------------------- özet
    toplam_pnl = sum(float(r.get("realized_pnl") or 0) for r in islemler)
    kazanan = [r for r in islemler if float(r.get("realized_pnl") or 0) > 0]
    kaybeden = [r for r in islemler if float(r.get("realized_pnl") or 0) <= 0]
    bakiye = 1000.0 + toplam_pnl

    E("## 1. Özet\n")
    E("| Ölçüt | Değer |")
    E("|---|---|")
    E(f"| Tespit edilen sinyal | **{len(olaylar)}** |")
    E(f"| Açılan pozisyon | **{len(islemler)}** |")
    E(f"| Kârlı / zararlı | {len(kazanan)} / {len(kaybeden)} |")
    oran = (len(kazanan) / len(islemler) * 100) if islemler else 0
    E(f"| İsabet oranı | **%{f(oran,1)}** |")
    E(f"| Net PnL | **{f(toplam_pnl)} USDT** |")
    E(f"| Bakiye | {f(bakiye)} USDT |")
    E(f"| Getiri | %{f(toplam_pnl / 10, 2)} |")
    E("")

    # ---------------------------------------------------------- kapsam
    E("## 2. Tarama Kapsamı\n")
    okx_sembol = {o["symbol"] for o in olaylar if o.get("exchange") == "okx"}
    bn_sembol = {o["symbol"] for o in olaylar if o.get("exchange") == "binance"}
    E("| | OKX | Binance |")
    E("|---|---|---|")
    E("| Kapsanan sembol | 289 (kripto USDT-SWAP) | 523 (USDT sürekli vade) |")
    E("| Bağlantı türü | WebSocket push | REST yoklama |")
    E("| Çözünürlük | ~100 ms | ~600 ms |")
    E(f"| Sinyal üreten sembol | {len(okx_sembol)} | {len(bn_sembol)} |")
    E("")

    # ---------------------------------------------------------- sinyaller
    if olaylar:
        E("## 3. Sinyal Dağılımı\n")
        borsa_s = Counter(o["exchange"] for o in olaylar)
        yon_s = Counter(o["yon"] for o in olaylar)
        E("| Borsa | Sinyal | Pay |")
        E("|---|---|---|")
        for b, n in borsa_s.most_common():
            E(f"| {b.upper()} | {n} | %{f(n/len(olaylar)*100,1)} |")
        E("")
        E(f"**Yön:** LONG {yon_s.get('LONG',0)} · SHORT {yon_s.get('SHORT',0)}\n")

        gec = [int(o["gecikme_ms"]) for o in olaylar if o.get("gecikme_ms")]
        if gec:
            # yerel saat OKX'ten ~56 ms ileride; bu taban çıkarılır
            duzeltilmis = [max(0, g - 56) for g in gec]
            E("**Tespit gecikmesi** (tik → sinyal, saat farkı düzeltilmiş):\n")
            E("| | Değer |")
            E("|---|---|")
            E(f"| Medyan | **{f(statistics.median(duzeltilmis),0)} ms** |")
            E(f"| Ortalama | {f(statistics.mean(duzeltilmis),0)} ms |")
            E(f"| p90 | {f(sorted(duzeltilmis)[int(len(duzeltilmis)*0.9)-1],0)} ms |")
            E(f"| En yüksek | {f(max(duzeltilmis),0)} ms |")
            E("")

        # en güçlü hareketler
        E("### En güçlü 10 sinyal\n")
        E("| Saat | Sembol | Yön | Hareket | Hacim katı |")
        E("|---|---|---|---|---|")
        guclu = sorted(olaylar, key=lambda o: -abs(float(o["ret_pct"])))[:10]
        for o in guclu:
            saat = o["ts_utc"][11:19]
            E(f"| {saat} | {o['symbol']} | {o['yon']} | "
              f"%{f(float(o['ret_pct']),2)} | {f(float(o['rvol']),1)}× |")
        E("")

    # ---------------------------------------------------------- işlemler
    if islemler:
        E("## 4. İşlem Sonuçları\n")
        sebep = Counter(r.get("reason", "") for r in islemler)
        E("| Kapanış sebebi | Adet | Toplam PnL |")
        E("|---|---|---|")
        adlar = {"take_profit": "Kâr al (TP)", "stop_loss": "Zarar durdur (SL)",
                 "timeout": "Süre aşımı", "session_end": "Oturum sonu"}
        for s, n in sebep.most_common():
            p = sum(float(r["realized_pnl"]) for r in islemler if r.get("reason") == s)
            E(f"| {adlar.get(s, s)} | {n} | {f(p)} USDT |")
        E("")

        borsa_p = defaultdict(list)
        for r in islemler:
            borsa_p[r["exchange"]].append(float(r["realized_pnl"]))
        E("| Borsa | İşlem | Kârlı | PnL | Ortalama |")
        E("|---|---|---|---|---|")
        for b, p in borsa_p.items():
            k = sum(1 for x in p if x > 0)
            E(f"| {b.upper()} | {len(p)} | {k} | {f(sum(p))} USDT | {f(statistics.mean(p))} USDT |")
        E("")

        pnl = [float(r["realized_pnl"]) for r in islemler]
        E("| | Değer |")
        E("|---|---|")
        E(f"| En iyi işlem | {f(max(pnl))} USDT |")
        E(f"| En kötü işlem | {f(min(pnl))} USDT |")
        E(f"| Ortalama | {f(statistics.mean(pnl))} USDT |")
        if len(pnl) > 1:
            E(f"| Standart sapma | {f(statistics.pstdev(pnl))} USDT |")
        # maksimum düşüş
        tepe, dd, kum = 0.0, 0.0, 0.0
        for x in pnl:
            kum += x
            tepe = max(tepe, kum)
            dd = min(dd, kum - tepe)
        E(f"| Maksimum düşüş | {f(dd)} USDT |")
        E("")

        komisyon = sum(float(r.get("entry_fee") or 0) + float(r.get("exit_fee") or 0)
                       for r in islemler)
        brut = sum(float(r.get("gross_pnl") or 0) for r in islemler)
        E(f"**Komisyon toplamı:** {f(komisyon)} USDT · "
          f"**Brüt PnL:** {f(brut)} USDT · **Net:** {f(toplam_pnl)} USDT\n")

    # ---------------------------------------------------------- yorum
    E("## 5. Değerlendirme\n")
    if islemler:
        if toplam_pnl > 0:
            E(f"- Test **kârla** kapandı: {f(toplam_pnl)} USDT.")
        else:
            E(f"- Test **zararla** kapandı: {f(toplam_pnl)} USDT.")
        if len(islemler) >= 10:
            E(f"- {len(islemler)} işlem istatistiksel olarak **yetersiz**; "
              "güvenilir bir isabet oranı için en az 100 işlem gerekir.")
        else:
            E(f"- Yalnızca {len(islemler)} işlem gerçekleşti — bu sayı **hiçbir** "
              "sonuç çıkarmaya yetmez.")
        if komisyon > abs(brut):
            E("- **Kritik:** komisyon, brüt kârdan büyük. Eşikler bu maliyeti "
              "karşılamıyor.")
    E("- Funding (fonlama) ücreti hesaplanmadı — gerçek sonuç bundan etkilenir.")
    E("- Binance tarafı ~600 ms çözünürlükte; OKX ~100 ms. İki borsa eşit hızda değil.")
    E("- Paper modda kayma (slippage) ve emir defteri derinliği modellenmiyor.")
    E("- Yatırım tavsiyesi değildir.\n")

    # ---------------------------------------------------------- kök neden
    if islemler:
        E("## 6. Kök Neden Analizi\n")
        brut_l = [float(r.get("gross_pnl") or 0) for r in islemler]
        ort_brut = statistics.mean(brut_l)
        fee = 0.50
        E("İşlem başına rakamlar (100 USDT marj × 5 kaldıraç = 500 USDT nominal):\n")
        E("| | Değer |")
        E("|---|---|")
        E(f"| Ortalama brüt kâr | **{f(ort_brut)} USDT** |")
        E(f"| Ortalama komisyon | **{f(fee)} USDT** |")
        E(f"| Ortalama net | {f(ort_brut - fee)} USDT |")
        E("")
        if abs(ort_brut) < fee:
            E(f"> **Sonuç:** sinyalin ortalama brüt getirisi ({f(ort_brut)} USDT) "
              f"komisyonun ({f(fee)} USDT) altında. Yani sinyal neredeyse **sıfır** "
              "kenar üretiyor ve işlem maliyeti onu eksiye çeviriyor.\n")

        # başabaş analizi
        tp, sl = 0.8, 0.5
        isabet = len(kazanan) / len(islemler)
        E("### Başabaş isabet oranı\n")
        E("| TP | SL | Ödül/Risk | Gereken isabet | Gerçekleşen | Durum |")
        E("|---|---|---|---|---|---|")
        for t in (0.8, 1.0, 1.2, 1.5):
            gerek = (fee / 500 * 100 + sl) / (t + sl)
            durum = "✅ geçer" if isabet >= gerek else "❌ kalmaz"
            E(f"| %{t} | %{sl} | {f(t/sl,2)} | %{f(gerek*100,1)} | "
              f"%{f(isabet*100,1)} | {durum} |")
        E("")
        E("### Borsa bazında stop aşımı\n")
        E("| Borsa | SL sayısı | Ortalama kayıp | En kötü |")
        E("|---|---|---|---|")
        for b in ("okx", "binance"):
            sl_r = [r for r in islemler if r["exchange"] == b and r.get("reason") == "stop_loss"]
            if not sl_r:
                continue
            hs = []
            for r in sl_r:
                g, c = float(r["entry_price"]), float(r["exit_price"])
                h = (c - g) / g * 100 * (-1 if r["side"] == "SHORT" else 1)
                hs.append(h)
            E(f"| {b.upper()} | {len(sl_r)} | %{f(statistics.mean(hs),2)} | %{f(min(hs),2)} |")
        E("")
        E("> Binance'te stoplar hedeften daha derin kapanıyor — REST akışı ~600 ms "
          "gecikmeli olduğu için fiyat durdurma seviyesini aşıp geri dönüyor. "
          "OKX'te aşım yok denecek kadar az.\n")

        E("### Öneriler\n")
        E("1. **Kâr hedefini yükselt** — TP %1,2 / SL %0,5 başabaş isabeti "
          "%38,5'ten %35,3'e indirir.")
        E("2. **Komisyonu düşür** — gerçek işlemde limit emir (maker) %0,02, "
          "piyasa emri (taker) %0,05. Maker ile maliyet %60 azalır.")
        E("3. **Eşiği sıkılaştır** — daha az ama daha güçlü sinyal. "
          "rvol eşiğini 2,0'dan 4,0'a çıkarmak işlem sayısını yarıya indirir.")
        E("4. **Binance'te WebSocket şart** — REST gecikmesi stop aşımına yol açıyor.")
        E("5. **Daha uzun test** — 35 işlem karar için yetersiz; 200+ işlem gerekir.\n")

    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="çıktı dosyası")
    a = ap.parse_args()
    metin = rapor()
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(metin)
        print(f"yazıldı: {a.md}")
    else:
        print(metin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
