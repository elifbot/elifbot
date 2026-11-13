"""OTO TRADER — zekâların otomatik işlem döngüsü.

Akış (her tur):
  1) GÜNLÜK ZARAR KAPISI  → limit aşıldıysa trading pasife çekilir
  2) TÜM FUTURES EVRENİ   → işlem yapılan borsanın tüm USDT perpetual'ları
                            hacim sırasına göre taranır
  3) TEKNİK ÖN ELEME      → signal_engine skoru |skor|≥20 olanlar; en güçlü
                            OTO_MAX_ADAY adet aday seçilir
  4) AI KONSENSÜSÜ        → bot kadrosu canlı veriyle oy verir, birbirini
                            kontrol eder; bölünürse Hakem devreye girer
  5) RİSK KAPISI          → maks pozisyon, soğuma, güven eşiği, oydaşlık
  6) POZİSYON AÇ          → kağıt / testnet / gerçek emir + SL/TP kaydı
  7) YÖNETİM DÖNGÜSÜ      → 45 sn'de bir fiyat izlenir; SL / TP / süre dolunca
                            POZİSYON KAPANIR, PnL kaydı + masaüstü bildirimi

Her adım trade_log'a ve Bot Odası'na canlı düşer.
"""
import asyncio
from datetime import datetime, timezone

import bildirim
import config
import konsensus
import database as db
import exchange_trader as xt
import market_data as md
import signal_engine as se

_SEMA = asyncio.Semaphore(6)  # eşzamanlı teknik tarama sınırı


