"""Telegram Bildirim + İki Yönlü Uzaktan Komut Botu (Interactive Telegram Bot).

Özellikler:
  • Tüm giden mesajlar `mask_secrets` ile filtrelenir (Asla API anahtarı sızdırmaz).
  • Yalnızca `.env` içindeki `TELEGRAM_CHAT_ID` sahibinden gelen komutları kabul eder.
  • Desteklenen Uzaktan Komutlar:
      /durum  (veya /status) → Anlık Kasa, Özsermaye, Açık Pozisyonlar (PnL/ROE) ve Sigorta tablosu
      /kill   (veya /acil)   → Web panelini beklemeden TÜM POZİSYONLARI ACİL KAPATIR ve botu kilitler
      /durdur (veya /pause)  → Yeni işlem açılışını duraklatır
      /baslat (veya /resume) → Botu tekrar aktif eder
      /sigorta (veya /reset) → Circuit Breaker sigortasını sıfırlar
      /yardim (veya /help)   → Komut listesini gösterir
"""
from __future__ import annotations

import asyncio

from .security import mask_secrets, sanitize_external_text


async def send_telegram(token: str, chat_id: str, text: str):
    if not token or not chat_id:
        return
    clean_text = mask_secrets(text)
    try:
        import aiohttp

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with aiohttp.ClientSession() as s:
            await s.post(
                url,
                json={"chat_id": chat_id, "text": clean_text},
                timeout=10,
            )
    except Exception:
        pass


def make_alerter(
    token: str = "",
    chat_id: str = "",
    discord_webhook: str = "",
    pagerduty_routing_key: str = "",
):
    """Telegram + Discord Webhook + PagerDuty Events API v2 birleşik alarm dağıtıcısı döner."""
    from .alerts import MultiChannelAlerter

    return MultiChannelAlerter(
        telegram_token=token,
        telegram_chat_id=chat_id,
        discord_webhook_url=discord_webhook,
        pagerduty_routing_key=pagerduty_routing_key,
    )


