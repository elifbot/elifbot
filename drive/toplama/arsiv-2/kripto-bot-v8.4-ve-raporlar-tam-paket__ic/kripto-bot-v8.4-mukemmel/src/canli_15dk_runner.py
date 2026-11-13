"""Kripto Bot v8.0 — 15 Dakikalık Gerçek Canlı Borsa Verisi (Binance USDⓈ-M + OKX USDT-SWAP) Motoru.

• %100 Gerçek Borsa Verisi:
  - Binance USDⓈ-M Vadeli: Canlı 24s hacim keşfi, 1m/5m/15m/1h kapanmış mumlar,
    ardışık ID (`a`) takipli canlı `aggTrades`, `bookTicker` (bid/ask spread) ve `premiumIndex` (funding).
  - OKX USDT-SWAP Vadeli: Canlı WebSocket (`wss://ws.okx.com/ws/v5/public` `trades` kanalı)
    milisaniyelik fiyat ve işlem akışı.
• Güvenli Paper İcra:
  - Gerçek emir / API anahtarı YOKTUR; $10,000 sanal kasa, gerçekçi komisyon (%0.02/%0.05),
    canlı bid/ask makası, SQLite WAL çift-taraflı muhasebe (`verify_paper_ledger_integrity`),
    `ClockDiscontinuityGuard` saat koruması ve 4'lü Yapay Zeka Konseyi (Claude + DeepSeek + GPT + Gemini).
• Canlı Web Gösterge Paneli: `0.0.0.0:8080` üzerinde anlık izleme ve 15. dakika sonunda tam rapor kaydı.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("BINANCE_PUBLIC_WWW", "1")

from saat_guard import ClockDiscontinuityGuard
from saat_kontrolu import sample as clock_sample
from src.ai_council import MultiAICouncil
from src.circuit_breaker import CircuitBreaker
from src.config import load_config
from src.equity_reporting import equity_or_none, safe_unrealized
from src.exchanges import ExchangeManager
from src.executor import Executor
from src.main import ohlcv_to_df
from src.risk import RiskManager
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy
from src.unified_v8_engine import UnifiedV8Engine

DURATION_SEC = int(os.environ.get("LIVE_TEST_DURATION_SEC", "600"))
DURATION_MIN = max(1, round(DURATION_SEC / 60))
MAX_DRAIN_SEC = int(os.environ.get("LIVE_MAX_DRAIN_SEC", "900"))
PORT = int(os.environ.get("PANEL_PORT", os.environ.get("LIVE_TEST_PORT", "8080")))
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PREFIX = os.environ.get("LIVE_REPORT_PREFIX", f"canli_{DURATION_MIN}dk_v84")
DB_PATH = REPORTS_DIR / f"{REPORT_PREFIX}_state.db"
SUMMARY_JSON_PATH = REPORTS_DIR / f"{REPORT_PREFIX}_ozet.json"
REPORT_MD_PATH = REPORTS_DIR / f"{REPORT_PREFIX}_rapor.md"


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Kripto Bot v8.4 (10-YZ Adaptif + Doğal Kapanış + %60 Maker Zırhı) — Canlı Borsa Testi</title>
<style>
  :root {
    --bg: #080d1a; --card: #10182b; --border: #1f2d4d;
    --text: #e6eefc; --muted: #8ea2c8; --green: #10b981;
    --red: #ef4444; --amber: #f59e0b; --blue: #3b82f6;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 18px; line-height: 1.45; }
  .header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; background: linear-gradient(135deg, #101b35, #0d1526); border: 1px solid var(--border); border-radius: 14px; padding: 16px 20px; margin-bottom: 16px; }
  .title { font-size: 19px; font-weight: 800; letter-spacing: -0.3px; }
  .sub { font-size: 12.5px; color: var(--muted); margin-top: 3px; }
  .pill { display: inline-flex; align-items: center; gap: 7px; padding: 6px 13px; border-radius: 999px; font-size: 12.5px; font-weight: 700; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.35); }
  .pill.done { background: rgba(59,130,246,0.18); color: #60a5fa; border-color: rgba(59,130,246,0.4); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 8px currentColor; }
  .progress-wrap { width: 100%; height: 8px; background: #17223b; border-radius: 99px; overflow: hidden; margin-top: 10px; }
  .progress-bar { height: 100%; background: linear-gradient(90deg, var(--blue), var(--green)); width: 0%; transition: width 0.6s ease; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .kpi { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 13px 15px; }
  .kpi-label { font-size: 11.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  .kpi-val { font-size: 20px; font-weight: 800; margin-top: 5px; font-variant-numeric: tabular-nums; }
  .kpi-sub { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
  .grid-2 { display: grid; grid-template-columns: 1.45fr 1fr; gap: 14px; margin-bottom: 16px; }
  @media (max-width: 980px) { .grid-2 { grid-template-columns: 1fr; } }
  .panel { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 15px; overflow-x: auto; }
  .panel h3 { font-size: 14px; margin-bottom: 11px; color: #c7d8f8; display: flex; justify-content: space-between; align-items: center; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
  th, td { padding: 8px 9px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.05); }
  th { color: var(--muted); font-weight: 600; font-size: 11.5px; }
  .pos { color: var(--green); font-weight: 700; }
  .neg { color: var(--red); font-weight: 700; }
  .tag { padding: 2px 7px; border-radius: 6px; font-size: 11px; font-weight: 700; }
  .tag-long { background: rgba(16,185,129,0.18); color: #34d399; }
  .tag-short { background: rgba(239,68,68,0.18); color: #f87171; }
  .tag-wait { background: rgba(142,162,200,0.14); color: #9fb2d4; }
  .log-list { display: flex; flex-direction: column; gap: 8px; max-height: 360px; overflow-y: auto; }
  .log-item { background: #0b1222; border: 1px solid #1b2948; border-radius: 9px; padding: 9px 11px; font-size: 12px; }
  .votes-row { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
  .vote-chip { font-size: 11px; padding: 2px 6px; border-radius: 5px; background: #14203a; color: #bfd2f5; }
</style>
</head>
<body>
  <div class="header">
    <div style="flex:1; min-width:280px;">
      <div class="title" id="mainTitle">🚀 Kripto Bot v8.2 (10-YZ Konsey) — Canlı Borsa Verisi Testi (Binance + OKX)</div>
      <div class="sub" id="subHeader">Canlı piyasa akışı bağlanıyor...</div>
      <div class="progress-wrap"><div class="progress-bar" id="progBar"></div></div>
    </div>
    <div style="display:flex; gap:10px; align-items:center;">
      <div class="pill" id="statusPill"><span class="dot"></span><span id="statusTxt">BAŞLATILIYOR</span></div>
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi"><div class="kpi-label" id="kpiTimerLabel">Kalan Süre</div><div class="kpi-val" id="kpiTimer">10:00</div><div class="kpi-sub" id="kpiElapsed">Geçen: 0 sn</div></div>
    <div class="kpi"><div class="kpi-label">Toplam Özsermaye (Paper)</div><div class="kpi-val" id="kpiEquity">$10,000.00</div><div class="kpi-sub" id="kpiCash">Nakit: $10,000.00</div></div>
    <div class="kpi"><div class="kpi-label">Açık K/Z &amp; Net Getiri</div><div class="kpi-val" id="kpiUnreal">$0.00</div><div class="kpi-sub" id="kpiFees">Ücret: $0.0000 | Funding: $0.0000</div></div>
    <div class="kpi"><div class="kpi-label">Canlı Borsa İşlem Akışı</div><div class="kpi-val" id="kpiTicks">0</div><div class="kpi-sub" id="kpiFeeds">OKX WS: 0 | Binance Agg: 0</div></div>
    <div class="kpi"><div class="kpi-label">10'lu Uzman YZ Konseyi</div><div class="kpi-val" id="kpiCouncil">0</div><div class="kpi-sub" id="kpiCouncilSub">Onay: 0 | Veto: 0</div></div>
    <div class="kpi"><div class="kpi-label">SQLite Defter &amp; Saat Zırhı</div><div class="kpi-val pos" id="kpiLedger">DOĞRULANDI</div><div class="kpi-sub" id="kpiClock">Saat: OK | Gap: 0</div></div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h3><span>📡 Canlı Vadeli Parite Tarayıcısı (V4 VWAP60/ATR14 + V7.8 300s Akış)</span><span id="symCount" style="font-size:11.5px;color:var(--muted);"></span></h3>
      <table>
        <thead>
          <tr><th>Parite</th><th>Canlı Fiyat</th><th>Makas</th><th>VWAP60 Z</th><th>ATR14%</th><th>300s Flow</th><th>Konsey</th><th>Durum</th></tr>
        </thead>
        <tbody id="marketRows"><tr><td colspan="8" style="color:var(--muted);">Canlı mum ve işlem verileri ısıtılıyor...</td></tr></tbody>
      </table>
    </div>

    <div class="panel">
      <h3><span>🧠 Dünyanın En İyi 10 Kodlama &amp; Algoritma Uzmanı YZ Konseyi</span></h3>
      <div class="log-list" id="councilLogs"><div style="color:var(--muted);font-size:12px;">İlk sinyal değerlendirmesi bekleniyor...</div></div>
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h3><span>📂 Açık Paper Pozisyonlar (Canlı Borsa Fiyatıyla Değerlenen)</span></h3>
      <table>
        <thead><tr><th>Parite</th><th>Yön</th><th>Giriş</th><th>Canlı</th><th>Miktar</th><th>Stop</th><th>Canlı K/Z</th></tr></thead>
        <tbody id="openPosRows"><tr><td colspan="7" style="color:var(--muted);">Henüz açık pozisyon yok.</td></tr></tbody>
      </table>
    </div>
    <div class="panel">
      <h3><span>🧾 Kapanan İşlemler &amp; Olay Günlüğü</span></h3>
      <div class="log-list" id="eventLogs"></div>
    </div>
  </div>

<script>
function fmtSec(s) {
  s = Math.max(0, Math.floor(s));
  const m = String(Math.floor(s / 60)).padStart(2, '0');
  const r = String(s % 60).padStart(2, '0');
  return m + ':' + r;
}
async function poll() {
  try {
    const r = await fetch('api/live-state', { cache: 'no-store' });
    const d = await r.json();
    document.getElementById('subHeader').textContent =
      `Başlangıç: ${d.started_utc} | Evren: ${d.symbols.length} Saf Kripto USDT Perpetual (${d.excluded_non_crypto_count} hisse/emtia kontratı elendi)`;
    const durMin = Math.max(1, Math.round(d.duration_sec / 60));
    document.getElementById('mainTitle').textContent =
      `🚀 Kripto Bot v8.4 (10-YZ Adaptif + Doğal Kapanış + Maker Zırhı) — ${durMin}dk Giriş + Doğal Kapanış`;
    document.getElementById('kpiTimerLabel').textContent = `Kalan Süre / ${fmtSec(d.duration_sec)}`;
    const pct = Math.min(100, (d.elapsed_sec / d.duration_sec) * 100);
    document.getElementById('progBar').style.width = pct.toFixed(1) + '%';
    const pill = document.getElementById('statusPill');
    const stTxt = document.getElementById('statusTxt');
    stTxt.textContent = d.completed ? `${durMin} DK TEST TAMAMLANDI` : ('CANLI: ' + d.phase.toUpperCase());
    if (d.completed) pill.classList.add('done');

    document.getElementById('kpiTimer').textContent = fmtSec(d.remaining_sec);
    document.getElementById('kpiElapsed').textContent = `Geçen: ${Math.floor(d.elapsed_sec)} / ${d.duration_sec} sn`;
    const eq = d.equity_usdt !== null ? ('$' + d.equity_usdt.toFixed(2)) : 'Hesaplanıyor';
    document.getElementById('kpiEquity').textContent = eq;
    document.getElementById('kpiCash').textContent = `Nakit: $${d.balance_usdt.toFixed(2)} (Başlangıç: $${d.start_balance.toFixed(0)})`;
    const unrEl = document.getElementById('kpiUnreal');
    const netDelta = d.equity_usdt !== null ? (d.equity_usdt - d.start_balance) : 0;
    unrEl.textContent = (netDelta >= 0 ? '+$' : '-$') + Math.abs(netDelta).toFixed(2);
    unrEl.className = 'kpi-val ' + (netDelta >= 0 ? 'pos' : 'neg');
    document.getElementById('kpiFees').textContent = `Ücret: $${d.total_fees_usdt.toFixed(4)} | Funding: $${d.total_funding_usdt.toFixed(4)}`;

    document.getElementById('kpiTicks').textContent = d.total_live_trades.toLocaleString('tr-TR');
    document.getElementById('kpiFeeds').textContent = `OKX WS: ${d.okx_ws_trades} | Binance Agg: ${d.binance_agg_trades}`;
    document.getElementById('kpiCouncil').textContent = d.council_stats.evaluations;
    document.getElementById('kpiCouncilSub').textContent = `Onay: ${d.council_stats.approved} | Veto: ${d.council_stats.vetoed}`;

    const ledEl = document.getElementById('kpiLedger');
    ledEl.textContent = d.ledger_ok ? 'DOĞRULANDI (OK)' : 'HATA / KİLİTLİ';
    ledEl.className = 'kpi-val ' + (d.ledger_ok ? 'pos' : 'neg');
    document.getElementById('kpiClock').textContent = `Saat: ${d.clock_ok ? 'OK' : 'SAPMA'} | Gap Sıfırlama: ${d.agg_gaps}`;

    document.getElementById('symCount').textContent = `${Object.keys(d.market_table).length} aktif parite`;
    const mRows = Object.values(d.market_table).map((m) => {
      const sig = String(m.last_signal || 'İZLENİYOR');
      const cls = sig.includes('LONG') ? 'tag-long' : (sig.includes('SHORT') ? 'tag-short' : 'tag-wait');
      return `<tr>
        <td><strong>${m.symbol}</strong></td>
        <td>$${Number(m.price || 0).toPrecision(6)}</td>
        <td>%${Number(m.spread_pct || 0).toFixed(3)}</td>
        <td class="${(m.vwap_z || 0) >= 0 ? 'pos' : 'neg'}">${(m.vwap_z >= 0 ? '+' : '') + Number(m.vwap_z || 0).toFixed(2)}</td>
        <td>%${Number(m.atr_pct || 0).toFixed(2)}</td>
        <td class="${(m.flow_score || 0) >= 0 ? 'pos' : 'neg'}">${(m.flow_score >= 0 ? '+' : '') + Number(m.flow_score || 0).toFixed(1)}</td>
        <td>${m.council_score !== null ? ((m.council_score >= 0 ? '+' : '') + m.council_score.toFixed(1)) : '-'}</td>
        <td><span class="tag ${cls}">${sig}</span></td>
      </tr>`;
    }).join('');
    if (mRows) document.getElementById('marketRows').innerHTML = mRows;

    const cLogs = (d.recent_council || []).map((c) => {
      const votes = (c.votes || []).map((v) => `<span class="vote-chip">${v.member_id.toUpperCase()}: ${v.verdict} (${v.score >= 0 ? '+' : ''}${v.score})</span>`).join('');
      return `<div class="log-item">
        <div><strong>${c.symbol}</strong> → <span class="${c.approved ? 'pos' : 'neg'}">${c.approved ? 'ONAYLANDI' : 'VETO / BEKLE'}</span> (${c.side}, Skor: ${c.consensus_score})</div>
        <div style="color:var(--muted);margin-top:2px;">${c.reason}</div>
        <div class="votes-row">${votes}</div>
      </div>`;
    }).join('');
    if (cLogs) document.getElementById('councilLogs').innerHTML = cLogs;

    const pRows = (d.open_positions || []).map((p) => `<tr>
      <td><strong>${p.symbol}</strong></td>
      <td><span class="tag ${p.side === 'LONG' ? 'tag-long' : 'tag-short'}">${p.side}</span></td>
      <td>$${p.entry.toPrecision(6)}</td>
      <td>${p.live_price ? ('$' + p.live_price.toPrecision(6)) : '-'}</td>
      <td>${p.qty.toPrecision(4)}</td>
      <td>$${p.stop.toPrecision(6)}</td>
      <td class="${(p.pnl_usdt || 0) >= 0 ? 'pos' : 'neg'}">${p.pnl_usdt !== null ? ((p.pnl_usdt >= 0 ? '+$' : '-$') + Math.abs(p.pnl_usdt).toFixed(3)) : '-'}</td>
    </tr>`).join('');
    document.getElementById('openPosRows').innerHTML = pRows || '<tr><td colspan="7" style="color:var(--muted);">Açık pozisyon yok.</td></tr>';

    document.getElementById('eventLogs').innerHTML = (d.events || []).map((e) => `<div class="log-item">${e}</div>`).join('');
  } catch (err) {
    console.error(err);
  }
}
poll();
setInterval(poll, 1500);
</script>
</body>
</html>
"""


