"""Telegram Bildirim + İki Yönlü Uzaktan Komut Botu (Interactive Telegram Bot).

Özellikler:
  • Tüm giden mesajlar `mask_secrets` ile filtrelenir (Asla API anahtarı sızdırmaz).
  • Yalnızca `.env` içindeki `TELEGRAM_CHAT_ID` sahibinden gelen komutları kabul eder.
  • Desteklenen Uzaktan Komutlar:
      /durum  (veya /status) → Anlık kasa, gerçekleşen/açık K/Z ve pozisyon tablosu
      /guncel (veya güncel)  → Borsadan taze fiyatlarla yalnızca açık pozisyonlar
      /karzar (veya /pnl)    → Gerçekleşen + gerçekleşmemiş anlık kâr/zarar özeti
      /kill   (veya /acil)   → Web panelini beklemeden TÜM POZİSYONLARI ACİL KAPATIR ve botu kilitler
      /durdur (veya /pause)  → Yeni işlem açılışını duraklatır
      /baslat (veya /resume) → Botu tekrar aktif eder
      /sigorta (veya /reset) → Circuit Breaker sigortasını sıfırlar
      /yardim (veya /help)   → Komut listesini gösterir
"""
from __future__ import annotations

import asyncio
import time
import re
from datetime import datetime, timezone

from .security import mask_secrets, register_secret, sanitize_external_text


def _normalize_telegram_credentials(token: str, chat_id: str | int) -> tuple[str, str]:
    raw_tok = str(token or "").strip().strip("\"'").strip()
    match_tok = re.search(r"(\d{6,15}:[A-Za-z0-9_-]{20,})", raw_tok)
    tok = match_tok.group(1) if match_tok else raw_tok
    if re.match(r"(?i)^bot\d{6,}:", tok):
        tok = tok[3:]
    if tok:
        register_secret(tok)

    raw_cid = str(chat_id or "").strip().strip("\"'").strip()
    if raw_cid.startswith("@"):
        cid = raw_cid.split()[0]
    else:
        match_cid = re.search(r"(-?\d{5,20})", raw_cid)
        cid = match_cid.group(1) if match_cid else raw_cid
    return tok, cid