class InteractiveTelegramBot:
    """İki yönlü Telegram komuta merkezi (`/durum`, `/kill`, `/durdur`, `/baslat`, `/sigorta`)."""

    def __init__(
        self,
        token: str = "",
        allowed_chat_id: str = "",
        executor=None,
        circuit_breaker=None,
        broker=None,
        poll_interval: float = 2.5,
    ):
        self.token = token.strip() if token else ""
        self.allowed_chat_id = str(allowed_chat_id).strip() if allowed_chat_id else ""
        self.executor = executor
        self.circuit_breaker = circuit_breaker
        self.broker = broker
        self.poll_interval = poll_interval
        self._last_update_id: int = 0
        self._running: bool = False

    def is_authorized(self, incoming_chat_id: str | int) -> bool:
        """Yalnızca yetkili TELEGRAM_CHAT_ID kullanıcısına izin verir."""
        if not self.allowed_chat_id:
            return False
        return str(incoming_chat_id).strip() == self.allowed_chat_id

    async def handle_command(
        self, raw_text: str, sender_chat_id: str | int | None = None
    ) -> str:
        """Gelen Telegram komutunu işler ve güvenli (maskelenmiş) yanıt metnini döner."""
        if sender_chat_id is not None and not self.is_authorized(sender_chat_id):
            return "⛔ Yetkisiz erişim reddedildi."

        clean = sanitize_external_text(raw_text, max_len=120).strip()
        if not clean:
            return ""
        cmd = clean.split()[0].lower()
        # '@bot_adi' uzantısını temizle (örn: /durum@kriptobot -> /durum)
        if "@" in cmd:
            cmd = cmd.split("@")[0]

        if cmd in ("/kill", "/acil", "/kapat"):
            if self.circuit_breaker is not None:
                self.circuit_breaker.trip("TELEGRAM UZAKTAN /kill ACİL DURDURMA")
            closed = 0
            if self.executor is not None:
                closed = await self.executor.close_all_positions(
                    "TELEGRAM /kill ACİL KAPAMA"
                )
            return mask_secrets(
                f"🚨 ACİL KILL-SWITCH AKTİF EDİLDİ!\n"
                f"• Kapatılan açık pozisyon: {closed}\n"
                f"• Bot durumu: KİLİTLENDİ (Yeni işlem açılmaz)"
            )

        if cmd in ("/durum", "/status", "/pnl"):
            return mask_secrets(await self._format_status_report())

        if cmd in ("/durdur", "/pause"):
            if self.circuit_breaker is not None:
                self.circuit_breaker.set_paused(True)
            return "⏸️ Bot duraklatıldı. Açık pozisyonlar korunuyor, yeni giriş yapılmayacak."

        if cmd in ("/baslat", "/resume"):
            if self.circuit_breaker is not None:
                self.circuit_breaker.set_paused(False)
            return "▶️ Bot tekrar aktif edildi."

        if cmd in ("/sigorta", "/reset"):
            if self.circuit_breaker is not None:
                self.circuit_breaker.reset()
            return "🔄 Circuit Breaker (Acil Durum Sigortası) sıfırlandı, bot aktif."

        if cmd in ("/yardim", "/help", "/start"):
            return (
                "🤖 KRIPTO-BOT Uzaktan Komuta Menüsü:\n"
                "• /durum — Anlık Kasa, PnL Tablosu ve Açık Pozisyonlar\n"
                "• /kill — 🚨 TÜM POZİSYONLARI ACİL KAPAT ve Botu Kilitle\n"
                "• /durdur — Yeni işlem açılışını duraklat\n"
                "• /baslat — İşlemleri devam ettir\n"
                "• /sigorta — Devre kesici sigortayı sıfırla"
            )

        return f"ℹ️ Bilinmeyen komut: {cmd}. Komut listesi için /yardim yazın."

    async def _format_status_report(self) -> str:
        bal = 0.0
        if self.broker is not None:
            try:
                bal = await self.broker.fetch_balance_usdt()
            except Exception:
                bal = getattr(getattr(self.broker, "paper", None), "balance", 0.0)
        unreal = (
            self.executor.total_unrealized_usdt()
            if self.executor is not None
            else 0.0
        )
        equity = bal + unreal
        cb_status = (
            self.circuit_breaker.snapshot()["status"]
            if self.circuit_breaker is not None
            else "AKTİF"
        )

        lines = [
            "📊 KRIPTO-BOT ANLIK DURUM RAPORU",
            f"• Durum: {cb_status}",
            f"• Nakit Kasa: ${bal:,.2f}",
            f"• Açık K/Z: ${unreal:+,.2f}",
            f"• Toplam Özsermaye: ${equity:,.2f}",
        ]
        if self.executor and self.executor.positions:
            lines.append(f"\n📌 AÇIK POZİSYONLAR ({len(self.executor.positions)}):")
            for sym, pos in self.executor.positions.items():
                px = self.executor.last_prices.get(sym, pos.entry)
                pnl_pct = self.executor.risk.profit_pct(pos, px)
                roe_pct = self.executor.risk.roe_pct(pos, px)
                usd = self.executor.risk.pnl_usdt(pos, px)
                lock = "🔒" if pos.locked_profit else ""
                lines.append(
                    f"  - {sym} {pos.side} ({pos.leverage}x, {pos.layers}. kademe) | "
                    f"Giriş: {pos.entry:,.4f} → Fiyat: {px:,.4f} | "
                    f"PnL: %{pnl_pct:+.2f} (ROE %{roe_pct:+.1f} / ${usd:+.2f}) | "
                    f"Stop: {pos.stop:,.4f}{lock}"
                )
        else:
            lines.append("\n📌 Açık pozisyon bulunmuyor.")
        return "\n".join(lines)

    async def poll_forever(self):
        """Telegram getUpdates üzerinden uzun-yoklama (long-polling) ile komutları dinler."""
        if not self.token or not self.allowed_chat_id:
            return
        import aiohttp

        self._running = True
        base_url = f"https://api.telegram.org/bot{self.token}"
        async with aiohttp.ClientSession() as session:
            while self._running:
                try:
                    params = {"timeout": 10, "offset": self._last_update_id + 1}
                    async with session.get(
                        f"{base_url}/getUpdates", params=params, timeout=15
                    ) as resp:
                        data = await resp.json()
                    for upd in data.get("result", []):
                        uid = int(upd.get("update_id", 0))
                        if uid > self._last_update_id:
                            self._last_update_id = uid
                        msg = upd.get("message") or upd.get("edited_message") or {}
                        chat_id = str(msg.get("chat", {}).get("id", ""))
                        text = msg.get("text", "")
                        if not text or not text.startswith("/"):
                            continue
                        reply = await self.handle_command(text, sender_chat_id=chat_id)
                        if reply and self.is_authorized(chat_id):
                            await session.post(
                                f"{base_url}/sendMessage",
                                json={"chat_id": chat_id, "text": mask_secrets(reply)},
                                timeout=10,
                            )
                except Exception:
                    await asyncio.sleep(self.poll_interval)
                await asyncio.sleep(0.5)

    def stop(self):
        self._running = False