class Live15MinSession:
    def __init__(self):
        if DB_PATH.exists():
            DB_PATH.unlink()
        for suf in ("-wal", "-shm"):
            p = Path(f"{DB_PATH}{suf}")
            if p.exists():
                p.unlink()

        self.started_ts = time.time()
        self.started_mono = time.monotonic()
        self.started_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.duration_sec = DURATION_SEC
        self.entries_open = True
        self.drain_duration_sec = 0.0
        self.phase = "evren_ve_mum_isitma"
        self.completed = False

        self.clock_guard = ClockDiscontinuityGuard(max_drift_sec=5.0)
        self.clock_ok = bool(clock_sample().get("ok", True))

        cfg = load_config()
        cfg["genel"]["mod"] = "paper"
        cfg["paper"]["bakiye"] = 10_000.0
        cfg["paper"]["gercekci_yurutme"] = True
        cfg["paper"]["akilli_maker_yurutme"] = True
        cfg["paper"]["funding_aktif"] = True

        self.broker = ExchangeManager(cfg)
        self.store = StateStore(DB_PATH)
        self.breaker = CircuitBreaker(state_store=self.store)
        self.risk = RiskManager(
            stop_model="marj",
            margin_stop_fraction=0.80,
            leverage=10,
            max_positions=6,
            hard_max_positions=6,
            max_same_side_positions=4,
            unlimited_pyramiding=False,
            max_layers=1,
            pair_rescue_enabled=True,
            pair_rescue_fee_aware=True,
            pair_rescue_min_net_usdt=0.20,
            mfe_lock_min_usdt=1.35,
            mfe_lock_keep_ratio=0.56,
            state_store=self.store,
        )
        self.strategy = Strategy(
            w_ind=0.45,
            w_flow=0.40,
            w_news=0.0,
            w_ml=0.0,
            long_th=20.0,
            short_th=-20.0,
            flow_trigger=True,
            flow_th=45.0,
            flow_ind_min=8.0,
            flow_min_total=14.0,
            runner_exit=True,
        )
        self.sizer = PositionSizer(
            mode="sabit_usdt",
            fixed_margin_usdt=100.0,
            leverage=10,
            kelly_on=False,
            stats_path=REPORTS_DIR / "canli_kelly.json",
        )
        self.events: deque[str] = deque(maxlen=60)
        self.executor = Executor(
            self.broker,
            self.risk,
            self.strategy,
            sizer=self.sizer,
            alert=self._on_alert,
            cooldown_sec=20.0,
            order_type="maker",
            maker_timeout=2.0,
            protection_on=True,
            state_store=self.store,
            circuit_breaker=self.breaker,
            supertrend_trailing=True,
            net_breakeven_enabled=True,
            net_profit_buffer_usdt=0.35,
            exit_fee_pct=0.05,
            runner_exit_cfg=cfg.get("cikis", {}),
        )
        rec = self.executor.reconcile_and_unlock_paper_state(owner_id="live-15m-runner")
        self.ledger_ok = bool(rec.get("ok", False))

        self.council = MultiAICouncil(min_consensus_score=16.0, max_veto_count=1, enabled=True)
        self.engine = UnifiedV8Engine(self.executor, mode="hybrid_fusion", council=self.council)

        self.symbols: list[str] = []
        self.excluded_non_crypto_count = 0
        self.okx_ws_trades = 0
        self.binance_agg_trades = 0
        self.agg_gaps = 0
        self.last_agg_id: dict[str, int] = {}
        self.ohlcv_5m_cache: dict[str, Any] = {}
        self.ohlcv_15m_cache: dict[str, Any] = {}
        self.ohlcv_1h_cache: dict[str, Any] = {}
        self.funding_rates: dict[str, float] = {}
        self.spreads_pct: dict[str, float] = {}
        self.market_table: dict[str, dict[str, Any]] = {}
        self.recent_council: deque[dict[str, Any]] = deque(maxlen=25)
        self._stop_event = asyncio.Event()

    async def _on_alert(self, msg: str):
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.events.appendleft(f"[{stamp}] {msg}")

    def log_event(self, msg: str):
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        self.events.appendleft(line)
        print(line, flush=True)

    async def discover_and_warmup(self, session: aiohttp.ClientSession):
        self.log_event("Binance USDⓈ-M + OKX USDT-SWAP canlı vadeli piyasa evreni taranıyor...")
        async with session.get("https://www.binance.com/fapi/v1/ticker/24hr") as resp:
            resp.raise_for_status()
            tickers = await resp.json()

        raw_usdt = [
            t for t in tickers
            if isinstance(t, dict)
            and str(t.get("symbol", "")).endswith("USDT")
            and float(t.get("quoteVolume") or 0.0) >= 25_000_000.0
        ]
        all_names = [str(t["symbol"]) for t in raw_usdt]
        pure_names = set(UnifiedV8Engine.filter_pure_crypto_symbols(all_names))
        self.excluded_non_crypto_count = len(all_names) - len(pure_names)

        try:
            async with session.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP") as o_resp:
                if o_resp.status == 200:
                    o_data = (await o_resp.json()).get("data", [])
                    o_raw = [str(x.get("instId", "")) for x in o_data if str(x.get("instId", "")).endswith("-USDT-SWAP")]
                    o_pure = UnifiedV8Engine.filter_pure_crypto_symbols(o_raw)
                    self.excluded_non_crypto_count += max(0, len(o_raw) - len(o_pure))
        except Exception:
            pass

        ranked = sorted(
            (t for t in raw_usdt if str(t["symbol"]) in pure_names),
            key=lambda x: float(x.get("quoteVolume") or 0.0),
            reverse=True,
        )
        core = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
        picked_raw: list[str] = []
        for c in core + [str(t["symbol"]) for t in ranked]:
            if c in pure_names and c not in picked_raw:
                picked_raw.append(c)
            if len(picked_raw) >= 12:
                break

        self.symbols = [f"{s[:-4]}/USDT" for s in picked_raw]
        self.broker.symbols = list(self.symbols)
        self.okx_ct_sizes = await self.broker.get_contract_sizes()
        self.log_event(
            f"Saf kripto evreni seçildi ({len(self.symbols)} likit parite, {self.excluded_non_crypto_count} kripto-dışı kontrat elendi): "
            + ", ".join(self.symbols)
        )

        sem = asyncio.Semaphore(4)

        async def warm_symbol(sym: str):
            raw = sym.replace("/", "")
            async with sem:
                now_ms = int(time.time() * 1000)
                async with session.get(
                    "https://www.binance.com/fapi/v1/klines",
                    params={"symbol": raw, "interval": "1m", "limit": "65"},
                ) as r1:
                    rows_1m = await r1.json()
                for row in rows_1m:
                    open_ts = int(row[0])
                    close_ts = int(row[6])
                    if close_ts < now_ms:
                        self.engine.ingest_closed_1m_candle(
                            "binance",
                            sym,
                            open_ts // 60_000,
                            float(row[1]),
                            float(row[2]),
                            float(row[3]),
                            float(row[4]),
                            float(row[5]),
                            float(row[7]),
                        )

                for tf, lim, target in (
                    ("5m", 220, self.ohlcv_5m_cache),
                    ("15m", 120, self.ohlcv_15m_cache),
                    ("1h", 120, self.ohlcv_1h_cache),
                ):
                    rows = await self.broker._ex["binance"].fetch_ohlcv(sym, timeframe=tf, limit=lim)
                    target[sym] = ohlcv_to_df(rows, timeframe=tf)

                async with session.get(
                    "https://www.binance.com/fapi/v1/aggTrades",
                    params={"symbol": raw, "limit": "80"},
                ) as ra:
                    trades = await ra.json()
                for tr in trades:
                    aid = int(tr["a"])
                    px = float(tr["p"])
                    qty = float(tr["q"])
                    ts_t = int(tr["T"])
                    maker = bool(tr["m"])
                    self.last_agg_id[sym] = aid
                    await self.engine.on_trade("binance", sym, px, qty, is_buyer_maker=maker, ts_ms=ts_t)
                    self.binance_agg_trades += 1

                self.market_table[sym] = {
                    "symbol": sym,
                    "price": self.executor.last_prices.get(sym, 0.0),
                    "spread_pct": 0.01,
                    "vwap_z": 0.0,
                    "atr_pct": 0.0,
                    "flow_score": 0.0,
                    "council_score": None,
                    "last_signal": "İZLENİYOR",
                }

        await asyncio.gather(*(warm_symbol(s) for s in self.symbols))
        self.phase = "canli_akis_ve_analiz"
        self.log_event("60dk VWAP60/ATR14 + 5m/15m/1h MTF + 300s Order-Flow canlı verilerle ısıtıldı!")

    async def okx_ws_loop(self, session: aiohttp.ClientSession):
        """OKX Canlı WebSocket `trades` akışı — milisaniyelik gerçek piyasa işlemleri."""
        inst_map = {f"{s.split('/')[0]}-USDT-SWAP": s for s in self.symbols}
        sub_msg = json.dumps(
            {"op": "subscribe", "args": [{"channel": "trades", "instId": k} for k in inst_map]}
        )
        ws_urls = ("wss://ws.okx.com/ws/v5/public", "wss://ws.okx.com:8443/ws/v5/public")
        idx = 0
        while not self._stop_event.is_set():
            url = ws_urls[idx % len(ws_urls)]
            try:
                async with session.ws_connect(url, heartbeat=15.0) as ws:
                    await ws.send_str(sub_msg)
                    self.log_event(f"OKX Canlı WebSocket (trades) bağlantısı aktif ({url}).")
                    async for msg in ws:
                        if self._stop_event.is_set():
                            break
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        payload = json.loads(msg.data)
                        for item in payload.get("data", []):
                            inst_id = item.get("instId")
                            sym = inst_map.get(inst_id)
                            if not sym:
                                continue
                            px = float(item["px"])
                            ct_val = float(getattr(self, "okx_ct_sizes", {}).get(("okx", sym), 0.0))
                            if ct_val <= 0:
                                continue
                            sz = float(item["sz"]) * ct_val
                            side = str(item.get("side", "buy")).lower()
                            ts_ms = int(item["ts"])
                            await self.engine.on_trade(
                                "okx", sym, px, sz, is_buyer_maker=(side == "sell"), ts_ms=ts_ms
                            )
                            self.okx_ws_trades += 1
                            if sym in self.market_table:
                                self.market_table[sym]["price"] = px
            except asyncio.CancelledError:
                break
            except Exception as exc:
                idx += 1
                self.log_event(f"OKX WS yeniden bağlanıyor ({type(exc).__name__})...")
                await asyncio.sleep(2.0)

    async def binance_fast_ticker_loop(self, session: aiohttp.ClientSession):
        """0.6sn kesintisiz tek-istek `bookTicker` beslemesi: ZEC benzeri fiyat boşluğu (gap-through) ve
        ağ tıkanmasını sıfırlar; açık pozisyon stoplarını milisaniyeye yakın izler."""
        while not self._stop_event.is_set():
            try:
                async with session.get(
                    "https://www.binance.com/fapi/v1/ticker/bookTicker",
                    timeout=aiohttp.ClientTimeout(total=4.0),
                ) as rb:
                    if rb.status == 200:
                        books = await rb.json()
                        book_map = {b["symbol"]: b for b in books if isinstance(b, dict) and "symbol" in b}
                        for sym in self.symbols:
                            b = book_map.get(sym.replace("/", ""))
                            if not b:
                                continue
                            bid = float(b.get("bidPrice") or 0.0)
                            ask = float(b.get("askPrice") or 0.0)
                            if bid > 0 and ask >= bid:
                                mid = (bid + ask) / 2.0
                                sp = (ask - bid) / mid * 100.0
                                self.spreads_pct[sym] = sp
                                await self.executor.on_price_tick(sym, mid)
                                if sym in self.market_table:
                                    self.market_table[sym]["price"] = mid
                                    self.market_table[sym]["spread_pct"] = sp
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            await asyncio.sleep(0.6)

    async def binance_live_poller(self, session: aiohttp.ClientSession):
        """Binance USDⓈ-M ardışık aggTrades ve kapanan 1m/5m mum güncelleyici (bookTicker'dan bağımsız)."""
        last_candle_refresh = 0.0
        while not self._stop_event.is_set():
            try:
                for sym in self.symbols:
                    if self._stop_event.is_set():
                        break
                    raw = sym.replace("/", "")
                    try:
                        async with session.get(
                            "https://www.binance.com/fapi/v1/aggTrades",
                            params={"symbol": raw, "limit": "60"},
                            timeout=aiohttp.ClientTimeout(total=5.0),
                        ) as ra:
                            if ra.status != 200:
                                continue
                            trades = await ra.json()
                    except Exception:
                        continue
                    prev_id = self.last_agg_id.get(sym)
                    new_trades = [t for t in trades if prev_id is None or int(t["a"]) > prev_id]
                    if prev_id is not None and new_trades and int(new_trades[0]["a"]) > prev_id + 1:
                        self.agg_gaps += 1
                    for tr in new_trades:
                        aid = int(tr["a"])
                        px = float(tr["p"])
                        qty = float(tr["q"])
                        ts_t = int(tr["T"])
                        maker = bool(tr["m"])
                        self.last_agg_id[sym] = aid
                        await self.engine.on_trade("binance", sym, px, qty, is_buyer_maker=maker, ts_ms=ts_t)
                        self.binance_agg_trades += 1

                if time.monotonic() - last_candle_refresh >= 25.0:
                    last_candle_refresh = time.monotonic()
                    try:
                        async with session.get(
                            "https://www.binance.com/fapi/v1/premiumIndex",
                            timeout=aiohttp.ClientTimeout(total=6.0),
                        ) as rf:
                            if rf.status == 200:
                                p_rows = await rf.json()
                                p_map = {x["symbol"]: x for x in p_rows if isinstance(x, dict) and "symbol" in x}
                                for sym in self.symbols:
                                    item = p_map.get(sym.replace("/", ""))
                                    if item:
                                        fr = float(item.get("lastFundingRate") or 0.0)
                                        mp = float(item.get("markPrice") or 0.0)
                                        self.funding_rates[sym] = fr
                                        if sym in self.executor.positions and mp > 0:
                                            try:
                                                self.executor.apply_funding(sym, fr, mp, enabled=True)
                                            except Exception:
                                                pass
                    except Exception:
                        pass

                    now_ms = int(time.time() * 1000)
                    for sym in self.symbols:
                        if self._stop_event.is_set():
                            break
                        raw = sym.replace("/", "")
                        try:
                            async with session.get(
                                "https://www.binance.com/fapi/v1/klines",
                                params={"symbol": raw, "interval": "1m", "limit": "5"},
                                timeout=aiohttp.ClientTimeout(total=5.0),
                            ) as rk1:
                                if rk1.status == 200:
                                    for row in await rk1.json():
                                        if int(row[6]) < now_ms:
                                            self.engine.ingest_closed_1m_candle(
                                                "binance", sym, int(row[0]) // 60_000,
                                                float(row[1]), float(row[2]), float(row[3]),
                                                float(row[4]), float(row[5]), float(row[7]),
                                            )
                            rows5 = await self.broker._ex["binance"].fetch_ohlcv(sym, timeframe="5m", limit=220)
                            self.ohlcv_5m_cache[sym] = ohlcv_to_df(rows5, timeframe="5m")
                        except Exception:
                            continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.log_event(f"Binance canlı veri döngüsü uyarısı: {type(exc).__name__}")
            await asyncio.sleep(2.5)

    async def strategy_and_audit_loop(self):
        """Her 8 saniyede tüm pariteleri UnifiedV8Engine + 10'lu Uzman YZ Konseyi ile değerlendirir."""
        while not self._stop_event.is_set():
            try:
                self.store.acquire_writer_lease("live-15m-runner", ttl_sec=120.0)
                self.clock_ok = self.clock_guard.check() and bool(clock_sample().get("ok", True))
                self.detector_breadth_update()
                for sym in self.symbols:
                    df5 = self.ohlcv_5m_cache.get(sym)
                    if df5 is None or len(df5) < 60:
                        continue
                    res = await self.engine.evaluate_and_route(
                        "binance",
                        sym,
                        df5,
                        ohlcv_15m=self.ohlcv_15m_cache.get(sym),
                        ohlcv_1h=self.ohlcv_1h_cache.get(sym),
                        spread_pct=self.spreads_pct.get(sym, 0.02),
                        funding_rate=self.funding_rates.get(sym, 0.0),
                        allow_new_entries=self.entries_open,
                    )
                    if sym in self.executor.positions and sym in self.executor.last_prices:
                        await self.executor.maybe_orderflow_exit(
                            sym,
                            self.executor.last_prices[sym],
                            lambda s=sym: self.engine.flow_for(s).snapshot(include_vpvr=False),
                        )

                    v4_m = res.get("v4_60m") or {}
                    flow_s = res.get("flow") or {}
                    council = res.get("council")
                    vwap_z = 0.0
                    if v4_m.get("atr14", 0) > 0 and sym in self.executor.last_prices:
                        vwap_z = (self.executor.last_prices[sym] - v4_m["vwap60"]) / v4_m["atr14"]

                    row = self.market_table.setdefault(sym, {"symbol": sym})
                    row.update(
                        {
                            "price": self.executor.last_prices.get(sym, row.get("price", 0.0)),
                            "spread_pct": self.spreads_pct.get(sym, 0.02),
                            "vwap_z": vwap_z,
                            "atr_pct": float(v4_m.get("atr_pct") or 0.0),
                            "flow_score": float(flow_s.get("score") or 0.0),
                            "council_score": council.get("consensus_score") if council else row.get("council_score"),
                            "last_signal": "AÇIK: " + self.executor.positions[sym].side
                            if sym in self.executor.positions
                            else str(res.get("signal") or "BEKLE"),
                        }
                    )
                    if council and council.get("votes"):
                        self.recent_council.appendleft(
                            {
                                "symbol": sym,
                                "side": council["side"],
                                "approved": council["approved"],
                                "consensus_score": council["consensus_score"],
                                "reason": council["reason"],
                                "votes": council["votes"],
                            }
                        )

                chk = self.store.verify_paper_ledger_integrity()
                self.ledger_ok = bool(chk.get("ok", False))
                self.write_checkpoint()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.log_event(f"Analiz döngüsü uyarısı: {exc}")
            await asyncio.sleep(8.0)

    def detector_breadth_update(self):
        try:
            self.engine.detector.genislik_guncelle()
        except Exception:
            pass

    def build_state_snapshot(self) -> dict[str, Any]:
        total_elapsed = time.monotonic() - self.started_mono
        elapsed = min(float(self.duration_sec), total_elapsed)
        remaining = max(0.0, float(self.duration_sec) - elapsed)
        unreal, known = safe_unrealized(self.executor)
        eq = equity_or_none(self.broker.paper.balance, unreal if known else None)
        if not self.executor.positions:
            eq = self.broker.paper.balance
            unreal = 0.0

        open_rows = []
        for sym, pos in self.executor.positions.items():
            px = self.executor.last_prices.get(sym)
            pnl_u = None
            if px is not None:
                d = 1.0 if pos.side == "LONG" else -1.0
                pnl_u = d * (px - pos.entry) * pos.qty
            open_rows.append(
                {
                    "symbol": sym,
                    "side": pos.side,
                    "entry": pos.entry,
                    "live_price": px,
                    "qty": pos.qty,
                    "stop": pos.stop,
                    "pnl_usdt": pnl_u,
                }
            )

        return {
            "started_utc": self.started_utc,
            "phase": self.phase,
            "completed": self.completed,
            "entries_open": self.entries_open,
            "duration_sec": self.duration_sec,
            "elapsed_sec": round(elapsed, 2),
            "total_elapsed_sec": round(total_elapsed, 2),
            "drain_duration_sec": round(self.drain_duration_sec, 2),
            "remaining_sec": round(remaining, 2),
            "symbols": self.symbols,
            "excluded_non_crypto_count": self.excluded_non_crypto_count,
            "start_balance": self.broker.paper.start_balance,
            "balance_usdt": round(self.broker.paper.balance, 4),
            "unrealized_usdt": round(unreal, 4) if unreal is not None else None,
            "equity_usdt": round(eq, 4) if eq is not None else None,
            "total_fees_usdt": round(self.broker.paper.total_fees_usdt, 6),
            "total_funding_usdt": round(self.broker.paper.total_funding_usdt, 6),
            "okx_ws_trades": self.okx_ws_trades,
            "binance_agg_trades": self.binance_agg_trades,
            "total_live_trades": self.okx_ws_trades + self.binance_agg_trades,
            "agg_gaps": self.agg_gaps,
            "ledger_ok": self.ledger_ok,
            "clock_ok": self.clock_ok,
            "council_stats": {
                "evaluations": self.council.evaluations,
                "approved": self.council.approved,
                "vetoed": self.council.vetoed,
            },
            "engine_metrics": dict(self.engine.metrics),
            "commission_optimizer": self.engine.commission_optimizer.snapshot(),
            "win_loss_stats": dict(self.engine.win_loss_analyzer.stats),
            "ai_assistants": self.council.get_assistants_dashboard(),
            "market_table": self.market_table,
            "open_positions": open_rows,
            "closed_trades": self.store.get_trades(limit=50),
            "recent_council": list(self.recent_council)[:12],
            "events": list(self.events)[:25],
        }

    def write_checkpoint(self):
        snap = self.build_state_snapshot()
        SUMMARY_JSON_PATH.write_text(json.dumps(snap, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        lines = [
            f"# 🚀 Kripto Bot v8.4 (10-YZ Adaptif + Doğal Kapanış + %60 Maker Zırhı) — {DURATION_MIN}dk Canlı Borsa Raporu",
            "",
            f"- **Durum:** {'✅ ' + str(DURATION_MIN) + 'dk Giriş + Doğal Kapanış Oturumu Tamamlandı' if self.completed else ('⏸️ Yeni Giriş Kapalı — Açık Pozisyonlar Doğal Kapanıyor' if not self.entries_open else '🟢 Canlı Çalışıyor')}",
            f"- **Başlangıç (UTC):** `{snap['started_utc']}`",
            f"- **Giriş Penceresi:** `{snap['elapsed_sec']} / {snap['duration_sec']} sn` | **10dk Sonrası Doğal Kapanış Bekleme Süresi:** `{snap['drain_duration_sec']} sn` | **Toplam Süre:** `{snap['total_elapsed_sec']} sn`",
            f"- **İzlenen Saf Kripto Vadeli Pariteler ({len(self.symbols)}):** `{', '.join(self.symbols)}`",
            f"- **Elenen Hisse / Emtia / Stabilcoin Kontratları:** `{self.excluded_non_crypto_count}`",
            f"- **İşlenen Canlı Borsa İşlemi (Tick):** `{snap['total_live_trades']}` (OKX WS: `{self.okx_ws_trades}`, Binance aggTrade: `{self.binance_agg_trades}`)",
            f"- **Başlangıç Kasası:** `${snap['start_balance']:,.2f}` | **Güncel Nakit:** `${snap['balance_usdt']:,.4f}` | **Özsermaye:** `${(snap['equity_usdt'] or snap['balance_usdt']):,.4f}`",
            f"- **Toplam Komisyon:** `${snap['total_fees_usdt']:,.6f}` | **Toplam Funding:** `${snap['total_funding_usdt']:+,.6f}`",
            f"- **SQLite WAL Çift-Taraflı Defter Mutabakatı:** `{'DOĞRULANDI (OK)' if self.ledger_ok else 'HATA'}`",
            f"- **Saat Süreksizlik Koruması (`ClockDiscontinuityGuard`):** `{'SAĞLIKLI (OK)' if self.clock_ok else 'SAPMA TESPİT EDİLDİ'}`",
            f"- **Dünyanın En İyi 10 Kodlama & Algoritma YZ Konseyi:** `{self.council.evaluations}` değerlendirme (`{self.council.approved}` onay, `{self.council.vetoed}` veto)",
            "",
            "## 📊 Canlı Parite Özeti",
            "| Parite | Son Canlı Fiyat | Makas (%) | V4 VWAP60 Z | Wilder ATR14 (%) | 300s Order-Flow | Durum |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for m in self.market_table.values():
            lines.append(
                f"| `{m['symbol']}` | `${float(m.get('price') or 0):,.5f}` | `%{float(m.get('spread_pct') or 0):.3f}` | "
                f"`{float(m.get('vwap_z') or 0):+.2f}` | `%{float(m.get('atr_pct') or 0):.2f}` | "
                f"`{float(m.get('flow_score') or 0):+.1f}` | **{m.get('last_signal')}** |"
            )
        REPORT_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    async def timer_and_finalize(self):
        remaining = self.duration_sec - (time.monotonic() - self.started_mono)
        if remaining > 0:
            await asyncio.sleep(remaining)

        # 10. dakika doldu: Yeni işlem açılışını KİLİTLE, açık pozisyonların doğal kapanmasını bekle!
        self.entries_open = False
        self.engine.sync_closed_trade_feedback()
        if self.executor.positions:
            open_syms = ", ".join(self.executor.positions.keys())
            self.phase = f"dogal_kapanis_bekleniyor({len(self.executor.positions)}_acik)"
            self.log_event(
                f"⏸️ {DURATION_MIN}. dakika doldu: Yeni işlem açılışı DURDURULDU. "
                f"Açık kalan {len(self.executor.positions)} pozisyon ({open_syms}) bot kurallarıyla doğal kapanana kadar izleniyor..."
            )
            drain_started = time.monotonic()
            while self.executor.positions and (time.monotonic() - drain_started) < MAX_DRAIN_SEC:
                self.drain_duration_sec = time.monotonic() - drain_started
                self.phase = f"dogal_kapanis_bekleniyor({len(self.executor.positions)}_acik)"
                self.engine.sync_closed_trade_feedback()
                await asyncio.sleep(1.0)
            self.drain_duration_sec = time.monotonic() - drain_started

        # Yalnızca güvenlik üst tavanı (MAX_DRAIN_SEC) aşılırsa kalan pozisyon kapatılır
        if self.executor.positions:
            self.log_event(
                f"⚠️ Doğal kapanış güvenlik tavanı ({MAX_DRAIN_SEC}sn) doldu; kalan {len(self.executor.positions)} pozisyon kapatılıyor..."
            )
            await self.executor.close_all_positions("DOĞAL KAPANIŞ TAVAN SÜRESİ", urgent=False)

        self.engine.sync_closed_trade_feedback()
        self._stop_event.set()
        chk = self.store.verify_paper_ledger_integrity()
        self.ledger_ok = bool(chk.get("ok", False))
        self.executor.release_writer_ownership()
        self.completed = True
        self.phase = "tamamlandi"
        self.write_checkpoint()
        self.log_event(
            f"✅ {DURATION_MIN}dk + Doğal Kapanış ({self.drain_duration_sec:.1f}sn) canlı borsa testi tamamlandı! Rapor kaydedildi: {REPORT_MD_PATH}"
        )


async def main():
    session_runner = Live15MinSession()

    app = web.Application()

    async def handle_index(_req: web.Request) -> web.Response:
        return web.Response(
            text=DASHBOARD_HTML,
            content_type="text/html",
            charset="utf-8",
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
        )

    async def handle_state(_req: web.Request) -> web.Response:
        return web.Response(
            text=json.dumps(session_runner.build_state_snapshot(), ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
        )

    app.router.add_get("/", handle_index)
    app.router.add_get("/api/live-state", handle_state)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    session_runner.log_event(f"Canlı 15dk Gösterge Paneli yayında: http://0.0.0.0:{PORT}")

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=28.0),
        headers={"User-Agent": "KriptoBotV84-LivePaper/1.0"},
    ) as http_sess:
        await session_runner.discover_and_warmup(http_sess)
        tasks = [
            asyncio.create_task(session_runner.okx_ws_loop(http_sess)),
            asyncio.create_task(session_runner.binance_fast_ticker_loop(http_sess)),
            asyncio.create_task(session_runner.binance_live_poller(http_sess)),
            asyncio.create_task(session_runner.strategy_and_audit_loop()),
            asyncio.create_task(session_runner.timer_and_finalize()),
        ]
        await tasks[-1]
        for t in tasks[:-1]:
            t.cancel()
        await asyncio.gather(*tasks[:-1], return_exceptions=True)
        await session_runner.broker.close()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