async def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Telegram mesajını gönderir ve API'nin onayını döndürür.

    Telegram'ın 4096 karakter sınırı için güvenli kısaltma yapılır. HTTP/API
    hataları sessizce yutulmaz; token içeren URL ise asla loglanmaz.
    """
    token, chat_id = _normalize_telegram_credentials(token, chat_id)
    if not token or not chat_id:
        return False
    clean_text = mask_secrets(text)
    if len(clean_text) > 4000:
        clean_text = clean_text[:3950] + "\n… [rapor kısaltıldı]"
    try:
        import aiohttp

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"chat_id": chat_id, "text": clean_text},
                timeout=10,
            ) as response:
                data = await response.json(content_type=None)
                if response.status == 200 and isinstance(data, dict) and data.get("ok"):
                    return True
                description = (
                    sanitize_external_text(str(data.get("description", "")), max_len=160)
                    if isinstance(data, dict)
                    else ""
                )
                print(
                    f"⚠️ Telegram mesajı reddedildi (HTTP {response.status}): {description}",
                    flush=True,
                )
                return False
    except Exception as exc:
        print(
            f"⚠️ Telegram gönderim hatası ({type(exc).__name__}); "
            "ağ veya API ayarlarını kontrol edin.",
            flush=True,
        )
        return False


def make_alerter(
    token: str = "",
    chat_id: str = "",
    discord_webhook: str = "",
    pagerduty_routing_key: str = "",
    whatsapp_phone: str = "",
    whatsapp_api_key: str = "",
    whatsapp_cloud_token: str = "",
    whatsapp_phone_number_id: str = "",
    whatsapp_webhook_url: str = "",
):
    """Telegram + WhatsApp + Discord Webhook + PagerDuty birleşik alarm dağıtıcısı döner."""
    from .alerts import MultiChannelAlerter

    token, chat_id = _normalize_telegram_credentials(token, chat_id)
    return MultiChannelAlerter(
        telegram_token=token,
        telegram_chat_id=chat_id,
        discord_webhook_url=discord_webhook,
        pagerduty_routing_key=pagerduty_routing_key,
        whatsapp_phone=whatsapp_phone,
        whatsapp_api_key=whatsapp_api_key,
        whatsapp_cloud_token=whatsapp_cloud_token,
        whatsapp_phone_number_id=whatsapp_phone_number_id,
        whatsapp_webhook_url=whatsapp_webhook_url,
    )


def telegram_message_chunks(text: str) -> list[str]:
    """Telegram 4096 sınırı için satır bazlı, güvenli boyutta mesaj parçaları."""
    clean = mask_secrets(text)
    chunks: list[str] = []
    current = ""
    for line in clean.splitlines(keepends=True):
        if len(line) > 3900:
            line = line[:3850] + "\n… [satır kısaltıldı]\n"
        if current and len(current) + len(line) > 3900:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks or [clean]


async def send_telegram_long(token: str, chat_id: str, text: str) -> bool:
    """Uzun günlük raporu Telegram sınırını aşmadan parçalara böler."""
    chunks = telegram_message_chunks(text)
    ok = True
    for index, chunk in enumerate(chunks, 1):
        prefix = f"({index}/{len(chunks)})\n" if len(chunks) > 1 else ""
        ok = await send_telegram(token, chat_id, prefix + chunk) and ok
        if index < len(chunks):
            await asyncio.sleep(0.2)
    return ok


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
        state_store=None,
        news_engine=None,
        periodic_reports: bool = False,
        report_interval_sec: float = 300.0,
        initial_report_delay_sec: float = 10.0,
        detailed_reports: bool = True,
        whatsapp_cfg: dict | None = None,
    ):
        self.token, self.allowed_chat_id = _normalize_telegram_credentials(
            token, allowed_chat_id
        )
        self.whatsapp_cfg: dict = dict(whatsapp_cfg or {})
        self.executor = executor
        self.circuit_breaker = circuit_breaker
        self.broker = broker
        self.state_store = state_store
        self.news_engine = news_engine
        self.periodic_reports = bool(periodic_reports)
        self.report_interval_sec = max(0.1, float(report_interval_sec))
        self.initial_report_delay_sec = max(0.0, float(initial_report_delay_sec))
        self.detailed_reports = bool(detailed_reports)
        self.poll_interval = poll_interval
        self.report_stats = {
            "sent": 0,
            "failed": 0,
            "last_attempt_ts": None,
            "last_success_ts": None,
            "last_error": "",
        }
        self._last_update_id: int = 0
        self._prime_updates = True
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
        plain = clean.casefold()

        if cmd in ("/rapor", "/ozet") or plain == "rapor":
            return mask_secrets(await self._format_periodic_report())

        if cmd in ("/gunluk", "/günlük", "/daily") or plain in {"günlük", "gunluk"}:
            return mask_secrets(await self._format_daily_report())

        if cmd in ("/piyasa", "/market", "/analiz") or plain in {"piyasa", "analiz"}:
            return mask_secrets(await self._format_market_report())

        if cmd in ("/guncel", "/güncel", "/pozisyonlar", "/positions") or plain in {
            "güncel", "guncel", "pozisyonlar", "açık pozisyonlar", "acik pozisyonlar",
        }:
            return mask_secrets(await self._format_positions_report())

        if cmd in ("/karzar", "/kârzar", "/pnl", "/k-z") or plain in {
            "kar zarar", "kâr zarar", "karzar", "kârzar", "pnl", "k/z", "kâr/zarar",
        }:
            return mask_secrets(await self._format_pnl_report())

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

        if cmd in ("/durum", "/status") or plain == "durum":
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
                "• /durum — Anlık kasa, K/Z ve açık pozisyonlar\n"
                "• /guncel veya güncel — Güncel fiyatlarla yalnızca açık pozisyonlar\n"
                "• /piyasa — MA/EMA/RSI/MACD, para akışı, funding ve haberler\n"
                "• /rapor — Otomatik gönderilen kompakt durum/analiz raporu\n"
                "• /gunluk — Oturumun başlangıcından beri ayrıntılı günlük sonuç\n"
                "• /karzar veya /pnl — Gerçekleşen ve açık K/Z özeti\n"
                "• /kill — 🚨 TÜM POZİSYONLARI ACİL KAPAT ve Botu Kilitle\n"
                "• /durdur — Yeni işlem açılışını duraklat\n"
                "• /baslat — İşlemleri devam ettir\n"
                "• /sigorta — Devre kesici sigortayı sıfırla"
            )

        return f"ℹ️ Bilinmeyen komut: {cmd}. Komut listesi için /yardim yazın."

    async def _fetch_balance(self) -> float:
        if self.broker is None:
            return 0.0
        fetch_balance = getattr(self.broker, "fetch_balance_usdt", None)
        if callable(fetch_balance):
            try:
                return float(await asyncio.wait_for(fetch_balance(), timeout=8))
            except Exception:
                pass
        paper = getattr(self.broker, "paper", None)
        return float(getattr(paper, "balance", 0.0) or 0.0)

    async def _refresh_position_prices(self) -> dict[str, tuple[float, bool]]:
        """Açık pozisyonların fiyatını kendi borsasından eşzamanlı tazeler.

        Borsa okunamazsa son bilinen fiyat kullanılır ve raporda açıkça
        ``önbellek`` olarak işaretlenir; bayat fiyat canlı gibi gösterilmez.
        """
        if self.executor is None or not self.executor.positions:
            return {}

        async def fetch_one(symbol, pos):
            cached = float(self.executor.last_prices.get(symbol, pos.entry) or pos.entry)
            if self.broker is None:
                return symbol, (cached, False)
            try:
                price = float(
                    await asyncio.wait_for(
                        self.broker.fetch_price(
                            symbol, exchange=getattr(pos, "exchange", None) or None
                        ),
                        timeout=8,
                    )
                )
                if price <= 0:
                    raise ValueError("Geçersiz fiyat")
                self.executor.last_prices[symbol] = price
                return symbol, (price, True)
            except Exception:
                return symbol, (cached, False)

        rows = await asyncio.gather(
            *(fetch_one(symbol, pos) for symbol, pos in self.executor.positions.items())
        )
        return dict(rows)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")

    def _position_lines(self, quotes: dict[str, tuple[float, bool]]) -> list[str]:
        if self.executor is None or not self.executor.positions:
            return ["📌 Açık pozisyon bulunmuyor."]
        lines = [f"📌 AÇIK POZİSYONLAR ({len(self.executor.positions)}):"]
        for sym, pos in self.executor.positions.items():
            px, fresh = quotes.get(
                sym, (self.executor.last_prices.get(sym, pos.entry), False)
            )
            pnl_pct = self.executor.risk.profit_pct(pos, px)
            roe_pct = self.executor.risk.roe_pct(pos, px)
            usd = self.executor.risk.pnl_usdt(pos, px)
            lock = "🔒" if pos.locked_profit else ""
            price_source = "canlı" if fresh else "önbellek"
            exchange = getattr(pos, "exchange", "") or "varsayılan"
            lines.append(
                f"  - {sym} {pos.side} [{exchange}] "
                f"({pos.leverage}x, {pos.layers}. kademe)\n"
                f"    Giriş: {pos.entry:,.4f} → Fiyat: {px:,.4f} ({price_source})\n"
                f"    K/Z: ${usd:+,.2f} | Fiyat %{pnl_pct:+.2f} | ROE %{roe_pct:+.1f}\n"
                f"    Miktar: {pos.qty:.8f} | Stop: {pos.stop:,.4f}{lock}"
            )
            get_plan = getattr(self.executor, "get_trade_plan", None)
            plan = get_plan(sym) if callable(get_plan) else None
            if plan:
                lines.append(
                    f"    Plan {plan.get('source', 'R')}: R {float(plan.get('initial_risk', 0)):,.4f} | "
                    f"TP1 {float(plan.get('tp1', 0)):,.4f} ({'tamam' if plan.get('tp1_hit') else 'bekliyor'}) | "
                    f"TP2 {float(plan.get('tp2', 0)):,.4f}"
                )
        return lines

    def _pnl_lines(self, bal: float, unreal: float) -> list[str]:
        stats = getattr(self.executor, "stats", {}) if self.executor is not None else {}
        realized = float(stats.get("pnl_usdt_sum", 0.0) or 0.0)
        trades = int(stats.get("trades", 0) or 0)
        wins = int(stats.get("wins", 0) or 0)
        losses = int(stats.get("losses", 0) or 0)
        cb_status = (
            self.circuit_breaker.snapshot()["status"]
            if self.circuit_breaker is not None
            else "AKTİF"
        )
        lines = [
            f"• Durum: {cb_status}",
            f"• Nakit Kasa: ${bal:,.2f}",
            f"• Gerçekleşen fiyat K/Z (brüt, bu oturum): ${realized:+,.2f}",
            f"• Açık K/Z: ${unreal:+,.2f}",
        ]
        paper = getattr(self.broker, "paper", None) if self.broker is not None else None
        if paper is not None and getattr(self.broker, "mode", "") == "paper":
            fees = float(getattr(paper, "total_fees_usdt", 0.0) or 0.0)
            funding = float(getattr(paper, "total_funding_usdt", 0.0) or 0.0)
            start_balance = float(getattr(paper, "start_balance", bal) or bal)
            total_pnl = bal - start_balance + unreal
            lines.extend(
                [
                    f"• Toplam komisyon: ${fees:,.2f}",
                    f"• Funding (ödeme - / alacak +): ${funding:+,.2f}",
                    f"• Net Paper K/Z: ${total_pnl:+,.2f}",
                ]
            )
        else:
            lines.append(f"• Toplam K/Z: ${realized + unreal:+,.2f}")
        lines.extend(
            [
                f"• Toplam Özsermaye: ${bal + unreal:,.2f}",
                f"• Kapanan işlem: {trades} ({wins} kâr / {losses} zarar)",
            ]
        )
        return lines

    async def _financial_snapshot(self):
        quotes, bal = await asyncio.gather(
            self._refresh_position_prices(), self._fetch_balance()
        )
        unreal = (
            self.executor.total_unrealized_usdt()
            if self.executor is not None
            else 0.0
        )
        return quotes, float(bal), float(unreal)

    async def _format_market_report(self) -> str:
        scores = {}
        if self.state_store is not None:
            try:
                scores = self.state_store.get_meta("live_scores", {}) or {}
            except Exception:
                scores = {}
        lines = ["📈 CANLI PİYASA / TEKNİK ANALİZ", f"🕒 {self._timestamp()}"]
        if not scores:
            lines.append("Henüz kapanmış mum ve piyasa verisi oluşmadı.")
        for symbol, row in list(scores.items())[:6]:
            if not isinstance(row, dict):
                continue

            def fmt(key, digits=2):
                value = row.get(key)
                if value is None:
                    return "—"
                try:
                    return f"{float(value):,.{digits}f}"
                except (TypeError, ValueError):
                    return "—"

            funding = row.get("funding_rate")
            funding_text = "—" if funding is None else f"{float(funding) * 100:+.4f}%"
            lines.extend(
                [
                    f"\n• {symbol} — {row.get('signal', 'YOK')} / skor {fmt('total', 1)}",
                    f"  Fiyat: {fmt('price', 4)} | MA20/50: {fmt('ma20', 4)} / {fmt('ma50', 4)}",
                    f"  EMA9/21/50/200: {fmt('ema9', 4)} / {fmt('ema21', 4)} / {fmt('ema50', 4)} / {fmt('ema200', 4)}",
                    f"  RSI(14): {fmt('rsi', 1)} | MACD: {fmt('macd', 4)} / Sinyal: {fmt('macd_signal', 4)} / Hist: {fmt('macd_hist', 4)}",
                    f"  Rejim: {row.get('regime', '—')} / {row.get('setup', '—')} | ADX: {fmt('adx', 1)} | "
                    f"Supertrend: {'LONG' if float(row.get('supertrend_direction', 1) or 1) >= 0 else 'SHORT'} @ {fmt('supertrend', 4)}",
                    f"  VWAP Gün/Hafta/Anchored: {fmt('session_vwap', 4)} / {fmt('weekly_vwap', 4)} / {fmt('anchored_vwap', 4)} | "
                    f"Mum VP (yaklaşık) POC/VAH/VAL: {fmt('volume_profile_poc', 4)} / {fmt('volume_profile_vah', 4)} / {fmt('volume_profile_val', 4)}",
                    f"  Para akışı: {fmt('para_akisi', 1)} | Bid/Ask: {fmt('bid_ask_ratio', 2)} | Funding: {funding_text}",
                    f"  Hacim Z: {fmt('volume_zscore', 2)} | OI: {row.get('oi_signal', '—')} ({fmt('oi_change_pct', 2)}%) | "
                    f"CVD: {row.get('oi_flow_confirmation', '—')}",
                ]
            )
            lines.append(
                f"  Order-flow: CVD div {row.get('cvd_divergence', 'YOK')} | "
                f"Absorption {row.get('absorption', 'YOK')}"
            )
            if int(row.get("vpvr_trades", 0) or 0) > 0:
                lines.append(
                    f"  Tick VPVR POC/VAH/VAL: {fmt('vpvr_poc', 4)} / {fmt('vpvr_vah', 4)} / {fmt('vpvr_val', 4)} | "
                    f"{int(row.get('vpvr_trades', 0) or 0)} trade, {fmt('vpvr_coverage_sec', 0)}sn "
                    f"({'hazır' if row.get('vpvr_warm') else 'ısınıyor'})"
                )
            if row.get("entry_block_reason"):
                lines.append(f"  ⏸️ Giriş notu: {row['entry_block_reason']}")
        if self.news_engine is not None:
            mood = self.news_engine.mood()
            lines.extend(
                [
                    "\n📰 HABER AKIŞI",
                    f"• Duygu skoru: {mood.get('score', 0):+.1f} | Korku/Açgözlülük: {mood.get('fear_greed', 50):.1f}",
                    f"• Giriş vetosu: {'VAR' if mood.get('veto') else 'yok'}",
                ]
            )
            latest = mood.get("latest") or {}
            if latest.get("title"):
                title = sanitize_external_text(latest["title"], max_len=140)
                lines.append(f"• Son: {title} [{latest.get('source', '')}]")
        return "\n".join(lines)

    async def _format_status_report(self) -> str:
        quotes, bal, unreal = await self._financial_snapshot()
        lines = [
            "📊 KRIPTO-BOT ANLIK DURUM RAPORU",
            f"🕒 {self._timestamp()}",
            *self._pnl_lines(bal, unreal),
            "",
            *self._position_lines(quotes),
        ]
        if quotes and any(not fresh for _, fresh in quotes.values()):
            lines.append("⚠️ Önbellek işaretli fiyatlar borsadan şu anda tazelenemedi.")
        return "\n".join(lines)

    async def _format_daily_report(self) -> str:
        """Seçili paper oturumunun (veya son 24 saatin) finansal sonuç raporu."""
        quotes, bal, unreal = await self._financial_snapshot()
        now = time.time()
        session = {}
        trades: list[dict] = []
        if self.state_store is not None:
            try:
                session = self.state_store.get_meta("paper_24h_session", {}) or {}
                start_ts = float(session.get("start_ts", now - 86400) or now - 86400)
                trades = self.state_store.get_trades_since(start_ts, now)
            except Exception:
                session = {}
        start_ts = float(session.get("start_ts", now - 86400) or now - 86400)
        start_balance = float(session.get("start_balance", bal) or bal)
        start_equity = float(session.get("start_equity", start_balance) or start_balance)
        equity = bal + unreal
        def trade_net(trade):
            if trade.get("net_pnl_usdt") is not None:
                return float(trade.get("net_pnl_usdt") or 0.0)
            return (
                float(trade.get("pnl_usdt", 0.0) or 0.0)
                - float(trade.get("entry_fee_usdt", 0.0) or 0.0)
                - float(trade.get("exit_fee_usdt", 0.0) or 0.0)
                + float(trade.get("funding_usdt", 0.0) or 0.0)
            )

        realized = sum(float(t.get("pnl_usdt", 0.0) or 0.0) for t in trades)
        realized_net = sum(trade_net(t) for t in trades)
        wins = sum(trade_net(t) > 0 for t in trades)
        losses = sum(trade_net(t) < 0 for t in trades)
        flats = len(trades) - wins - losses
        win_rate = wins / len(trades) * 100 if trades else 0.0
        positions = getattr(self.executor, "positions", {}) if self.executor else {}
        used_margin = sum(float(p.margin_usdt or 0.0) for p in positions.values())
        elapsed_min = max(0.0, (now - start_ts) / 60.0)

        paper = getattr(self.broker, "paper", None) if self.broker is not None else None
        fee_text = "• Komisyon/Funding: canlı borsa ekstresinden ayrıca doğrulanmalı"
        if paper is not None and getattr(self.broker, "mode", "") == "paper":
            fees_now = float(getattr(paper, "total_fees_usdt", 0.0) or 0.0)
            funding_now = float(getattr(paper, "total_funding_usdt", 0.0) or 0.0)
            fees = max(0.0, fees_now - float(session.get("start_fees", 0.0) or 0.0))
            funding = funding_now - float(session.get("start_funding", 0.0) or 0.0)
            fee_text = (
                f"• Komisyon: ${fees:,.2f} | Funding (ödeme - / alacak +): ${funding:+,.2f}\n"
                "• Gerçekleşen fiyat K/Z satırı brüt fiyat K/Z'sidir; kapalı işlem NET K/Z'si ve NET OTURUM K/Z ücret/funding içerir."
            )

        by_symbol: dict[str, dict] = {}
        by_reason: dict[str, dict] = {}
        by_exchange: dict[str, dict] = {}
        for trade in trades:
            pnl = float(trade.get("pnl_usdt", 0.0) or 0.0)
            net = trade_net(trade)
            for table, key in (
                (by_symbol, str(trade.get("symbol") or "—")),
                (by_reason, str(trade.get("reason") or "—")),
                (by_exchange, str(trade.get("exchange") or "BELİRSİZ")),
            ):
                row = table.setdefault(key, {"count": 0, "pnl": 0.0, "net": 0.0})
                row["count"] += 1
                row["pnl"] += pnl
                row["net"] += net

        def top_rows(table: dict[str, dict], limit: int = 8) -> list[str]:
            rows = sorted(table.items(), key=lambda item: abs(item[1]["pnl"]), reverse=True)
            return [
                f"  {key}: {row['count']} işlem | ${row['pnl']:+,.2f} | net ${row['net']:+,.2f}"
                for key, row in rows[:limit]
            ] or ["  Henüz kapanan işlem yok."]

        session_title = f"📅 {float(session.get('hours', 24)):g} SAATLİK PAPER SONUÇ RAPORU"
        lines = [
            session_title if session else "📅 SON 24 SAAT SONUÇ RAPORU",
            f"🕒 {self._timestamp()} | Oturum: {elapsed_min / 60:.2f} saat",
            f"• Başlangıç kasası: ${start_balance:,.2f}",
            f"• Başlangıç özsermayesi: ${start_equity:,.2f}",
            f"• Bitiş/anlık kasa: ${bal:,.2f}",
            f"• Bitiş/anlık özsermaye: ${equity:,.2f}",
            f"• NET OTURUM K/Z: ${equity - start_equity:+,.2f}",
            f"• Gerçekleşen fiyat K/Z (brüt): ${realized:+,.2f} | Açık K/Z: ${unreal:+,.2f}",
            f"• Kapalı işlemlerin NET K/Z'si (ücret/funding dahil): ${realized_net:+,.2f}",
            fee_text,
            (
                f"• Açılan işlem: {int(session.get('entries', 0))} | "
                if session else "• Açılan işlem: bu kayıtta sayaç yok | "
            ) + f"Kapanan işlem: {len(trades)} | {wins} kâr / {losses} zarar / {flats} başa baş",
            f"• Kazanma oranı: %{win_rate:.1f} (net) | Açık pozisyon: {len(positions)}",
            f"• Kullanılan marj: ${used_margin:,.2f} | Serbest kasa: ${max(0.0, bal - used_margin):,.2f}",
            "",
            "🏦 BORSA BAZINDA KAPANAN SONUÇLAR (brüt | net)",
            *top_rows(by_exchange),
            "",
            "🏷️ SEMBOL BAZINDA KAPANAN SONUÇLAR",
            *top_rows(by_symbol),
            "",
            "🚪 ÇIKIŞ NEDENLERİ",
            *top_rows(by_reason),
            "",
            *self._position_lines(quotes),
        ]
        if quotes and any(not fresh for _, fresh in quotes.values()):
            lines.append("⚠️ Bazı açık pozisyon fiyatları önbellekten; nihai KZ değişebilir.")
        return "\n".join(lines)

    async def _send_whatsapp_if_enabled(self, text: str, *, long_msg: bool = False) -> bool:
        if not self.whatsapp_cfg:
            return False
        from .whatsapp import is_whatsapp_configured, send_whatsapp, send_whatsapp_long

        kw = {
            "phone": self.whatsapp_cfg.get("phone", ""),
            "api_key": self.whatsapp_cfg.get("api_key", ""),
            "cloud_token": self.whatsapp_cfg.get("cloud_token", ""),
            "phone_number_id": self.whatsapp_cfg.get("phone_number_id", ""),
            "webhook_url": self.whatsapp_cfg.get("webhook_url", ""),
        }
        if not is_whatsapp_configured(**kw):
            return False
        return await (send_whatsapp_long(text, **kw) if long_msg else send_whatsapp(text, **kw))

    async def send_daily_report(self, text: str | None = None) -> bool:
        text = text if text is not None else await self._format_daily_report()
        wa_ok = await self._send_whatsapp_if_enabled(text, long_msg=True)
        if not self.token or not self.allowed_chat_id:
            if not wa_ok:
                print("⚠️ Günlük rapor gönderilemedi: Telegram token/chat ID eksik.", flush=True)
            return wa_ok
        tg_ok = await send_telegram_long(self.token, self.allowed_chat_id, text)
        return tg_ok or wa_ok

    async def _format_positions_report(self) -> str:
        quotes = await self._refresh_position_prices()
        lines = [
            "📌 GÜNCEL AÇIK POZİSYONLAR",
            f"🕒 {self._timestamp()}",
            *self._position_lines(quotes),
        ]
        if quotes and any(not fresh for _, fresh in quotes.values()):
            lines.append("⚠️ Önbellek işaretli fiyatlar borsadan şu anda tazelenemedi.")
        return "\n".join(lines)

    async def _format_pnl_report(self) -> str:
        quotes, bal, unreal = await self._financial_snapshot()
        lines = [
            "💰 KRIPTO-BOT ANLIK KÂR/ZARAR",
            f"🕒 {self._timestamp()}",
            *self._pnl_lines(bal, unreal),
        ]
        if quotes and any(not fresh for _, fresh in quotes.values()):
            lines.append("⚠️ Açık K/Z hesabında bazı fiyatlar önbellekten geliyor.")
        return "\n".join(lines)

    async def _format_periodic_report(self) -> str:
        """Otomatik gönderim için kompakt, tek mesajlık gerçek durum analizi."""
        quotes, bal, unreal = await self._financial_snapshot()
        status, scores = {}, {}
        if self.state_store is not None:
            try:
                status = self.state_store.get_meta("bot_status", {}) or {}
                scores = self.state_store.get_meta("live_scores", {}) or {}
            except Exception:
                pass
        now = time.time()
        status_ts = float(status.get("ts", 0) or 0)
        status_age = max(0.0, now - status_ts) if status_ts else None
        status_health = (
            "BAŞLANGIÇ" if status_age is None else ("GÜNCEL" if status_age < 60 else "BAYAT")
        )
        market_meta = status.get("market_data", {}) or {}
        last_message = float(market_meta.get("last_message_ts", 0) or 0)
        ws_age = max(0.0, now - last_message) if last_message else None
        ws_health = (
            "bilinmiyor" if ws_age is None else ("canlı" if ws_age <= 30 else "gecikmeli")
        )
        mode = str(status.get("mode") or getattr(self.broker, "mode", "paper")).upper()
        exchange = str(
            status.get("primary_exchange") or getattr(self.broker, "primary", "—")
        ).upper()
        cb_status = (
            self.circuit_breaker.snapshot()["status"]
            if self.circuit_breaker is not None
            else "AKTİF"
        )
        report_title = (
            "OTOMATİK BOT ANALİZİ" if self.detailed_reports else "OTOMATİK GENEL DURUM"
        )
        lines = [
            f"🤖 {report_title} — {mode}",
            f"🕒 {self._timestamp()}",
            f"• Motor: {cb_status} | Borsa: {exchange} | Durum kaydı: {status_health}",
            f"• Veri: {market_meta.get('market_type', '—')} / {ws_health}"
            + (
                f" ({ws_age:.0f}sn önce)"
                if ws_age is not None
                else ""
            )
            + f" | Gecikme: {float(market_meta.get('latency_ms', 0) or 0):.0f}ms",
            *self._pnl_lines(bal, unreal),
        ]

        if self.executor is None or not self.executor.positions:
            lines.append("📌 Açık pozisyon yok.")
        else:
            lines.append(f"📌 POZİSYONLAR ({len(self.executor.positions)}):")
            for symbol, pos in self.executor.positions.items():
                price, fresh = quotes.get(
                    symbol, (self.executor.last_prices.get(symbol, pos.entry), False)
                )
                pnl = self.executor.risk.pnl_usdt(pos, price)
                roe = self.executor.risk.roe_pct(pos, price)
                lines.append(
                    f"- {symbol} {pos.side}: {pos.entry:,.4f}→{price:,.4f} | "
                    f"${pnl:+,.2f} / ROE %{roe:+.1f} | "
                    f"{'canlı' if fresh else 'önbellek'} | Stop {pos.stop:,.4f}"
                )
                get_plan = getattr(self.executor, "get_trade_plan", None)
                plan = get_plan(symbol) if callable(get_plan) else None
                if plan:
                    lines.append(
                        f"  {plan.get('source', 'R')} planı | TP1 {float(plan.get('tp1', 0)):,.4f} "
                        f"({'tamam' if plan.get('tp1_hit') else 'bekliyor'}) | TP2 {float(plan.get('tp2', 0)):,.4f}"
                    )

        if not self.detailed_reports:
            if mode == "PAPER":
                lines.append("ℹ️ Gerçek piyasa verisi + sanal emir; gerçek para kullanılmıyor.")
            return "\n".join(lines)

        lines.append("📈 TEKNİK / PARA AKIŞI:")
        if not scores:
            lines.append("- Kapanmış mum analizi henüz bekleniyor.")
        for symbol, row in list(scores.items())[:4]:
            if not isinstance(row, dict):
                continue

            def number(key, default=0.0):
                try:
                    value = row.get(key, default)
                    return default if value is None else float(value)
                except (TypeError, ValueError):
                    return default

            ema_relation = (
                "EMA9>21" if number("ema9") > number("ema21") else "EMA9≤21"
            )
            ma_relation = (
                "MA20>50" if number("ma20") > number("ma50") else "MA20≤50"
            )
            funding = row.get("funding_rate")
            funding_text = "—" if funding is None else f"{float(funding) * 100:+.3f}%"
            lines.append(
                f"- {symbol} {row.get('signal', 'YOK')}({number('total'):+.0f}) | "
                f"{row.get('regime', '—')}/{row.get('setup', '—')} | "
                f"RSI {number('rsi', 50):.1f} | {ema_relation}/{ma_relation} | "
                f"MACD-H {number('macd_hist'):+.4f}"
            )
            lines.append(
                f"  Fiyat {number('price'):,.4f} | Akış {number('para_akisi'):+.1f} | "
                f"Bid/Ask {number('bid_ask_ratio', 1):.2f} | Funding {funding_text}"
            )
            lines.append(
                f"  ST {number('supertrend'):,.4f} | VWAP {number('session_vwap'):,.4f} | "
                f"MumPOC~ {number('volume_profile_poc'):,.4f} | HacimZ {number('volume_zscore'):+.1f} | "
                f"OI {row.get('oi_signal', '—')}"
            )
            lines.append(
                f"  Div {row.get('cvd_divergence', 'YOK')} | Abs {row.get('absorption', 'YOK')} | "
                f"TickPOC {number('vpvr_poc'):,.4f} ({int(row.get('vpvr_trades', 0) or 0)} trade)"
            )
            if row.get("entry_block_reason"):
                lines.append(f"  ⏸️ {row['entry_block_reason']}")

        if self.news_engine is not None:
            mood = self.news_engine.mood()
            lines.append(
                f"📰 Haber: {mood.get('score', 0):+.1f} | FG {mood.get('fear_greed', 50):.1f} | "
                f"Veto {'VAR' if mood.get('veto') else 'yok'}"
            )
            latest = mood.get("latest") or {}
            if latest.get("title"):
                lines.append(
                    f"  Son: {sanitize_external_text(latest['title'], max_len=90)}"
                )
        if mode == "PAPER":
            lines.append("ℹ️ Gerçek piyasa verisi + sanal emir; gerçek para kullanılmıyor.")
        return "\n".join(lines)

    async def periodic_report_forever(self):
        """Yapılandırılan aralıkta otomatik Telegram durum/analiz bildirimi gönderir."""
        if not self.periodic_reports or not self.token or not self.allowed_chat_id:
            return
        self._running = True
        await asyncio.sleep(self.initial_report_delay_sec)
        while self._running:
            self.report_stats["last_attempt_ts"] = time.time()
            try:
                report = await self._format_periodic_report()
                delivered = await send_telegram(
                    self.token, self.allowed_chat_id, report
                )
                await self._send_whatsapp_if_enabled(report, long_msg=False)
                if delivered:
                    self.report_stats["sent"] += 1
                    self.report_stats["last_success_ts"] = time.time()
                    self.report_stats["last_error"] = ""
                    print("📨 Otomatik Telegram durum/analiz raporu gönderildi.", flush=True)
                else:
                    self.report_stats["failed"] += 1
                    self.report_stats["last_error"] = "Telegram API gönderimi doğrulanamadı"
            except Exception as exc:
                self.report_stats["failed"] += 1
                self.report_stats["last_error"] = type(exc).__name__
                print(
                    f"⚠️ Otomatik Telegram raporu üretilemedi ({type(exc).__name__}).",
                    flush=True,
                )
            await asyncio.sleep(self.report_interval_sec)

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
                    priming = self._prime_updates
                    params = {"timeout": 10, "offset": self._last_update_id + 1}
                    if priming:
                        # Restart öncesindeki /kill gibi kuyrukta kalmış komutları
                        # çalıştırmadan tüket; yalnızca bundan sonraki mesajları işle.
                        params.update({"offset": -1, "limit": 1, "timeout": 0})
                    async with session.get(
                        f"{base_url}/getUpdates", params=params, timeout=15
                    ) as resp:
                        data = await resp.json()
                    if not isinstance(data, dict) or not data.get("ok"):
                        raise RuntimeError("Telegram getUpdates başarısız")
                    if priming:
                        self._prime_updates = False
                        pending = data.get("result", [])
                        if pending:
                            self._last_update_id = max(
                                int(item.get("update_id", 0)) for item in pending
                            )
                        continue
                    for upd in data.get("result", []):
                        uid = int(upd.get("update_id", 0))
                        if uid > self._last_update_id:
                            self._last_update_id = uid
                        msg = upd.get("message") or upd.get("edited_message") or {}
                        chat_id = str(msg.get("chat", {}).get("id", ""))
                        text = msg.get("text", "")
                        # Yetkisiz sohbetlerde komut GÖVDESİ de çalıştırılmaz.
                        if not text or not self.is_authorized(chat_id):
                            continue
                        reply = await self.handle_command(text, sender_chat_id=chat_id)
                        if reply:
                            chunks = telegram_message_chunks(reply)
                            for index, chunk in enumerate(chunks, 1):
                                prefix = f"({index}/{len(chunks)})\n" if len(chunks) > 1 else ""
                                await session.post(
                                    f"{base_url}/sendMessage",
                                    json={"chat_id": chat_id, "text": prefix + chunk},
                                    timeout=10,
                                )
                                if index < len(chunks):
                                    await asyncio.sleep(0.2)
                except Exception:
                    await asyncio.sleep(self.poll_interval)
                await asyncio.sleep(0.5)

    def stop(self):
        self._running = False