def _bugun() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class OtoTrader:
    def __init__(self):
        self.calisiyor = False
        self.pasif_neden = ""
        self.kill_aktif = False
        self.broker = None
        self._tarama_task = None
        self._yonet_task = None
        self._tarama_kilit = asyncio.Lock()
        self.son_tur = None      # son turun özeti (panel için)
        self.gun_baslangic = None

    # ------------------------------------------------------------ durum
    def durum(self) -> dict:
        return {
            "calisiyor": self.calisiyor,
            "pasif_neden": self.pasif_neden,
            "kill_aktif": self.kill_aktif,
            "borsa": self.broker.ad if self.broker else None,
            "mod": config.TRADE_MODE,
            "son_tur": self.son_tur,
        }

    # ------------------------------------------------------------ başlat/durdur
    async def baslat(self) -> str:
        if self.calisiyor:
            return "Oto trader zaten çalışıyor"
        self.broker = xt.borsa_olustur()  # anahtar eksikse EmirHatasi fırlatır
        self.kill_aktif = False
        self.pasif_neden = ""
        self.calisiyor = True
        bakiye = await self.broker.bakiye()
        self.gun_baslangic = bakiye
        db.ayar_koy(f"gun_baslangic_{_bugun()}", str(bakiye))
        self._tarama_task = asyncio.create_task(self._tarama_dongusu())
        self._yonet_task = asyncio.create_task(self._yonet_dongusu())
        mesaj = (f"▶️ OTO İŞLEM başladı: {self.broker.ad} • mod "
                 f"{config.TRADE_MODE.upper()} • bakiye {bakiye:,.2f} USDT • "
                 f"risk: %{config.RISK_POS_PCT}/pozisyon, maks "
                 f"{config.RISK_MAX_POSITIONS} pozisyon, "
                 f"{config.RISK_MAX_LEVERAGE}x tavan, günlük zarar limiti "
                 f"%{config.RISK_DAILY_LOSS_PCT}")
        db.tlog(mesaj, "ALARM")
        db.oda_ekle("⚙️ Sistem", mesaj, tur="sistem", emoji="⚙️")
        return mesaj

    async def durdur(self, pozisyonlari_kapat: bool = False) -> str:
        self.calisiyor = False
        mesaj = "⏸ Oto trader durduruldu"
        if pozisyonlari_kapat and self.broker:
            await self.tumunu_kapat("Durdurma (pozisyonlar kapatıldı)")
        else:
            db.oda_ekle("⚙️ Sistem",
                        "⏸ Oto trader durduruldu. Açık pozisyonlar (varsa) "
                        "izlenmeye devam etmez — manuel yönet.",
                        tur="sistem", emoji="⚙️")
        db.tlog(mesaj)
        return mesaj

    async def kill_switch(self) -> str:
        self.kill_aktif = True
        self.calisiyor = False
        if self.broker:
            await self.tumunu_kapat("🚨 KILL SWITCH")
        db.tlog("🚨 KILL SWITCH — tüm pozisyonlar kapatıldı, trader durdu",
                "ALARM")
        db.oda_ekle("⚙️ Sistem",
                    "🚨 KILL SWITCH! Tüm pozisyonlar kapatıldı ve oto işlem "
                    "durdu. Tekrar başlatmak için Başlat'a bas.",
                    tur="sistem", emoji="⚙️")
        bildirim.gonder("🚨 KILL SWITCH", "Tüm pozisyonlar kapatıldı, trader durdu")
        return "Kill switch: pozisyonlar kapatıldı, trader durduruldu"

    async def pasif_sifirla(self) -> str:
        self.pasif_neden = ""
        db.tlog("Günlük zarar limiti sıfırlama: kullanıcı trading'e izin verdi")
        return "Pasif durum sıfırlandı — trading devam edebilir"

    # ------------------------------------------------------------ ana döngüler
    async def _tarama_dongusu(self):
        await asyncio.sleep(3)  # panelin açılması için nefes payı
        while self.calisiyor:
            try:
                await self.tarama_turu()
            except Exception as e:
                db.tlog(f"Tarama turu hatası: {type(e).__name__}: {e}", "HATA")
            adim = max(5, config.SCAN_INTERVAL_MIN) * 60
            for _ in range(adim):
                if not self.calisiyor:
                    return
                await asyncio.sleep(1)

    async def _yonet_dongusu(self):
        while self.calisiyor:
            try:
                await self.pozisyonlari_yonet()
            except Exception as e:
                db.tlog(f"Pozisyon yönetim hatası: {type(e).__name__}: {e}",
                        "HATA")
            for _ in range(45):
                if not self.calisiyor:
                    return
                await asyncio.sleep(1)

    # ------------------------------------------------------------ tarama turu
    async def tarama_turu(self) -> dict:
        """Bir tam tarama turu. Dönen: tur özeti (panelde gösterilir)."""
        if self._tarama_kilit.locked():
            return {"atlandi": "önceki tur sürüyor"}
        async with self._tarama_kilit:
            if not self.broker:
                self.broker = xt.borsa_olustur()
            bakiye = await self.broker.bakiye()

            # 0) günlük zarar kapısı
            gp = db.gun_pnl()
            temel = self.gun_baslangic or bakiye or 0
            zarar_pct = (gp["pnl"] / temel * 100) if temel else 0
            if zarar_pct <= -abs(config.RISK_DAILY_LOSS_PCT):
                self.pasif_neden = (
                    f"Günlük zarar limiti aşıldı (%{zarar_pct:.1f} — "
                    f"{gp['pnl']:+.2f} USDT). Devam için 'Pasifi Sıfırla'.")
                db.tlog("⛔ " + self.pasif_neden, "ALARM")
                self.son_tur = {"zaman": datetime.now(timezone.utc)
                                .isoformat(timespec="seconds"),
                                "sonuc": self.pasif_neden}
                return self.son_tur
            if self.pasif_neden:
                self.son_tur = {"zaman": datetime.now(timezone.utc)
                                .isoformat(timespec="seconds"),
                                "sonuc": f"pasif: {self.pasif_neden}"}
                return self.son_tur

            # 1) evren: tüm futures
            borsa_ad = getattr(self.broker, "mod", "bybit")
            evren = await md.tum_perpler(borsa_ad, config.SCAN_MAX_SYMBOLS,
                                         config.MIN_VOLUME_USDT)
            semboller = [e["sembol"] for e in evren]
            db.tlog(f"🔎 Tur başladı: {len(semboller)} sembol taranacak "
                    f"(bakiye {bakiye:,.2f} USDT)")
            if not semboller:
                self.son_tur = {"zaman": datetime.now(timezone.utc)
                                .isoformat(timespec="seconds"),
                                "sonuc": "evren alınamadı — veri kaynağı erişilemiyor"}
                return self.son_tur

            # 2) teknik ön eleme
            adaylar = await self._teknik_on_eleme(semboller)
            ozet = {"zaman": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds"),
                    "evren": len(semboller), "aday": len(adaylar),
                    "acilan": [], "sonuc": ""}
            if not adaylar:
                ozet["sonuc"] = "teknik eşik altı — aday yok"
                db.tlog("• Aday yok: hiçbir sembol |skor|≥20 vermedi")
                self.son_tur = ozet
                return ozet
            db.tlog("• Adaylar: " + ", ".join(
                f"{a['sembol']} {a['skor']:+d}" for a in adaylar))

            # 3+4+5) AI konsensusu + risk kapısı + giriş
            for aday in adaylar[:max(1, config.OTO_MAX_ADAY)]:
                if not self.calisiyor:
                    break
                sembol = aday["sembol"]
                if db.pos_bul(sembol):
                    db.tlog(f"• {sembol}: zaten açık pozisyon var, atlandı")
                    continue
                if db.son_kapanis_sogumasi(sembol, config.POS_COOLDOWN_H):
                    db.tlog(f"• {sembol}: soğuma ({config.POS_COOLDOWN_H}h), atlandı")
                    continue
                if len(db.acik_pozisyonlar()) >= config.RISK_MAX_POSITIONS:
                    db.tlog(f"⛔ Maks pozisyon ({config.RISK_MAX_POSITIONS}) "
                            f"dolu — yeni giriş yok")
                    break
                try:
                    sonuc = await konsensus.analiz_et(sembol)
                except Exception as e:
                    db.tlog(f"⚠️ {sembol}: AI konsensus hatası: {str(e)[:150]}",
                            "HATA")
                    continue
                # kayıt + oda
                alarm = 1 if (sonuc["final_yon"] in ("LONG", "SHORT")
                              and sonuc["final_guven"] >= config.RISK_MIN_GUVEN
                              and sonuc["oydaslik"] >= 50) else 0
                db.save_analysis(sembol, sonuc["final_yon"],
                                 sonuc["final_guven"], sonuc["oydaslik"],
                                 sonuc["teknik"]["skor"],
                                 sonuc["teknik"]["fiyat"], sonuc["hukum"],
                                 konsensus.detay_paketi(sonuc), alarm)

                if (sonuc["final_yon"] in ("LONG", "SHORT")
                        and sonuc["final_guven"] >= config.RISK_MIN_GUVEN
                        and sonuc["oydaslik"] >= 50):
                    try:
                        await self._gire(sonuc, bakiye)
                        ozet["acilan"].append(sembol)
                    except xt.EmirHatasi as e:
                        db.tlog(f"⛔ {sembol}: {e}", "HATA")
                    except Exception as e:
                        db.tlog(f"❌ {sembol} giriş hatası: {str(e)[:200]}",
                                "HATA")
                else:
                    db.tlog(f"✋ {sembol}: AI kararı {sonuc['final_yon']} "
                            f"(güven %{sonuc['final_guven']}, oydaşlık "
                            f"%{sonuc['oydaslik']}) — eşik altı, işlem yok")

            ozet["sonuc"] = (f"{len(ozet['acilan'])} pozisyon açıldı"
                             if ozet["acilan"] else "işlem açılmadı")
            self.son_tur = ozet
            return ozet

    async def _teknik_on_eleme(self, semboller: list[str]) -> list[dict]:
        async def biri(s: str):
            async with _SEMA:
                try:
                    return await se.generate_signal(s)
                except Exception:
                    return None
        sonuclar = await asyncio.gather(*[biri(s) for s in semboller])
        rows = [r for r in sonuclar
                if r and r["taraf"] in ("LONG", "STRONG LONG",
                                        "SHORT", "STRONG SHORT")
                and abs(r["skor"]) >= 20]
        rows.sort(key=lambda r: abs(r["skor"]), reverse=True)
        return rows

    # ------------------------------------------------------------ giriş
    async def _gire(self, sonuc: dict, bakiye: float) -> None:
        sig = sonuc["teknik"]
        sembol = sig["sembol"]
        taraf = "LONG" if sonuc["final_yon"] == "LONG" else "SHORT"
        kaldirac = max(1, min(int(sig.get("kaldirac", 1)),
                              config.RISK_MAX_LEVERAGE))
        fiyat = float(sig["fiyat"])

        miktar, notional = xt.pozisyon_buyuklugu(bakiye, fiyat, kaldirac)
        try:
            await self.broker.kaldirac_ayarla(sembol, kaldirac)
        except Exception as e:
            db.tlog(f"⚠️ {sembol} kaldıraç ayarlanamadı (devam): {str(e)[:120]}")
        d = await self.broker.market_ac(sembol, taraf, miktar, kaldirac)
        giris = float(d["giris"])
        miktar = float(d["miktar"])

        atr = float(sig.get("atr") or giris * 0.01)
        sl = giris - 1.5 * atr if taraf == "LONG" else giris + 1.5 * atr
        tp = giris + 2.5 * atr if taraf == "LONG" else giris - 2.5 * atr
        db.pos_ac(sembol, taraf, miktar, giris, sl, tp, kaldirac,
                  config.TRADE_MODE, self.broker.ad,
                  f"{sonuc['hukum']} • güven %{sonuc['final_guven']}")

        mesaj = (f"🤖 POZİSYON AÇILDI [{config.TRADE_MODE.upper()}] "
                 f"{sembol} {taraf} {kaldirac}x\n"
                 f"• Miktar: {xt._fmt_qty(miktar)} (~{notional:,.0f} USDT)\n"
                 f"• Giriş: {giris:,.4g} | SL: {sl:,.4g} | TP: {tp:,.4g}\n"
                 f"• Konsensus: %{sonuc['final_guven']} güven, "
                 f"%{sonuc['oydaslik']:.0f} oydaşlık ({sonuc['hukum']})\n"
                 f"• Marjin: {notional / kaldirac:,.2f} USDT "
                 f"(bakiyenin %{config.RISK_POS_PCT})")
        db.tlog(mesaj.replace("\n", " | "), "ALARM")
        db.oda_ekle("⚙️ Sistem", mesaj, tur="sistem", emoji="⚙️")
        bildirim.gonder(f"🤖 {sembol} {taraf} {kaldirac}x AÇILDI",
                        f"{config.TRADE_MODE.upper()} • giriş {giris:,.4g} • "
                        f"SL {sl:,.4g} • TP {tp:,.4g} • güven %{sonuc['final_guven']}")

    # ------------------------------------------------------------ kapatma
    async def _kapat(self, p: dict, neden: str) -> None:
        sembol = p["sembol"]
        d = await self.broker.market_kapat(sembol, p["taraf"],
                                           float(p["miktar"]))
        cikis = float(d.get("cikis") or 0)
        yon = xt._yon_birimi(p["taraf"])
        pnl = (cikis - float(p["giris"])) * float(p["miktar"]) * yon
        marjin = float(p["miktar"]) * float(p["giris"]) / max(p["kaldirac"], 1)
        pnl_pct = (pnl / marjin * 100) if marjin else 0.0
        db.pos_kapat(p["id"], cikis, round(pnl, 6), round(pnl_pct, 2), neden)

        if config.TRADE_MODE == "kagit" and self.broker:
            # sanal bakiyeye PnL yansıt
            try:
                bakiye = await self.broker.bakiye()
                db.ayar_koy("paper_bakiye",
                            str(round(bakiye + pnl, 6)))
            except Exception:
                pass

        emoji = "💰" if pnl > 0 else "🔻"
        mesaj = (f"🔒 POZİSYON KAPANDI {sembol} {p['taraf']}\n"
                 f"• Neden: {neden}\n"
                 f"• Çıkış: {cikis:,.4g}\n"
                 f"• PnL: {pnl:+.2f} USDT ({pnl_pct:+.1f}%) {emoji}")
        db.tlog(mesaj.replace("\n", " | "), "ALARM")
        db.oda_ekle("⚙️ Sistem", mesaj, tur="sistem", emoji="⚙️")
        bildirim.gonder(f"🔒 {sembol} kapatıldı — {pnl:+.2f} USDT",
                        f"{neden} • çıkış {cikis:,.4g} • PnL %{pnl_pct:+.1f}")

    async def tumunu_kapat(self, neden: str) -> int:
        n = 0
        for p in db.acik_pozisyonlar():
            try:
                await self._kapat(p, neden)
                n += 1
            except Exception as e:
                db.tlog(f"Kapatma hatası {p['sembol']}: {str(e)[:150]}", "HATA")
        return n

    async def tek_kapat(self, pos_id: int, neden: str = "Manuel kapatma") -> bool:
        p = db.pos_getir(pos_id)
        if not p or p["durum"] != "ACIK":
            return False
        await self._kapat(p, neden)
        return True

    # ------------------------------------------------------------ yönetim
    async def pozisyonlari_yonet(self) -> None:
        pozlar = db.acik_pozisyonlar()
        if not pozlar:
            return
        simdi = datetime.now(timezone.utc)
        for p in pozlar:
            try:
                fiyat = await self.broker.fiyat(p["sembol"])
            except Exception as e:
                db.tlog(f"⚠️ {p['sembol']} fiyat hatası: {str(e)[:100]}")
                continue
            if fiyat <= 0:
                continue
            yon = xt._yon_birimi(p["taraf"])
            # stop-loss
            if (yon > 0 and fiyat <= float(p["sl"])) or \
               (yon < 0 and fiyat >= float(p["sl"])):
                await self._kapat(p, "🛑 Stop-Loss")
                continue
            # take-profit
            if (yon > 0 and fiyat >= float(p["tp"])) or \
               (yon < 0 and fiyat <= float(p["tp"])):
                await self._kapat(p, "✅ Take-Profit")
                continue
            # süre dolması
            try:
                acilis = datetime.fromisoformat(p["acilis_ts"])
                fark_h = (simdi - acilis).total_seconds() / 3600
                if fark_h >= config.POS_TIMEOUT_H:
                    await self._kapat(p, "⏱ Süre doldu")
            except (ValueError, TypeError):
                pass


# ---------------------------------------------------------------- singleton
oto = OtoTrader()
