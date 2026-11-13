"""Kripto Bot v9.4 — Tam Saf Kripto Vadeli Evren (~545+ Coin), 10-Ajan Çapraz Teftiş ve Canlı Çift Borsa Motoru.

Mimari Özellikler (v9.4):
  1. Tam Saf Kripto Vadeli Evren (`BINANCE USDⓈ-M` + `OKX USDT-SWAP`, ~545+ Saf Coin):
     - OKX `/api/v5/public/instruments?instType=SWAP` üzerinden yalnızca `instCategory == "1"` ve
       `ruleType == "normal"` kontratlar alınır; ABD hisse senetleri (`instCategory == "3"`) ve
       emtia/metal kontratları (`instCategory == "4"`) %100 dışlanır.
     - Binance `www.binance.com/fapi/v1/exchangeInfo` üzerinden yalnızca aktif `PERPETUAL` `USDT`
       saf kripto kontratları alınır; 12-coin tavanı veya hacim alt sınırı uygulanmaz.
     - Tüm ~545+ saf coin BBO fiyatları her 4 sn'de bir canlı taranır; en hareketli pariteler dinamik
       olarak derin 5m/15m/1h + canlı WS (`aggTrade` / `trades` / `bbo-tbt`) havuzuna terfi ettirilir.
  2. Gerçekçi Pasif Maker Kuyruk Simülatörü (`RealisticMakerQueueSimulator`):
     - Paper modda anlık %100 dolum varsayımı kaldırılmıştır; pasif post-only emirler yalnızca canlı
       emir defteri veya işlem akışı fiyat seviyesini katedince/tüketince dolar, aksi halde zaman
       aşımıyla (`expired_unfilled`) iptal edilir.
  3. 10-Ajan Karşılıklı Teftiş Konseyi + Akım Takipli Dinamik Çıkış:
     - `$1,000` Çapraz (Cross) Kasa, işlem başı `$50 × 10x = $500` büyüklük, `-$40` (`%80` marj = `%8.0`
       fiyat mesafesi) sert stop, serbest teminat yettiği sürece sınırsız açık işlem kapasitesi.
  4. Şeffaf Canlı Web Paneli (`0.0.0.0:8080`, `/api/state`, `/health`):
     - Brüt vs Net Edge (bps), `Komisyon / Hacim (bps)`, Bootstrap %95 Güven Aralığı, Maker kuyruk
       dolum oranı, 10-Ajan 3-turlu teftiş diyalogları, LONG/SHORT karşı-olgu tablosu ve mutabakat sağlığı.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp
from aiohttp import web
import pandas as pd

from scanner.ws_scanner import SpikeDetector
from src.circuit_breaker import CircuitBreaker
from src.commission_optimizer import CommissionOptimizer
from src.config import BASE_DIR, CANONICAL_CONFIG_PATH, load_config
from src.exchanges import ExchangeManager
from src.evaluation_telemetry import evaluation_telemetry_snapshot
from src.feed_health import binance_futures_ws_url, venue_feed_status
from src.executor import Executor
from src.llm_referee import LiveLLMReferee
from src.quant_rule_council import QuantRuleCouncil
from src.regime_state_machine import RegimeStateMachine
from src.risk import RiskManager, position_limits_for_mode
from src.v94_live_risk import V94RiskManager
from src.adaptive_policy import AdaptivePolicy
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy
from src.unified_engine import UnifiedTradingEngine
from src.win_loss_analyzer import WinLossAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("kripto_bot_v9_2")

EXCLUDED_BASES = {
    "USDC", "USDT", "FDUSD", "USDE", "TUSD", "DAI", "BUSD", "PYUSD", "USD1",
    "XAU", "XAG", "PAXG", "XAUT", "EUR", "GBP", "TRY", "WBTC",
    "SKHY", "SKHYNIX", "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL",
    "MSTR", "COIN", "SPY", "QQQ", "SNDK", "SOXL", "SPCX", "CL", "NG", "SPX", "NDX",
    "INTC", "AMD", "PLTR", "HOOD", "NFLX", "BABA", "GOLD", "SILVER",
}

CORE_SEED_BASES = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "SUI", "NEAR", "UNI", "ADA",
    "LINK", "AVAX", "LTC", "ARB", "OP", "APT", "PEPE", "WIF", "INJ", "SEI",
    "TIA", "FET", "RENDER", "DOT", "ATOM", "FIL", "AAVE", "CRV", "ENA", "PENDLE",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sym_to_okx_inst(sym: str) -> str:
    return f"{sym.split('/')[0]}-USDT-SWAP"


def _sym_to_binance_raw(sym: str) -> str:
    return f"{sym.split('/')[0]}USDT"


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Kripto Bot v9.4 — Tam Vadeli Evren & 10-Ajan Çapraz Teftiş Paneli</title>
<style>
  :root {
    --bg:#070b14; --card:#0f172a; --border:#1e293b;
    --text:#e2e8f0; --muted:#94a3b8; --green:#10b981; --red:#ef4444;
    --amber:#f59e0b; --blue:#38bdf8;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif; background:var(--bg); color:var(--text); }
  header { padding:13px 20px; background:#0b1120; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; }
  .title { font-size:16px; font-weight:700; display:flex; align-items:center; gap:9px; }
  .dot { width:10px; height:10px; border-radius:50%; background:var(--green); box-shadow:0 0 10px var(--green); display:inline-block; }
  .venue-pills { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .vpill { padding:4px 10px; border-radius:999px; font-size:11.5px; font-weight:700; border:1px solid var(--border); background:var(--card); }
  .vpill.bn { border-color:rgba(245,158,11,.45); color:#fbbf24; }
  .vpill.okx { border-color:rgba(56,189,248,.45); color:#38bdf8; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(185px,1fr)); gap:10px; padding:12px 20px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:11px 13px; }
  .label { font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
  .val { font-size:18px; font-weight:700; margin-top:4px; }
  .sub { font-size:11px; color:var(--muted); margin-top:3px; }
  .pos { color:var(--green); } .neg { color:var(--red); } .warn { color:var(--amber); }
  .section { padding:5px 20px 13px; }
  .section h3 { margin:4px 0 7px; font-size:12.5px; color:#cbd5e1; text-transform:uppercase; letter-spacing:.05em; display:flex; justify-content:space-between; align-items:center; }
  .tbl-wrap { overflow-x:auto; background:var(--card); border:1px solid var(--border); border-radius:10px; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th, td { padding:7px 9px; text-align:left; border-bottom:1px solid var(--border); white-space:nowrap; }
  th { color:var(--muted); font-weight:600; background:#0b1324; font-size:11px; }
  .badge { padding:2px 6px; border-radius:5px; font-weight:700; font-size:10px; display:inline-block; }
  .LONG { background:rgba(16,185,129,.16); color:#34d399; }
  .SHORT { background:rgba(239,68,68,.16); color:#f87171; }
  .BEKLE { background:rgba(148,163,184,.14); color:#94a3b8; }
  .BINANCE { background:rgba(245,158,11,.18); color:#fbbf24; border:1px solid rgba(245,158,11,.35); }
  .OKX { background:rgba(56,189,248,.18); color:#38bdf8; border:1px solid rgba(56,189,248,.35); }
</style>
</head>
<body>
<header>
  <div class="title"><span class="dot"></span> <span id="hdrTitle">Kripto Bot v9.4 — Tam Saf Kripto Vadeli Motoru</span></div>
  <div class="venue-pills">
    <div class="vpill bn" id="bnStatus">BINANCE: Bağlanıyor...</div>
    <div class="vpill okx" id="okxStatus">OKX: Bağlanıyor...</div>
    <div class="vpill" id="healthPill" style="color:#34d399;">SAĞLIK: OK</div>
    <div class="vpill" id="clock" style="color:#cbd5e1;">Hazırlanıyor...</div>
  </div>
</header>

<div class="grid">
  <div class="card"><div class="label">Çapraz Kasa Özsermaye</div><div class="val" id="eq">$1,000.00</div><div class="sub" id="balSub">Başlangıç: $1,000 | $50×10x (Stop -$40)</div></div>
  <div class="card"><div class="label">Brüt vs Net K/Z Ayrımı</div><div class="val" id="netPnl">$0.0000</div><div class="sub" id="grossSub">Brüt: $0.00 | Komisyon: -$0.00</div></div>
  <div class="card"><div class="label">Komisyon / Hacim Oranı</div><div class="val" id="feeBps">0.00 bps</div><div class="sub" id="edgeBps">Brüt Edge: 0.0 bps | Net: 0.0 bps</div></div>
  <div class="card"><div class="label">Pasif Maker Kuyruk</div><div class="val" id="makerFill">%0.0 Dolum</div><div class="sub" id="makerSub">Dolan: 0 | İptal: 0 | TersSeçim: 0 bps</div></div>
  <div class="card"><div class="label">Saf Kripto Vadeli Evren</div><div class="val" id="univCnt">0 Coin</div><div class="sub" id="univSub">BN: 0 | OKX: 0 (ABD Hisse: 0)</div></div>
  <div class="card"><div class="label">Açık Pozisyon (Sınırsız Cross)</div><div class="val" id="openCnt">0 Açık</div><div class="sub" id="uPnl">Açık K/Z: $0.0000</div></div>
  <div class="card"><div class="label">Eski denetim (v9.4 kapalı)</div><div class="val" id="tenAgent">0 Eski Denetim</div><div class="sub" id="tenSub">Onay: 0 | Veto: 0 (3-Tur)</div></div>
  <div class="card"><div class="label">Toplam değerlendirme çağrısı</div><div class="val" id="evalTotal">0</div><div class="sub">Benzersiz sinyal değildir</div></div>
  <div class="card"><div class="label">Tekrar deneme koruması</div><div class="val" id="evalRetry">0</div><div class="sub" id="evalOther">Tekrar dışı çağrı: 0</div></div>
  <div class="card"><div class="label">Gölge 135sn vs Akım Tutuş</div><div class="val" id="cfDelta">$0.0000</div><div class="sub" id="cfSub">Engellenen Sinyal: 0</div></div>
</div>

<div class="section">
  <h3><span>Canlı Değerlendirme Tablosu (Aktif Derin Havuz — Tam Vadeli Evren Taramalı)</span><span id="pairCount" style="color:var(--muted);font-size:11px;"></span></h3>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Sembol</th>
          <th>BINANCE Perp BBO</th>
          <th>OKX Swap BBO</th>
          <th>Spot-Perp Basis</th>
          <th>En İyi Borsa</th>
          <th>Rejim</th>
          <th>5m İndikatör</th>
          <th>Para Akışı</th>
          <th>10-Ajan Oy</th>
          <th>Karar & Gerekçe</th>
        </tr>
      </thead>
      <tbody id="boardBody"><tr><td colspan="10" style="color:#64748b">Veri yükleniyor...</td></tr></tbody>
    </table>
  </div>
</div>

<div class="section">
  <h3>Açık Pozisyonlar ($50 Marj × 10x Cross | Sert Stop -$40 / %8.0 | Akım-Takip Çıkışı)</h3>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>Sembol</th><th>Borsa</th><th>Yön</th><th>Marj×Kaldıraç</th><th>Giriş</th><th>Canlı</th><th>Stop (-$40)</th><th>Zirve (MFE)</th><th>Anlık Brüt K/Z</th></tr></thead>
      <tbody id="openBody"><tr><td colspan="9" style="color:#64748b">Açık pozisyon yok</td></tr></tbody>
    </table>
  </div>
</div>

<div class="section">
  <h3>10-Ajan Karşılıklı Teftiş Son Diyalog Kaydı (3-Tur Çapraz Denetim)</h3>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>Sembol</th><th>Yön</th><th>Sonuç</th><th>Oy</th><th>Tur-1 → Tur-2 İtiraz & Revizyon Özeti</th></tr></thead>
      <tbody id="debateBody"><tr><td colspan="5" style="color:#64748b">Henüz aday sinyal teftişi oluşmadı</td></tr></tbody>
    </table>
  </div>
</div>

<div class="section">
  <h3>Kapanan İşlemler (Brüt Edge vs Komisyon Ayrımı)</h3>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>#</th><th>Zaman</th><th>Sembol</th><th>Borsa</th><th>Yön</th><th>Giriş → Çıkış</th><th>Brüt K/Z</th><th>Komisyon</th><th>Net K/Z</th><th>R-Çarpanı</th><th>Çıkış Nedeni</th></tr></thead>
      <tbody id="closedBody"><tr><td colspan="11" style="color:#64748b">Henüz kapanan işlem yok</td></tr></tbody>
    </table>
  </div>
</div>

<script>
const fmtPx = (v) => {
  const n = Number(v || 0);
  if (!n) return '-';
  if (n >= 1000) return n.toFixed(2);
  if (n >= 1) return n.toFixed(4);
  return n.toFixed(6);
};
async function refresh(){
  try{
    const r = await fetch('/api/state');
    const s = await r.json();
    document.getElementById('hdrTitle').textContent = `${s.product_label} — Tam Saf Kripto Vadeli Motoru`;
    const phaseTxt = ({WARMUP:'ISINIYOR', ACTIVE:'AKTİF', DRAIN:'DOĞAL KAPANIŞ BEKLENİYOR', COMPLETED:'TAMAMLANDI', INTERRUPTED:'KESİLDİ', FAILED:'HATA'})[s.phase] || s.phase;
    const et = s.evaluation_telemetry || {};
    document.getElementById('evalTotal').textContent = et.evaluation_calls_total ?? 0;
    document.getElementById('evalRetry').textContent = et.retry_suppressed_total ?? 0;
    document.getElementById('evalOther').textContent = `Tekrar dışı çağrı: ${et.non_retry_evaluation_calls ?? 0} — benzersiz sinyal değildir`;
    document.getElementById('clock').textContent = `${phaseTxt} | ${s.elapsed_sec.toFixed(0)}sn`;

    const bn = s.venues.binance || {};
    const ok = s.venues.okx || {};
    document.getElementById('bnStatus').textContent = `BINANCE: ${bn.healthy ? 'AKTİF' : 'BEKLİYOR'} (${((bn.ticks||0)+(bn.bbo_updates||0)).toLocaleString()} pkt | ${s.universe_counts.binance_pure} coin)`;
    document.getElementById('okxStatus').textContent = `OKX: ${ok.healthy ? 'AKTİF' : 'BEKLİYOR'} (${((ok.ticks||0)+(ok.bbo_updates||0)).toLocaleString()} pkt | ${s.universe_counts.okx_pure} coin)`;

    const opHealth = (s.analytics && s.analytics.operational_health) || {healthy:false, alarms:['ANALYTICS_YOK']};
    const hp = document.getElementById('healthPill');
    hp.textContent = opHealth.healthy ? `${opHealth.ledger_status === "IN_FLIGHT" ? "İŞLEM BEKLİYOR" : "MUTABAKAT: TAM"} (Lag ${opHealth.feed_lag_sec}s)` : `ALARM: ${opHealth.alarms.join(',')}`;
    hp.style.color = opHealth.healthy ? '#34d399' : '#ef4444';

    document.getElementById('eq').textContent = '$' + s.equity.toFixed(4);
    document.getElementById('balSub').textContent = `Kapalı Kasa: $${s.balance.toFixed(2)} | $50×10x (Stop -$40)`;
    const np = document.getElementById('netPnl');
    np.textContent = (s.net_pnl >= 0 ? '+$' : '-$') + Math.abs(s.net_pnl).toFixed(4);
    np.className = 'val ' + (s.net_pnl >= 0 ? 'pos' : 'neg');
    document.getElementById('grossSub').textContent = `Brüt: $${s.gross_pnl.toFixed(4)} | Komisyon: -$${s.total_fees.toFixed(4)}`;

    const edge = (s.analytics && s.analytics.edge_separation) || {};
    document.getElementById('feeBps').textContent = `${Number(edge.fee_cost_bps || 0).toFixed(2)} bps`;
    document.getElementById('edgeBps').textContent = `Brüt: ${Number(edge.pre_fee_edge_bps || 0).toFixed(2)} bps | Net: ${Number(edge.post_fee_edge_bps || 0).toFixed(2)} bps`;

    const mq = (s.analytics && s.analytics.maker_queue) || {};
    document.getElementById('makerFill').textContent = `%${Number(mq.fill_rate_pct || 0).toFixed(1)} Dolum`;
    document.getElementById('makerSub').textContent = `Dolan: ${mq.filled||0} | İptal: ${mq.expired_unfilled||0} | TersSeçim: ${Number(mq.avg_unfilled_runaway_bps||0).toFixed(1)} bps`;

    document.getElementById('univCnt').textContent = `${s.universe_counts.union_pure} Saf Coin`;
    document.getElementById('univSub').textContent = `BN: ${s.universe_counts.binance_pure} | OKX: ${s.universe_counts.okx_pure} | ABD Hisse/Emtia: 0`;

    document.getElementById('openCnt').textContent = `${s.open_positions.length} Açık (Cross)`;
    document.getElementById('uPnl').textContent = 'Açık K/Z: ' + (s.unrealized_pnl >= 0 ? '+$' : '-$') + Math.abs(s.unrealized_pnl).toFixed(4);

    const tac = (s.analytics && s.analytics.ten_agent_council) || {};
    const tacSt = tac.stats || {};
    document.getElementById('tenAgent').textContent = `${tacSt.entry_audits||0} Giriş | ${tacSt.position_audits||0} Açık`;
    document.getElementById('tenSub').textContent = `Onay: ${tacSt.entry_approved||0} | Veto: ${tacSt.entry_rejected||0} | MinMaliyet×${Number(tac.dynamic_min_gross_fee_mult||3.5).toFixed(2)}`;

    const cf = (s.analytics && s.analytics.counterfactual) || {};
    const sh = cf.shadow_135s_cut_comparison || {};
    const gates = cf.gate_asymmetry_and_forward_returns || {};
    const blockedTot = Object.values(gates).reduce((a, g) => a + Number(g.total || 0), 0);
    const adv = Number(sh.net_advantage_of_holding_usdt || 0);
    document.getElementById('cfDelta').textContent = (adv >= 0 ? '+$' : '-$') + Math.abs(adv).toFixed(4);
    document.getElementById('cfSub').textContent = `Engellenen Sinyal: ${blockedTot} | Gölge135s: ${sh.completed_count||0}`;

    document.getElementById('pairCount').textContent = `${s.market_board.length} Aktif Derin Parite / ${s.universe_counts.union_pure} Tam Evren`;

    const bb = document.getElementById('boardBody');
    bb.innerHTML = s.market_board.map(m => {
      const bnTxt = m.bn_bid ? `${fmtPx(m.bn_bid)} / ${fmtPx(m.bn_ask)} <span style="color:#94a3b8">(${m.bn_spread_bps.toFixed(1)} bps)</span>` : '<span style="color:#64748b">-</span>';
      const okTxt = m.okx_bid ? `${fmtPx(m.okx_bid)} / ${fmtPx(m.okx_ask)} <span style="color:#94a3b8">(${m.okx_spread_bps.toFixed(1)} bps)</span>` : '<span style="color:#64748b">-</span>';
      const bestCls = (m.best_venue || 'binance').toUpperCase();
      const sigCls = m.last_signal || 'BEKLE';
      return `<tr>
        <td><b>${m.symbol}</b></td>
        <td>${bnTxt}</td>
        <td>${okTxt}</td>
        <td class="${Math.abs(m.basis_bps) < 15 ? 'pos' : 'warn'}">${m.basis_bps >= 0 ? '+' : ''}${m.basis_bps.toFixed(1)} bps</td>
        <td><span class="badge ${bestCls}">${bestCls}</span></td>
        <td>${m.regime || '-'}</td>
        <td class="${m.ind_score >= 0 ? 'pos' : 'neg'}">${m.ind_score >= 0 ? '+' : ''}${m.ind_score.toFixed(1)}</td>
        <td class="${m.flow_score >= 0 ? 'pos' : 'neg'}">${m.flow_score >= 0 ? '+' : ''}${m.flow_score.toFixed(1)}</td>
        <td>${m.ten_agent_votes || '-'}</td>
        <td><span class="badge ${sigCls}">${sigCls}</span> <span style="color:#94a3b8;font-size:11px">${m.reason || ''}</span></td>
      </tr>`;
    }).join('');

    const ob = document.getElementById('openBody');
    if(!s.open_positions.length){
      ob.innerHTML = '<tr><td colspan="9" style="color:#64748b">Açık pozisyon yok</td></tr>';
    } else {
      ob.innerHTML = s.open_positions.map(p => {
        const vCls = (p.exchange || 'binance').toUpperCase();
        return `<tr>
          <td><b>${p.symbol}</b></td>
          <td><span class="badge ${vCls}">${vCls}</span></td>
          <td><span class="badge ${p.side}">${p.side}</span></td>
          <td>$${Number(p.margin_usdt||50).toFixed(0)} × ${p.leverage||10}x</td>
          <td>${fmtPx(p.entry)}</td>
          <td>${fmtPx(p.mark)}</td>
          <td>${fmtPx(p.stop)}</td>
          <td class="pos">+$${p.mfe.toFixed(3)}</td>
          <td class="${p.upnl >= 0 ? 'pos' : 'neg'}">${p.upnl >= 0 ? '+$' : '-$'}${Math.abs(p.upnl).toFixed(4)}</td>
        </tr>`;
      }).join('');
    }

    const db = document.getElementById('debateBody');
    const debates = (tac.recent_dialogues || []).slice().reverse();
    if(!debates.length){
      db.innerHTML = '<tr><td colspan="5" style="color:#64748b">Henüz aday sinyal teftişi oluşmadı</td></tr>';
    } else {
      db.innerHTML = debates.slice(0, 6).map(d => {
        const sample = (d.messages || []).join(' | ');
        return `<tr>
          <td><b>${d.symbol}</b></td>
          <td><span class="badge ${d.side}">${d.side}</span></td>
          <td class="${d.approved ? 'pos' : 'warn'}"><b>${d.approved ? 'ONAY' : 'VETO'}</b></td>
          <td>${d.votes || '-'}</td>
          <td style="font-size:11px;color:#cbd5e1">${sample.slice(0, 155)}</td>
        </tr>`;
      }).join('');
    }

    const cb = document.getElementById('closedBody');
    if(!s.closed_trades.length){
      cb.innerHTML = '<tr><td colspan="11" style="color:#64748b">Henüz kapanan işlem yok</td></tr>';
    } else {
      cb.innerHTML = s.closed_trades.map((t, idx) => {
        const vCls = (t.exchange || 'binance').toUpperCase();
        const rMult = Number(t.pnl_usdt || 0) / 40.0;
        return `<tr>
          <td>${idx + 1}</td>
          <td>${(t.closed_at || '').slice(0, 8)}</td>
          <td><b>${t.symbol}</b></td>
          <td><span class="badge ${vCls}">${vCls}</span></td>
          <td><span class="badge ${t.side}">${t.side}</span></td>
          <td>${fmtPx(t.entry_price)} → ${fmtPx(t.exit_price)}</td>
          <td class="${t.gross_pnl >= 0 ? 'pos' : 'neg'}">${t.gross_pnl >= 0 ? '+$' : '-$'}${Math.abs(t.gross_pnl).toFixed(4)}</td>
          <td class="warn">-$${Number(t.fee_usdt || 0).toFixed(4)}</td>
          <td class="${t.pnl_usdt >= 0 ? 'pos' : 'neg'}"><b>${t.pnl_usdt >= 0 ? '+$' : '-$'}${Math.abs(t.pnl_usdt).toFixed(4)}</b></td>
          <td class="${rMult >= 0 ? 'pos' : 'neg'}">${rMult >= 0 ? '+' : ''}${rMult.toFixed(3)}R</td>
          <td>${t.reason || ''}</td>
        </tr>`;
      }).join('');
    }
  } catch(e){}
}
setInterval(refresh, 1500);
refresh();
</script>
</body>
</html>
"""


class _LogAlerter:
    def __init__(self, sink: list[dict[str, Any]]) -> None:
        self._sink = sink

    async def send(self, text: str, **_: Any) -> bool:
        log.info("[BİLDİRİM] %s", text)
        self._sink.append({"ts": _utc_now_iso(), "msg": text})
        return True

    def __call__(self, text: str) -> Any:
        return self.send(text)


class DualVenueLiveRunner:
    """v9.4 Tam Saf Kripto Vadeli Evren (~545+ Coin) + Çift Borsa Canlı Motoru."""

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        duration_sec: float = 0.0,
        max_drain_sec: float = 600.0,
        port: int | None = None,
        report_prefix: str | None = None,
        keep_panel_alive: bool = False,
    ) -> None:
        self.cfg = cfg
        self.product_version = str(cfg.get("version") or "9.2.1")
        self.product_label = f"Kripto Bot v{self.product_version}"
        self.duration_sec = float(duration_sec)
        self.max_drain_sec = float(max_drain_sec)
        self.port = int(port if port is not None else cfg.get("panel", {}).get("port", 8080))
        self.report_prefix = report_prefix or f"canli_v{self.product_version.replace('.', '')}"
        self.keep_panel_alive = bool(keep_panel_alive)

        self.reports_dir = BASE_DIR / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.reports_dir / f"{self.report_prefix}_state.db"
        self.jsonl_path = self.reports_dir / f"{self.report_prefix}_decisions.jsonl"
        self.summary_path = self.reports_dir / f"{self.report_prefix}_summary.json"
        if report_prefix:
            for p in (self.db_path, self.jsonl_path, self.summary_path):
                if p.exists():
                    p.unlink()

        g = cfg["genel"]
        r = cfg["risk"]
        sn = cfg["sinyal"]
        bz = cfg.get("boyutlandirma", {})
        em = cfg.get("emirler", {})
        sg = cfg.get("sigorta", {})
        plan_cfg = cfg.get("islem_plani", {})
        exit_cfg = cfg.get("cikis", {})
        db_cfg = cfg.get("veritabani", {})
        mode = str(g.get("mod", "paper")).lower()
        leverage = int(g.get("kaldıraç", bz.get("kaldirac", 10)) or 10)
        capital_pct = float(r.get("kasa_giris_yuzde", bz.get("kasa_yuzde", 5.0)))

        self.store = StateStore(
            self.db_path,
            wal_mode=bool(db_cfg.get("wal_modu", True)),
            maintenance_interval_sec=float(db_cfg.get("cop_toplayici_saniye", 86400.0)),
        )
        self.cb = CircuitBreaker(
            max_consecutive_errors=int(sg.get("max_ardisik_emir_hatasi", 3)),
            daily_max_loss_pct=float(sg.get("gunluk_max_zarar_yuzde", r.get("gunluk_max_zarar_yuzde", 20.0))),
            max_ws_disconnect_sec=float(sg.get("ws_kopma_saniye", 20.0)),
            flash_crash_pct=float(sg.get("flash_crash_yuzde", 8.0)),
            max_consecutive_auth_errors=int(sg.get("max_ardisik_yetki_hatasi", 3)),
            state_store=self.store,
            global_shock_symbols=sg.get("global_sok_sembolleri", ["BTC/USDT", "ETH/USDT"]),
            symbol_shock_cooldown_sec=float(sg.get("altcoin_sok_mola_saniye", 900.0)),
        )

        self.broker = ExchangeManager(cfg)
        self.broker.smart_maker_execution = bool(cfg.get("paper", {}).get("akilli_maker_yurutme", True))
        self.broker.dynamic_slippage_enabled = bool(cfg.get("paper", {}).get("dinamik_atr_kayma", True))
        self.broker.max_maker_spread_pct = float(em.get("max_maker_makas_yuzde", 0.05))

        pos_limits = position_limits_for_mode(r, mode)
        risk_class = V94RiskManager if cfg.get("v94", {}).get("enabled", False) else RiskManager
        self.risk = risk_class(
            stop_loss_pct=r["stop_loss_yuzde"],
            stop_model=r.get("stop_modeli", "marj"),
            margin_stop_fraction=float(r.get("marj_zarar_orani", 0.80)),
            margin_stop_liq_buffer=float(r.get("marj_stop_likidasyon_tamponu", 0.85)),
            lock_trigger_pct=r["kar_kilit_tetikleyici"],
            lock_level_pct=r["kar_kilit_seviyesi"],
            trail_pct=r["trailing_yuzde"],
            risk_per_trade_pct=r["islem_basina_risk_yuzde"],
            max_positions=pos_limits["max_positions"],
            daily_max_loss_pct=r["gunluk_max_zarar_yuzde"],
            capital_pct_per_entry=capital_pct,
            leverage=leverage,
            unlimited_pyramiding=bool(r.get("sinirsiz_ekleme", False)),
            pyramid_min_profit_pct=float(r.get("ekleme_min_kar_yuzde", 0.40)),
            pair_rescue_enabled=bool(r.get("capraz_kurtarma", False)),
            rescue_min_loser_pct=float(r.get("kurtarma_min_zarar_yuzde", 0.8)),
            max_slippage_pct=float(r.get("max_kayma_yuzde", 0.20)),
            dynamic_leverage_enabled=bool(r.get("dinamik_kaldirac", False)),
            atr_high_volatility_pct=float(r.get("atr_yuksek_oynaklik_yuzde", 1.5)),
            atr_extreme_volatility_pct=float(r.get("atr_asiri_oynaklik_yuzde", 3.0)),
            max_layers=int(r.get("max_kademe", 1)),
            hard_max_positions=pos_limits["hard_max_positions"],
            max_same_side_positions=pos_limits["max_same_side_positions"],
            max_total_margin_pct=float(r.get("toplam_marj_tavani_yuzde", 98.0)),
            weekly_max_loss_pct=float(r.get("haftalik_max_zarar_yuzde", 40.0)),
            liq_stop_buffer=float(r.get("likidasyon_stop_tamponu", 0.85)),
            margin_mode=str(r.get("marj_modu", "cross")),
            cross_max_margin_pct=float(r.get("capraz_max_kullanim_yuzde", 98.0)),
            cross_min_free_usdt=float(r.get("capraz_min_serbest_usdt", 0.0)),
            early_lock_trigger_pct=float(r.get("erken_kar_kilit_tetik", 0.0)),
            early_lock_level_pct=float(r.get("erken_kar_kilit_seviye", 0.0)),
            mfe_lock_min_usdt=float(r.get("zirve_kar_koruma_min_usdt", 2.40)),
            mfe_lock_keep_ratio=float(r.get("zirve_kar_koruma_orani", 0.66)),
            atr_trail_mult=float(r.get("atr_trailing_carpani", 2.4)),
            state_store=self.store,
        )

        if cfg.get("v94", {}).get("enabled", False):
            self.risk.policy = AdaptivePolicy(**cfg["v94"].get("policy", {}))

        self.strategy = Strategy(
            sn["agirlik_indikator"],
            sn["agirlik_para_akisi"],
            sn["agirlik_haber"],
            sn["long_esik"],
            sn["short_esik"],
            sn["cikis_esik"],
            g.get("short_izni", True),
            w_ml=0.0,
            flow_trigger=bool(sn.get("para_akisi_tetik", True)),
            flow_th=float(sn.get("para_akisi_esik", 36.0)),
            flow_ind_min=float(sn.get("tetik_indikator_min", 8.0)),
            flow_min_total=float(sn.get("tetik_min_toplam", 18.0)),
            regime_filter=bool(sn.get("rejim_bazli", True)),
            breakout_flow_confirmation=bool(sn.get("breakout_akim_onayi", True)),
            orderflow_filter=bool(sn.get("orderflow_onayi", True)),
            runner_exit=bool(exit_cfg.get("kosan_kar", True)),
        )

        size_mode = bz.get("mod", "sabit_usdt")
        self.sizer = PositionSizer(
            base_risk_pct=r["islem_basina_risk_yuzde"],
            atr_mult=bz.get("atr_katsayi", 1.25),
            kelly_on=size_mode in ("kelly", "atr_kelly"),
            kelly_fraction=bz.get("kelly_kesir", 0.5),
            kelly_min_risk=bz.get("kelly_min_risk", 0.25),
            kelly_max_risk=bz.get("kelly_max_risk", 1.5),
            kelly_min_trades=bz.get("kelly_min_islem", 20),
            stats_path=self.reports_dir / f"{self.report_prefix}_kelly.json",
            mode=size_mode,
            capital_pct=capital_pct,
            leverage=leverage,
            fixed_margin_usdt=float(bz.get("sabit_marj_usdt", 50.0)),
        )

        self.events: list[dict[str, Any]] = []
        self.alerter = _LogAlerter(self.events)

        self.executor = Executor(
            self.broker,
            self.risk,
            self.strategy,
            self.sizer,
            self.alerter,
            int(r["mola_saniye"]),
            em.get("giris_tipi", "maker"),
            float(em.get("maker_zaman_asimi_sn", 3.5)),
            bool(em.get("borsa_korumasi", True)),
            state_store=self.store,
            circuit_breaker=self.cb,
            supertrend_trailing=bool(sn.get("supertrend_iz_takibi", True)),
            trade_plan_cfg=plan_cfg,
            runner_exit_cfg=exit_cfg,
            exit_fee_pct=float(em.get("komisyon_taker_yuzde", 0.05)),
            net_breakeven_enabled=bool(exit_cfg.get("net_basabas_aktif", True)),
            net_profit_buffer_usdt=float(exit_cfg.get("net_kar_tamponu_usdt", 0.35)),
            min_bb_width_pct=float(sn.get("min_bb_genisligi_yuzde", 0.14)),
            min_atr_pct=float(sn.get("min_atr_yuzde", 0.08)),
            dedup_twin_assets=bool(sn.get("ikiz_varlik_korumasi", True)),
            opportunity_swap_enabled=bool(r.get("firsat_takasi_aktif", False)),
            opportunity_swap_min_age_sec=float(r.get("firsat_takasi_min_dakika", 10.0)) * 60.0,
            funding_settlement_only=bool(cfg.get("paper", {}).get("funding_gercek_8s_uzlasma", True)),
        )
        if mode == "paper":
            rec = self.executor.reconcile_and_unlock_paper_state(owner_id="kripto-bot-v94-main")
            log.info("Paper defter mutabakatı: %s", rec)

        self.detector = SpikeDetector(baglam_aktif=True)
        rm_cfg = cfg.get("rejim_makinesi", {})
        breadth_th = float(rm_cfg.get("genislik_fade_esigi", 0.35))
        self.regime_machine = RegimeStateMachine(
            min_confirm_bars=int(rm_cfg.get("min_onay_mumu", 2)),
            adx_enter=float(rm_cfg.get("adx_giris", 22.0)),
            adx_exit=float(rm_cfg.get("adx_cikis", 18.0)),
            breadth_min_ratio=breadth_th,
            fade_min_vwap_z=float(rm_cfg.get("fade_min_vwap_z", 1.65)),
            choppy_choppiness_min=float(rm_cfg.get("choppy_choppiness_esigi", 61.8)),
            crash_5m_pct=float(rm_cfg.get("crash_5m_sok_yuzde", -1.8)),
            crash_1h_pct=float(rm_cfg.get("crash_1h_dusus_yuzde", -3.5)),
            volume_decline_ratio_max=float(rm_cfg.get("hacim_daralma_orani_ust", 0.94)),
            block_long_in_bearish_distribution=bool(rm_cfg.get("ayi_ve_dagitimda_long_engeli", True)),
        )
        self.council = QuantRuleCouncil()
        self.referee = LiveLLMReferee.from_config_dict(
            cfg.get("api"),
            timeout_sec=float(cfg.get("llm_hakem", {}).get("timeout_saniye", 2.5)),
            ref_cfg=cfg.get("llm_hakem"),
        )
        self.win_loss = WinLossAnalyzer()
        self.comm_opt = CommissionOptimizer(max_entry_spread_pct=0.08)

        self.engine = UnifiedTradingEngine(
            self.executor,
            mode="hybrid_fusion",
            council=self.council,
            detector=self.detector,
            commission_optimizer=self.comm_opt,
            win_loss_analyzer=self.win_loss,
            regime_machine=self.regime_machine,
            llm_referee=self.referee,
            breadth_fade_threshold=breadth_th,
            require_vwap_warmup=True,
            cfg=cfg,
        )

        self.symbols: list[str] = []
        self.universe_all_symbols: list[str] = []
        self.binance_pure_symbols: set[str] = set()
        self.okx_pure_symbols: set[str] = set()
        self.excluded_non_crypto_count: dict[str, int] = {"okx_stocks_commodities": 0, "binance_non_crypto": 0}
        self.okx_ct_val: dict[str, float] = {}
        self.ohlcv_5m: dict[str, pd.DataFrame] = {}
        self.ohlcv_15m: dict[str, pd.DataFrame] = {}
        self.ohlcv_1h: dict[str, pd.DataFrame] = {}
        self.funding_rates: dict[str, float] = {}
        self.board_decisions: dict[str, dict[str, Any]] = {}
        self.first_seen_mid: dict[str, tuple[float, float]] = {}

        self.binance_perp_bbo: dict[str, tuple[float, float, float]] = {}
        self.binance_spot_mid: dict[str, float] = {}
        self.binance_basis_offset: dict[str, float] = {}

        self.venue_stats: dict[str, dict[str, Any]] = {
            "binance": {"ticks": 0, "bbo_updates": 0, "last_ts": 0.0, "last_bbo_ts": 0.0, "last_trade_ts": 0.0, "errors": 0, "errors_aggTrade": 0, "errors_bookTicker": 0, "endpoint_aggTrade": "init", "endpoint_bookTicker": "init", "endpoint": "see stream-specific endpoints"},
            "okx": {"ticks": 0, "bbo_updates": 0, "endpoint": "wss://ws.okx.com/ws/v5/public", "last_ts": 0.0, "last_bbo_ts": 0.0, "last_trade_ts": 0.0, "errors": 0},
        }
        self.start_ts = time.time()
        self.phase = "WARMUP"
        self.allow_new_entries = True
        self.stop_Flag = False
        self.drain_elapsed_sec = 0.0

    async def discover_full_pure_crypto_universe(self, session: aiohttp.ClientSession) -> list[str]:
        """Binance USDⓈ-M + OKX USDT-SWAP üzerindeki TÜM saf kripto vadeli kontratları (~545+) keşfeder.

        ABD hisse senetleri (`OKX instCategory == "3"`), emtialar (`instCategory == "4"`) ve sentetik/fiat
        kontratlar %100 elenir; hiçbir saf coine 12-parite tavanı veya hacim alt sınırı uygulanmaz.
        """
        pool_size = int(self.cfg.get("cift_borsa", {}).get("aktif_derin_havuz_boyutu", 40) or 40)

        # 1) OKX enstrüman kataloğu: yalnızca instCategory == "1" (Saf Kripto) ve ruleType == "normal"
        async with session.get(
            "https://www.okx.com/api/v5/public/instruments?instType=SWAP", timeout=15
        ) as resp:
            okx_inst_rows = (await resp.json()).get("data", [])

        okx_allowed_bases: set[str] = set()
        for row in okx_inst_rows:
            inst = str(row.get("instId", ""))
            if not inst.endswith("-USDT-SWAP") or str(row.get("state", "")) != "live":
                continue
            cat = str(row.get("instCategory", ""))
            rule_t = str(row.get("ruleType", "normal"))
            base = inst.split("-")[0].upper()
            if cat != "1" or rule_t != "normal":
                self.excluded_non_crypto_count["okx_stocks_commodities"] += 1
                continue
            if base in EXCLUDED_BASES or not base.isalnum():
                self.excluded_non_crypto_count["okx_stocks_commodities"] += 1
                continue
            sym = f"{base}/USDT"
            if not UnifiedTradingEngine.filter_pure_crypto_symbols([sym]):
                self.excluded_non_crypto_count["okx_stocks_commodities"] += 1
                continue
            okx_allowed_bases.add(base)
            self.okx_pure_symbols.add(sym)
            try:
                self.okx_ct_val[sym] = float(row.get("ctVal") or 1.0)
            except Exception:
                self.okx_ct_val[sym] = 1.0

        # 2) Binance USDⓈ-M Perpetual kataloğu (`www.binance.com/fapi/v1/exchangeInfo`)
        async with session.get(
            "https://www.binance.com/fapi/v1/exchangeInfo", timeout=15
        ) as resp:
            bn_info = await resp.json()
        for row in bn_info.get("symbols", []):
            if (
                str(row.get("status")) != "TRADING"
                or str(row.get("contractType")) != "PERPETUAL"
                or str(row.get("quoteAsset")) != "USDT"
            ):
                continue
            base = str(row.get("baseAsset") or "").upper()
            sym = f"{base}/USDT"
            if base in EXCLUDED_BASES or not base.isalnum() or not UnifiedTradingEngine.filter_pure_crypto_symbols([sym]):
                self.excluded_non_crypto_count["binance_non_crypto"] += 1
                continue
            self.binance_pure_symbols.add(sym)

        # 3) Canlı BBO & 24s aktivite anlık görüntüsü (her iki borsanın tamamı)
        okx_books: dict[str, tuple[float, float, float]] = {}
        async with session.get(
            "https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=12
        ) as resp:
            okx_tickers = (await resp.json()).get("data", [])
        for row in okx_tickers:
            inst = str(row.get("instId", ""))
            if not inst.endswith("-USDT-SWAP"):
                continue
            base = inst.split("-")[0].upper()
            if base not in okx_allowed_bases:
                continue
            sym = f"{base}/USDT"
            bid = float(row.get("bidPx") or 0.0)
            ask = float(row.get("askPx") or 0.0)
            last = float(row.get("last") or 0.0)
            vol_usdt = float(row.get("volCcy24h") or 0.0) * last
            if bid > 0 and ask >= bid:
                okx_books[sym] = (bid, ask, vol_usdt)

        bn_books: dict[str, tuple[float, float]] = {}
        async with session.get(
            "https://www.binance.com/fapi/v1/ticker/bookTicker", timeout=12
        ) as resp:
            bn_rows = await resp.json()
        now_s = time.time()
        for row in bn_rows:
            raw_s = str(row.get("symbol", ""))
            if not raw_s.endswith("USDT"):
                continue
            sym = f"{raw_s[:-4]}/USDT"
            if sym not in self.binance_pure_symbols:
                continue
            bid = float(row.get("bidPrice") or 0.0)
            ask = float(row.get("askPrice") or 0.0)
            if bid > 0 and ask >= bid:
                bn_books[sym] = (bid, ask)
                self.binance_perp_bbo[sym] = (bid, ask, now_s)

        union_syms = sorted(set(bn_books.keys()) | set(okx_books.keys()))
        self.universe_all_symbols = union_syms

        # Her sembolün hangi borsalarda gerçekten işlem gördüğünü ExchangeManager'a kaydet
        sym_ex_map: dict[str, list[str]] = {}
        for sym in union_syms:
            venues: list[str] = []
            if sym in bn_books:
                venues.append("binance")
            if sym in okx_books:
                venues.append("okx")
            if venues:
                sym_ex_map[sym] = venues
        self.broker.symbol_exchanges = sym_ex_map
        self.broker.symbols = list(union_syms)

        now_ms = int(now_s * 1000)
        for sym in union_syms:
            if sym in bn_books:
                b, a = bn_books[sym]
                mid = (b + a) / 2.0
                self.broker.update_live_bbo("binance", sym, b, a, now_s)
                self.engine.ingest_universe_price("binance", sym, mid, now_ms)
                self.first_seen_mid[sym] = (mid, now_s)
            if sym in okx_books:
                b, a, _ = okx_books[sym]
                mid = (b + a) / 2.0
                self.broker.update_live_bbo("okx", sym, b, a, now_s)
                self.engine.ingest_universe_price("okx", sym, mid, now_ms)
                self.first_seen_mid.setdefault(sym, (mid, now_s))

        self.venue_stats["binance"]["last_ts"] = now_s
        self.venue_stats["okx"]["last_ts"] = now_s
        self.venue_stats["binance"]["last_bbo_ts"] = now_s
        self.venue_stats["okx"]["last_bbo_ts"] = now_s

        # İlk aktif derin havuz: çekirdek coinler + OKX/Binance çeşitli saf kripto vadeli pariteler
        selected: list[str] = []
        for base in CORE_SEED_BASES:
            s = f"{base}/USDT"
            if s in sym_ex_map and s not in selected:
                selected.append(s)
                if len(selected) >= pool_size:
                    break
        if len(selected) < pool_size:
            ranked_okx = sorted(okx_books.items(), key=lambda kv: kv[1][2], reverse=True)
            for sym, _ in ranked_okx:
                if sym not in selected:
                    selected.append(sym)
                if len(selected) >= pool_size:
                    break
        if len(selected) < pool_size:
            for sym in union_syms:
                if sym not in selected:
                    selected.append(sym)
                if len(selected) >= pool_size:
                    break

        self.cfg["genel"]["semboller"] = list(selected)
        log.info(
            "Tam saf kripto vadeli evren hazır: Toplam=%d saf coin (Binance=%d, OKX=%d | Elenen hisse/emtia=%d) | Başlangıç derin havuz=%d",
            len(union_syms),
            len(self.binance_pure_symbols),
            len(self.okx_pure_symbols),
            sum(self.excluded_non_crypto_count.values()),
            len(selected),
        )
        return selected

    async def _fetch_binance_perp_candles(
        self, session: aiohttp.ClientSession, sym: str, interval: str, limit: int
    ) -> list[list[float]]:
        """Binance USDⓈ-M Perpetual `/fapi/v1/klines` mumlarını (gerçek vadeli taker-buy hacmi dahil) çeker."""
        raw = _sym_to_binance_raw(sym)
        url = f"https://www.binance.com/fapi/v1/klines?symbol={raw}&interval={interval}&limit={limit}"
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                return []
            rows = await resp.json()
        parsed = []
        for r in rows:
            ts_ms = int(r[0])
            o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
            base_v = float(r[5])
            quote_v = float(r[7])
            taker_buy_base = float(r[9]) if len(r) > 9 else base_v * 0.5
            parsed.append([ts_ms, o, h, l, c, base_v, quote_v, taker_buy_base, float(r[10])])
        return parsed

    async def _fetch_okx_candles(
        self, session: aiohttp.ClientSession, sym: str, bar: str, limit: int
    ) -> list[list[float]]:
        inst = _sym_to_okx_inst(sym)
        url = f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar={bar}&limit={limit}"
        async with session.get(url, timeout=10) as resp:
            rows = (await resp.json()).get("data", [])
        parsed = []
        for r in reversed(rows):
            ts_ms = int(r[0])
            o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
            base_coin = float(r[6]) if len(r) > 6 and float(r[6]) > 0 else 0.0
            quote_usdt = float(r[7]) if len(r) > 7 and float(r[7]) > 0 else (base_coin * c)
            parsed.append([ts_ms, o, h, l, c, base_coin, quote_usdt, base_coin * 0.5, float("nan")])
        return parsed

    async def _fetch_candles_best_source(
        self, session: aiohttp.ClientSession, sym: str, tf: str, limit: int
    ) -> list[list[float]]:
        venues = self.broker.symbol_exchanges.get(sym, [])
        if "binance" in venues:
            bn_tf = "1h" if tf.upper() == "1H" else tf
            rows = await self._fetch_binance_perp_candles(session, sym, bn_tf, limit)
            if rows:
                return rows
        if "okx" in venues:
            ok_tf = "1H" if tf.lower() == "1h" else tf
            rows = await self._fetch_okx_candles(session, sym, ok_tf, limit)
            if rows:
                return rows
        return []

    @staticmethod
    def _rows_to_df(rows: list[list[float]]) -> pd.DataFrame:
        now_ms = int(time.time() * 1000)
        # API responses include the forming candle: exclude it using each response interval.
        interval_ms = int(rows[-1][0] - rows[-2][0]) if len(rows) > 1 else 300_000
        trimmed = [[r[0], r[1], r[2], r[3], r[4], r[6], r[8] if len(r)>8 else float("nan")]
                   for r in rows if int(r[0]) + interval_ms <= now_ms]
        return pd.DataFrame(trimmed, columns=["ts", "open", "high", "low", "close", "volume", "taker_buy_quote"])

    def _ingest_1m_rows(self, sym: str, rows_1m: list[list[float]]) -> None:
        now_min = int(time.time() * 1000) // 60_000
        for r in rows_1m:
            mid = int(r[0]) // 60_000
            if mid >= now_min:
                continue
            self.engine.ingest_closed_1m_candle(
                "binance",
                sym,
                mid,
                r[1],
                r[2],
                r[3],
                r[4],
                r[5],
                r[6],
                mirror_exchanges=True,
            )
        # Son 5 dakikalık gerçek vadeli alıcı/satıcı hacmini MoneyFlow penceresine yalnız ilk kez tohumla
        flow = self.engine.flow_for(sym)
        if not getattr(flow, "_seeded_from_klines", False) and len(rows_1m) >= 5:
            flow._seeded_from_klines = True
            now_s = time.time()
            for idx_r, r in enumerate(rows_1m[-5:]):
                c_px = float(r[4])
                base_v = float(r[5])
                tb_base = float(r[7]) if len(r) > 7 else base_v * 0.5
                ts_seed = now_s - (5 - idx_r) * 45.0
                if c_px > 0 and tb_base > 0:
                    flow.add_trade(c_px, tb_base, is_buyer_maker=False, ts=ts_seed)
                ts_sell = max(0.0, base_v - tb_base)
                if c_px > 0 and ts_sell > 0:
                    flow.add_trade(c_px, ts_sell, is_buyer_maker=True, ts=ts_seed + 1.0)

    async def warmup_symbol(self, session: aiohttp.ClientSession, sym: str) -> None:
        c1m, c5m, c15m, c1h = await asyncio.gather(
            self._fetch_candles_best_source(session, sym, "1m", 70),
            self._fetch_candles_best_source(session, sym, "5m", 600),
            self._fetch_candles_best_source(session, sym, "15m", 65),
            self._fetch_candles_best_source(session, sym, "1h", 55),
        )
        if c1m:
            self._ingest_1m_rows(sym, c1m)
        if c5m:
            self.ohlcv_5m[sym] = self._rows_to_df(c5m)
        if c15m:
            self.ohlcv_15m[sym] = self._rows_to_df(c15m)
        if c1h:
            self.ohlcv_1h[sym] = self._rows_to_df(c1h)

    async def warmup_all(self, session: aiohttp.ClientSession) -> None:
        sem = asyncio.Semaphore(8)

        async def _warm_one(sym: str) -> None:
            async with sem:
                await self.warmup_symbol(session, sym)

        await asyncio.gather(*(_warm_one(s) for s in self.symbols))
        # Tüm Binance vadeli paritelerinin güncel fonlama oranlarını tek toplu çağrıyla çek (`weight=1`)
        try:
            async with session.get("https://www.binance.com/fapi/v1/premiumIndex", timeout=10) as f_resp:
                if f_resp.status == 200:
                    for row in await f_resp.json():
                        raw_s = str(row.get("symbol", ""))
                        if raw_s.endswith("USDT"):
                            sym = f"{raw_s[:-4]}/USDT"
                            if sym in self.binance_pure_symbols:
                                self.funding_rates[sym] = float(row.get("lastFundingRate") or 0.0)
        except Exception:
            pass
        log.info(
            "65dk VWAP60 + 5m/15m/1h tam evren ısınması tamamlandı (%d mum kaydı, %d aktif derin parite).",
            self.engine.metrics["candles_ingested"],
            len(self.symbols),
        )

    async def full_universe_bbo_and_scanner_loop(self, session: aiohttp.ClientSession) -> None:
        """Her 4 sn'de bir TÜM ~545+ saf kripto vadeli paritenin Binance + OKX BBO fiyatlarını günceller,
        Spot-Perp basis sapmasını ölçer ve sert hareket eden herhangi bir coini derin havuza terfi ettirir."""
        raw_bn = {_sym_to_binance_raw(s): s for s in self.binance_pure_symbols}
        cycle = 0
        while not self.stop_Flag:
            cycle += 1
            now_s = time.time()
            now_ms = int(now_s * 1000)
            movers: list[tuple[float, str]] = []
            try:
                async with session.get(
                    "https://www.binance.com/fapi/v1/ticker/bookTicker", timeout=6
                ) as resp:
                    if resp.status == 200:
                        rows = await resp.json()
                        for row in rows:
                            sym = raw_bn.get(str(row.get("symbol", "")))
                            if not sym:
                                continue
                            bid = float(row.get("bidPrice") or 0.0)
                            ask = float(row.get("askPrice") or 0.0)
                            if bid > 0 and ask >= bid:
                                perp_mid = (bid + ask) / 2.0
                                self.binance_perp_bbo[sym] = (bid, ask, now_s)
                                spot_mid = self.binance_spot_mid.get(sym, 0.0)
                                if spot_mid > 0:
                                    self.binance_basis_offset[sym] = perp_mid - spot_mid
                                    self.engine.set_spot_perp_basis(sym, perp_mid, spot_mid)
                                self.broker.update_live_bbo("binance", sym, bid, ask, now_s)
                                self.engine.ingest_universe_price("binance", sym, perp_mid, now_ms)
                                self.venue_stats["binance"]["bbo_updates"] += 1
                                self.venue_stats["binance"]["last_ts"] = now_s
                                if sym in self.executor.positions:
                                    await self.executor.on_price_tick(sym, perp_mid, exchange="binance")
                                ref_mid, ref_ts = self.first_seen_mid.get(sym, (perp_mid, now_s))
                                if now_s - ref_ts >= 45.0:
                                    self.first_seen_mid[sym] = (perp_mid, now_s)
                                move_pct = abs(perp_mid - ref_mid) / max(ref_mid, 1e-12) * 100.0
                                if move_pct >= 0.40 and sym not in self.ohlcv_5m:
                                    movers.append((move_pct, sym))
            except Exception as exc:
                self.venue_stats["binance"]["errors"] += 1
                log.debug("Binance tam evren BBO uyarısı: %s", exc)

            # OKX tüm saf kripto swap BBO güncellemesi (her 2 döngüde = 8 sn'de bir)
            if cycle % 2 == 0:
                try:
                    async with session.get(
                        "https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=7
                    ) as ok_resp:
                        if ok_resp.status == 200:
                            for row in (await ok_resp.json()).get("data", []):
                                inst = str(row.get("instId", ""))
                                if not inst.endswith("-USDT-SWAP"):
                                    continue
                                sym = f"{inst.split('-')[0].upper()}/USDT"
                                if sym not in self.okx_pure_symbols:
                                    continue
                                bid = float(row.get("bidPx") or 0.0)
                                ask = float(row.get("askPx") or 0.0)
                                if bid > 0 and ask >= bid:
                                    mid = (bid + ask) / 2.0
                                    self.broker.update_live_bbo("okx", sym, bid, ask, now_s)
                                    self.engine.ingest_universe_price("okx", sym, mid, now_ms)
                                    self.venue_stats["okx"]["bbo_updates"] += 1
                                    self.venue_stats["okx"]["last_ts"] = now_s
                                    if sym in self.executor.positions:
                                        await self.executor.on_price_tick(sym, mid, exchange="okx")
                                    ref_mid, _ = self.first_seen_mid.get(sym, (mid, now_s))
                                    move_pct = abs(mid - ref_mid) / max(ref_mid, 1e-12) * 100.0
                                    if move_pct >= 0.45 and sym not in self.ohlcv_5m:
                                        movers.append((move_pct, sym))
                except Exception as exc:
                    self.venue_stats["okx"]["errors"] += 1
                    log.debug("OKX tam evren BBO uyarısı: %s", exc)

            # Spot-Perp Basis kontrolü için her 3 döngüde (12 sn) Binance Spot BBO ölçümü
            if cycle % 3 == 1:
                try:
                    async with session.get(
                        "https://data-api.binance.vision/api/v3/ticker/bookTicker", timeout=7
                    ) as sp_resp:
                        if sp_resp.status == 200:
                            for row in await sp_resp.json():
                                sym = raw_bn.get(str(row.get("symbol", "")))
                                if not sym:
                                    continue
                                sb = float(row.get("bidPrice") or 0.0)
                                sa = float(row.get("askPrice") or 0.0)
                                if sb > 0 and sa >= sb:
                                    smid = (sb + sa) / 2.0
                                    self.binance_spot_mid[sym] = smid
                                    perp = self.binance_perp_bbo.get(sym)
                                    if perp:
                                        pmid = (perp[0] + perp[1]) / 2.0
                                        self.binance_basis_offset[sym] = pmid - smid
                                        self.engine.set_spot_perp_basis(sym, pmid, smid)
                except Exception:
                    pass

            # Tam evrenden sert hareket eden yeni saf coinleri anında derin değerlendirme havuzuna ekle
            if movers and len(self.symbols) < 75:
                movers.sort(reverse=True)
                for _mv, cand_sym in movers[:2]:
                    if cand_sym not in self.symbols:
                        try:
                            await self.warmup_symbol(session, cand_sym)
                            if cand_sym in self.ohlcv_5m:
                                self.symbols.append(cand_sym)
                                log.info("Tam evren tarayıcı yeni hareketli coini terfi ettirdi: %s", cand_sym)
                        except Exception:
                            pass

            self.engine.update_universe_breadth(now_ms)
            await asyncio.sleep(4.0)

    async def _binance_single_ws(
        self, session: aiohttp.ClientSession, stream_suffix: str, label: str
    ) -> None:
        bn_syms = [s for s in self.symbols[:40] if s in self.binance_pure_symbols]
        if not bn_syms:
            return
        raw_to_sym = {_sym_to_binance_raw(s): s for s in bn_syms}
        stream_path = "/".join(f"{_sym_to_binance_raw(s).lower()}@{stream_suffix}" for s in bn_syms)
        # Denetim 2.c: Önce birincil vadeli fstream.binance.com denenir; bölgesel kısıtta spot+perpAnchor yedeğe düşer
        ws_candidates = [
            (binance_futures_ws_url(stream_suffix, stream_path), True, 3.5),
            ("wss://data-stream.binance.vision/stream?streams=" + stream_path, False, 8.0),
        ]
        if self.cfg.get("v94", {}).get("enabled", False):
            ws_candidates = ws_candidates[:1]  # Never label spot+anchor prices as executable futures BBO.
        idx = 0
        while not self.stop_Flag:
            ws_url, is_perp_ws, conn_timeout = ws_candidates[idx % len(ws_candidates)]
            short_ep = binance_futures_ws_url(stream_suffix, "").split("/stream")[0].replace("wss://", "") if is_perp_ws else "data-stream.binance.vision+perpAnchor"
            try:
                async with session.ws_connect(
                    ws_url, heartbeat=15.0, timeout=conn_timeout, receive_timeout=6.0
                ) as ws:
                    self.venue_stats["binance"][f"endpoint_{label}"] = short_ep
                    log.info("BINANCE WebSocket (%s) bağlandı: %s", label, short_ep)
                    async for msg in ws:
                        if self.stop_Flag:
                            break
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            continue
                        payload = json.loads(msg.data)
                        data = payload.get("data") or payload
                        sym = raw_to_sym.get(str(data.get("s", "")))
                        if not sym:
                            continue
                        now_s = time.time()
                        if stream_suffix == "bookTicker":
                            bid = float(data.get("b") or 0.0)
                            ask = float(data.get("a") or 0.0)
                            if bid > 0 and ask >= bid:
                                raw_mid = (bid + ask) / 2.0
                                if not is_perp_ws:
                                    self.binance_spot_mid[sym] = raw_mid
                                    perp_anchor = self.binance_perp_bbo.get(sym)
                                    if perp_anchor and (now_s - perp_anchor[2]) <= 12.0:
                                        pmid = (perp_anchor[0] + perp_anchor[1]) / 2.0
                                        offset = pmid - raw_mid
                                        self.binance_basis_offset[sym] = offset
                                        self.engine.set_spot_perp_basis(sym, pmid, raw_mid)
                                    else:
                                        offset = self.binance_basis_offset.get(sym, 0.0)
                                    bid += offset
                                    ask += offset
                                if bid > 0 and ask >= bid:
                                    self.broker.update_live_bbo("binance", sym, bid, ask, now_s)
                                    self.venue_stats["binance"]["bbo_updates"] += 1
                                    self.venue_stats["binance"]["last_ts"] = now_s
                                    self.venue_stats["binance"]["last_bbo_ts"] = now_s
                                    await self.executor.on_price_tick(
                                        sym, (bid + ask) / 2.0, exchange="binance"
                                    )
                        else:
                            px = float(data.get("p") or 0.0)
                            qty = float(data.get("q") or 0.0)
                            ts_ms = int(data.get("T") or int(now_s * 1000))
                            is_bm = bool(data.get("m", False))
                            if px > 0 and qty > 0:
                                if not is_perp_ws:
                                    px += self.binance_basis_offset.get(sym, 0.0)
                                if px > 0:
                                    self.venue_stats["binance"]["ticks"] += 1
                                    self.venue_stats["binance"]["last_ts"] = now_s
                                    self.venue_stats["binance"]["last_trade_ts"] = now_s
                                    await self.engine.on_trade(
                                        "binance", sym, px, qty, is_buyer_maker=is_bm, ts_ms=ts_ms
                                    )
            except Exception as exc:
                self.venue_stats["binance"]["errors"] += 1
                self.venue_stats["binance"][f"errors_{label}"] = self.venue_stats["binance"].get(f"errors_{label}", 0) + 1
                idx += 1
                log.info("Binance WS (%s) geçişi (%s -> yedek aday): %s", label, short_ep, exc)
                await asyncio.sleep(0.4)

    async def binance_ws_loop(self, session: aiohttp.ClientSession) -> None:
        await asyncio.gather(
            self._binance_single_ws(session, "aggTrade", "aggTrade"),
            self._binance_single_ws(session, "bookTicker", "bookTicker"),
        )

    async def okx_ws_loop(self, session: aiohttp.ClientSession) -> None:
        okx_syms = [s for s in self.symbols[:40] if s in self.okx_pure_symbols]
        if not okx_syms:
            return
        inst_to_sym = {_sym_to_okx_inst(s): s for s in okx_syms}
        args = []
        for inst in inst_to_sym:
            args.append({"channel": "trades", "instId": inst})
            args.append({"channel": "bbo-tbt", "instId": inst})

        while not self.stop_Flag:
            try:
                async with session.ws_connect(
                    "wss://ws.okx.com/ws/v5/public", heartbeat=15.0, timeout=10.0
                ) as ws:
                    for k in range(0, len(args), 30):
                        await ws.send_json({"op": "subscribe", "args": args[k : k + 30]})
                    log.info("OKX WebSocket bağlandı (%d saf kripto kanal).", len(args))
                    async for msg in ws:
                        if self.stop_Flag:
                            break
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            continue
                        if msg.data == "pong":
                            continue
                        payload = json.loads(msg.data)
                        arg = payload.get("arg") or {}
                        ch = arg.get("channel")
                        sym = inst_to_sym.get(str(arg.get("instId", "")))
                        if not sym:
                            continue
                        now_s = time.time()
                        rows = payload.get("data") or []
                        if ch == "bbo-tbt":
                            for r in rows:
                                bids = r.get("bids") or []
                                asks = r.get("asks") or []
                                if bids and asks:
                                    bid = float(bids[0][0])
                                    ask = float(asks[0][0])
                                    if bid > 0 and ask >= bid:
                                        self.broker.update_live_bbo("okx", sym, bid, ask, now_s)
                                        self.venue_stats["okx"]["bbo_updates"] += 1
                                        self.venue_stats["okx"]["last_ts"] = now_s
                                        self.venue_stats["okx"]["last_bbo_ts"] = now_s
                                        await self.executor.on_price_tick(
                                            sym, (bid + ask) / 2.0, exchange="okx"
                                        )
                        elif ch == "trades":
                            mult = float(self.okx_ct_val.get(sym, 1.0))
                            for r in rows:
                                px = float(r.get("px") or 0.0)
                                sz = float(r.get("sz") or 0.0) * mult
                                side_str = str(r.get("side") or "buy").lower()
                                ts_ms = int(r.get("ts") or int(now_s * 1000))
                                if px > 0 and sz > 0:
                                    is_bm = side_str == "sell"
                                    self.venue_stats["okx"]["ticks"] += 1
                                    self.venue_stats["okx"]["last_ts"] = now_s
                                    self.venue_stats["okx"]["last_trade_ts"] = now_s
                                    await self.engine.on_trade(
                                        "okx", sym, px, sz, is_buyer_maker=is_bm, ts_ms=ts_ms
                                    )
            except Exception as exc:
                self.venue_stats["okx"]["errors"] += 1
                log.warning("OKX WS yeniden bağlanıyor: %s", exc)
                await asyncio.sleep(1.0)

    async def candle_refresh_loop(self, session: aiohttp.ClientSession) -> None:
        while not self.stop_Flag:
            await asyncio.sleep(20.0)
            active_list = list(dict.fromkeys([*self.executor.positions.keys(), *self.symbols]))
            for sym in active_list:
                if self.stop_Flag:
                    break
                try:
                    c1m, c5m = await asyncio.gather(
                        self._fetch_candles_best_source(session, sym, "1m", 6),
                        self._fetch_candles_best_source(session, sym, "5m", 600),
                    )
                    if c1m:
                        self._ingest_1m_rows(sym, c1m)
                    if c5m:
                        self.ohlcv_5m[sym] = self._rows_to_df(c5m)
                except Exception:
                    continue

    async def open_positions_fast_quote_loop(self, session: aiohttp.ClientSession) -> None:
        """Açık olan tüm pozisyonlar (ilk-40 WS dışındaki dinamik terfi pariteleri dahil)
        için her 1.3 sn'de taze BBO çekerek çapraz-marjin (ortak kasa) kotasyon yaşını
        daima <5 sn altında tutar ve stop/kâr kilidini milisaniye hassasiyetle çalıştırır."""
        while not self.stop_Flag:
            await asyncio.sleep(1.3)
            if self.stop_Flag:
                break
            open_items = list(self.executor.positions.items())
            if not open_items:
                continue
            now_mono = time.monotonic()
            now_s = time.time()
            for sym, pos in open_items:
                last_mono = self.executor._price_receipt_mono.get(sym)
                if last_mono is not None and (now_mono - last_mono) < 1.1:
                    continue
                ex_k = str(getattr(pos, "exchange", "binance") or "binance").lower()
                # Önce bellekte son 1.5 sn içinde güncellenmiş taze BBO varsa onu kullan
                fresh_bbo = self.broker.get_fresh_bbo(ex_k, sym, max_age_sec=1.5)
                if fresh_bbo:
                    mid = (fresh_bbo[0] + fresh_bbo[1]) / 2.0
                    await self.executor.on_price_tick(sym, mid, exchange=ex_k)
                    continue
                base_coin = sym.split("/")[0].upper()
                try:
                    if ex_k == "binance":
                        async with session.get(
                            f"https://www.binance.com/fapi/v1/ticker/bookTicker?symbol={base_coin}USDT",
                            timeout=2.2,
                        ) as r_bbo:
                            if r_bbo.status == 200:
                                jb = await r_bbo.json()
                                lb = float(jb.get("bidPrice") or 0.0)
                                la = float(jb.get("askPrice") or 0.0)
                                if lb > 0 and la >= lb:
                                    self.broker.update_live_bbo("binance", sym, lb, la, now_s)
                                    await self.executor.on_price_tick(sym, (lb + la) / 2.0, exchange="binance")
                    else:
                        async with session.get(
                            f"https://www.okx.com/api/v5/market/ticker?instId={base_coin}-USDT-SWAP",
                            timeout=2.2,
                        ) as r_bbo:
                            if r_bbo.status == 200:
                                rows = (await r_bbo.json()).get("data") or []
                                if rows:
                                    lb = float(rows[0].get("bidPx") or 0.0)
                                    la = float(rows[0].get("askPx") or 0.0)
                                    if lb > 0 and la >= lb:
                                        self.broker.update_live_bbo("okx", sym, lb, la, now_s)
                                        await self.executor.on_price_tick(sym, (lb + la) / 2.0, exchange="okx")
                except Exception:
                    continue

    async def strategy_eval_loop(self) -> None:
        while not self.stop_Flag:
            now_ms = int(time.time() * 1000)
            try:
                self.store.acquire_writer_lease("kripto-bot-v94-main", ttl_sec=120.0)
            except Exception:
                pass
            for leader in ("BTC/USDT", "ETH/USDT"):
                leader_df = self.ohlcv_5m.get(leader)
                if leader_df is not None:
                    self.engine.global_anchor.update_leader(leader, leader_df, now_ms=now_ms)
            returns_15m = [
                (float(df["close"].iloc[-1]) / float(df["close"].iloc[-4]) - 1) * 100
                for df in self.ohlcv_5m.values() if len(df) >= 4 and float(df["close"].iloc[-4]) > 0
            ]
            self.engine.global_anchor.update_directional_breadth_from_returns(returns_15m)
            eval_list = list(dict.fromkeys([*self.executor.positions.keys(), *self.symbols]))
            for sym in eval_list:
                if self.stop_Flag:
                    break
                try:
                    df5 = self.ohlcv_5m.get(sym)
                    if df5 is None or len(df5) < 30:
                        continue
                    bn_bbo = self.broker.get_fresh_bbo("binance", sym, max_age_sec=20.0)
                    ok_bbo = self.broker.get_fresh_bbo("okx", sym, max_age_sec=20.0)
                    if not bn_bbo and not ok_bbo:
                        continue

                    best_ex, _books = self.broker.select_best_exchange(
                        sym, "LONG", self.executor.positions
                    )
                    ref_bbo = bn_bbo if (best_ex == "binance" and bn_bbo) else (ok_bbo or bn_bbo)
                    live_px = (ref_bbo[0] + ref_bbo[1]) / 2.0
                    live_spread_pct = (ref_bbo[1] - ref_bbo[0]) / live_px * 100.0 if live_px > 0 else 0.02

                    # Closed bars are immutable. Live quote is an independent execution/valuation input.
                    df_live = df5
                    self.engine.v94_frames = self.ohlcv_5m

                    res = await self.engine.evaluate_and_route(
                        best_ex,
                        sym,
                        df_live,
                        ohlcv_15m=self.ohlcv_15m.get(sym),
                        ohlcv_1h=self.ohlcv_1h.get(sym),
                        spread_pct=live_spread_pct,
                        funding_rate=self.funding_rates.get(sym, 0.0),
                        now_ms=now_ms,
                        allow_new_entries=self.allow_new_entries,
                        mark_price=live_px,
                    )
                    self.board_decisions[sym] = res
                    with self.jsonl_path.open("a", encoding="utf-8") as fh:
                        fh.write(
                            json.dumps(
                                {
                                    "ts": _utc_now_iso(),
                                    "symbol": sym,
                                    "best_venue": best_ex,
                                    "signal": res.get("signal"),
                                    "routed": res.get("routed"),
                                    "decision_bar_open_ms": int(df5["ts"].iloc[-1]),
                                    "features": res.get("features"),
                                    "reason": res.get("reason"),
                                    "regime": (res.get("regime") or {}).get("macro_regime"),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except Exception as eval_exc:
                    log.warning("Sembol değerlendirme uyarısı (%s): %s", sym, eval_exc)
                    continue
            self.engine.sync_closed_trade_feedback()
            await asyncio.sleep(3.5)

    def build_state_payload(self) -> dict[str, Any]:
        now_s = time.time()
        paper = self.broker.paper
        trades = self.store.get_trades(limit=500)
        trades_chrono = list(reversed(trades))

        open_list = []
        upnl_total = 0.0
        for sym, pos in list(self.executor.positions.items()):
            ex_k = str(getattr(pos, "exchange", "binance") or "binance").lower()
            bbo = self.broker.get_fresh_bbo(ex_k, sym, max_age_sec=30.0)
            mark = (
                (bbo[0] + bbo[1]) / 2.0
                if bbo
                else getattr(self.executor, "last_venue_prices", {}).get(
                    (ex_k, sym), self.executor.last_prices.get(sym, pos.entry)
                )
            )
            upnl = float(self.risk.pnl_usdt(pos, mark))
            upnl_total += upnl
            open_list.append(
                {
                    "symbol": sym,
                    "exchange": ex_k,
                    "side": pos.side,
                    "margin_usdt": float(getattr(pos, "margin_usdt", 50.0)),
                    "leverage": int(getattr(pos, "leverage", 10)),
                    "entry": float(pos.entry),
                    "mark": float(mark),
                    "stop": float(pos.stop),
                    "mfe": float(getattr(pos, "mfe_usdt", 0.0)),
                    "upnl": upnl,
                }
            )

        closed_rows = []
        gross_closed = 0.0
        net_closed = 0.0
        wins = 0
        for t in trades_chrono:
            gross_v = float(t.get("pnl_usdt", 0.0) or 0.0)
            fee_v = float(
                t.get("fee_usdt")
                if t.get("fee_usdt") is not None
                else ((t.get("entry_fee_usdt") or 0.0) + (t.get("exit_fee_usdt") or 0.0))
            )
            net_v = (
                float(t["net_pnl_usdt"])
                if t.get("net_pnl_usdt") is not None
                else (gross_v - fee_v)
            )
            entry_px = float(t.get("entry_price") or t.get("entry") or 0.0)
            closed_ts = t.get("ts")
            closed_at_str = str(t.get("closed_at") or "")
            if not closed_at_str and closed_ts:
                closed_at_str = datetime.fromtimestamp(float(closed_ts), tz=timezone.utc).strftime("%H:%M:%S")
            gross_closed += gross_v
            net_closed += net_v
            if net_v > 0:
                wins += 1
            closed_rows.append(
                {
                    "symbol": t.get("symbol"),
                    "exchange": str(t.get("exchange") or "binance").lower(),
                    "side": t.get("side"),
                    "entry_price": entry_px,
                    "exit_price": float(t.get("exit_price", 0.0)),
                    "gross_pnl": gross_v,
                    "fee_usdt": fee_v,
                    "pnl_usdt": net_v,
                    "reason": t.get("reason", ""),
                    "closed_at": closed_at_str,
                }
            )

        closed_count = len(closed_rows)
        total_fees = float(paper.total_fees_usdt)

        venue_counts = {"binance": 0, "okx": 0}
        for t in trades_chrono:
            vk = str(t.get("exchange") or "binance").lower()
            venue_counts[vk] = venue_counts.get(vk, 0) + 1
        for p in open_list:
            vk = str(p.get("exchange") or "binance").lower()
            venue_counts[vk] = venue_counts.get(vk, 0) + 1

        market_board = []
        bn_fresh_cnt = 0
        ok_fresh_cnt = 0
        for sym in self.symbols[:35]:
            bn_bbo = self.broker.get_fresh_bbo("binance", sym, max_age_sec=25.0)
            ok_bbo = self.broker.get_fresh_bbo("okx", sym, max_age_sec=25.0)
            if bn_bbo:
                bn_fresh_cnt += 1
            if ok_bbo:
                ok_fresh_cnt += 1
            bn_mid = (bn_bbo[0] + bn_bbo[1]) / 2.0 if bn_bbo else 0.0
            ok_mid = (ok_bbo[0] + ok_bbo[1]) / 2.0 if ok_bbo else 0.0
            bn_sp_bps = ((bn_bbo[1] - bn_bbo[0]) / bn_mid * 10_000.0) if bn_mid > 0 else 0.0
            ok_sp_bps = ((ok_bbo[1] - ok_bbo[0]) / ok_mid * 10_000.0) if ok_mid > 0 else 0.0
            basis_bps = float(self.engine.spot_perp_basis_bps.get(sym, 0.0))

            dec = self.board_decisions.get(sym) or {}
            comb = dec.get("combined") or {}
            tac_rep = dec.get("ten_agent_audit") or {}
            votes_str = (
                f"{tac_rep.get('consensus_votes')}/10"
                if tac_rep.get("consensus_votes") is not None
                else "-"
            )
            sig_hint = str(dec.get("raw_signal") or dec.get("signal") or "LONG")
            best_v, _ = self.broker.select_best_exchange(
                sym, sig_hint if sig_hint in ("LONG", "SHORT") else "LONG", self.executor.positions
            )
            reg_obj = dec.get("regime") or {}
            reg_str = (
                reg_obj.get("macro_regime")
                or reg_obj.get("confirmed_regime")
                or reg_obj.get("regime")
                or "-"
            )
            market_board.append(
                {
                    "symbol": sym,
                    "bn_bid": bn_bbo[0] if bn_bbo else 0.0,
                    "bn_ask": bn_bbo[1] if bn_bbo else 0.0,
                    "bn_spread_bps": bn_sp_bps,
                    "okx_bid": ok_bbo[0] if ok_bbo else 0.0,
                    "okx_ask": ok_bbo[1] if ok_bbo else 0.0,
                    "okx_spread_bps": ok_sp_bps,
                    "basis_bps": basis_bps,
                    "best_venue": best_v,
                    "regime": reg_str,
                    "ind_score": float(comb.get("ind", comb.get("ind_score", 0.0))),
                    "flow_score": float((dec.get("flow") or {}).get("score", 0.0)),
                    "combined": float(comb.get("total", 0.0)),
                    "ten_agent_votes": votes_str,
                    "last_signal": str(dec.get("signal") or "BEKLE"),
                    "reason": str(dec.get("reason") or "")[:48],
                }
            )

        analytics = self.engine.analytics_snapshot()
        bn_feed = venue_feed_status(self.venue_stats["binance"], now_s, started_at=self.start_ts)
        ok_feed = venue_feed_status(self.venue_stats["okx"], now_s, started_at=self.start_ts)
        feed_alarms = [f"{v.upper()}_{a}" for v, fs in (("binance", bn_feed), ("okx", ok_feed)) for a in fs["alarms"]]
        if feed_alarms:
            op_h = dict(analytics.get("operational_health") or {})
            op_h["alarms"] = list(op_h.get("alarms") or []) + feed_alarms
            op_h["healthy"] = False
            analytics = {**analytics, "operational_health": op_h}
        equity = float(paper.balance) + upnl_total
        return {
            "product_version": self.product_version,
            "product_label": self.product_label,
            "phase": self.phase,
            "elapsed_sec": now_s - self.start_ts,
            "drain_elapsed_sec": self.drain_elapsed_sec,
            "run_completion": {
                "active_duration_target_sec": self.duration_sec,
                "active_window_completed": bool(getattr(self, "active_window_completed", False)),
                "stop_reason": getattr(self, "run_stop_reason", None),
                "completed": self.phase == "COMPLETED",
                "scope": "time protocol only; not trade-cycle or profitability approval",
            },
            "evaluation_telemetry": evaluation_telemetry_snapshot(self.engine),
            "balance": float(paper.balance),
            "starting_balance": float(paper.start_balance),
            "equity": equity,
            "net_pnl": equity - float(paper.start_balance),
            "closed_net_pnl": net_closed,
            "gross_pnl": gross_closed,
            "total_fees": total_fees,
            "total_funding": float(paper.total_funding_usdt),
            "closed_count": closed_count,
            "wins": wins,
            "losses": closed_count - wins,
            "win_rate": (wins / closed_count * 100.0) if closed_count else 0.0,
            "margin_mode": str(self.cfg.get("risk", {}).get("marj_modu", "cross")),
            "per_trade_margin_usdt": float(self.cfg.get("boyutlandirma", {}).get("sabit_marj_usdt", 50.0)),
            "leverage": int(self.cfg.get("genel", {}).get("kaldıraç", 10)),
            "hard_stop_usdt": -40.0,
            "max_positions": int(self.cfg.get("risk", {}).get("max_pozisyon", 1000)),
            "unrealized_pnl": upnl_total,
            "breadth_ratio": float(getattr(self.detector, "genislik_oran", 0.0)),
            "universe_counts": {
                "union_pure": len(self.universe_all_symbols),
                "binance_pure": len(self.binance_pure_symbols),
                "okx_pure": len(self.okx_pure_symbols),
                "active_deep_pool": len(self.symbols),
                "excluded_non_crypto": dict(self.excluded_non_crypto_count),
            },
            "v94": {
                "closed_candle_core": bool(self.cfg.get("v94", {}).get("enabled", False)),
                "policy": self.cfg.get("v94", {}).get("policy"),
                "entry_rejections": dict(getattr(getattr(self.engine,"v94_router",None),"rejections",{})),
                "entry_rejections_includes_retry_suppression": True,
                "open_stop_risk_usdt": sum(max(0.0,(p.entry-p.stop) if p.side=="LONG" else (p.stop-p.entry))*p.qty for p in self.executor.positions.values()),
                "active_duration_target_sec": self.duration_sec,
                "real_money_approved": False,
            },
            "engine_metrics": dict(self.engine.metrics),
            "analytics": analytics,
            "venue_trade_counts": venue_counts,
            "venues": {
                "binance": {
                    "healthy": bn_feed["healthy"],
                    "bbo_healthy": bn_feed["bbo_healthy"],
                    "trade_tape_healthy": bn_feed["trade_tape_healthy"],
                    "fresh_pairs": bn_fresh_cnt,
                    **self.venue_stats["binance"],
                },
                "okx": {
                    "healthy": ok_feed["healthy"],
                    "bbo_healthy": ok_feed["bbo_healthy"],
                    "trade_tape_healthy": ok_feed["trade_tape_healthy"],
                    "fresh_pairs": ok_fresh_cnt,
                    **self.venue_stats["okx"],
                },
            },
            "open_positions": open_list,
            "closed_trades": closed_rows,
            "market_board": market_board,
        }

    async def start_web_server(self) -> web.AppRunner:
        app = web.Application()

        async def _index(_req: web.Request) -> web.Response:
            return web.Response(text=DASHBOARD_HTML, content_type="text/html")

        async def _api_state(_req: web.Request) -> web.Response:
            return web.json_response(self.build_state_payload())

        async def _health(_req: web.Request) -> web.Response:
            st = self.build_state_payload()
            op = st["analytics"]["operational_health"]
            status_code = 200 if op["healthy"] else 503
            return web.json_response(
                {
                    "status": "ok" if op["healthy"] else "degraded",
                    "version": self.product_version,
                    "binance_healthy": st["venues"]["binance"]["healthy"],
                    "okx_healthy": st["venues"]["okx"]["healthy"],
                    "ledger_reconciled": op["ledger_reconciled"],
                    "ledger_status": op.get("ledger_status", "UNKNOWN"),
                    "ledger_reason": op.get("ledger_reason"),
                    "pending_operations": op.get("pending_operations", []),
                    "warnings": op.get("warnings", []),
                    "feed_lag_sec": op["feed_lag_sec"],
                    "alarms": op["alarms"],
                    "open_positions": len(st["open_positions"]),
                },
                status=status_code,
            )

        app.router.add_get("/", _index)
        app.router.add_get("/api/state", _api_state)
        app.router.add_get("/health", _health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        log.info("Canlı Çift Borsa Web Paneli yayında: http://0.0.0.0:%d", self.port)
        return runner

    async def run(self) -> dict[str, Any]:
        web_runner = await self.start_web_server()
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            self.symbols = await self.discover_full_pure_crypto_universe(session)
            await self.warmup_all(session)

            ws_tasks = [
                asyncio.create_task(self.full_universe_bbo_and_scanner_loop(session)),
                asyncio.create_task(self.open_positions_fast_quote_loop(session)),
                asyncio.create_task(self.binance_ws_loop(session)),
                asyncio.create_task(self.okx_ws_loop(session)),
                asyncio.create_task(self.candle_refresh_loop(session)),
            ]
            await asyncio.sleep(5.0)
            self.start_ts = time.time()
            self.phase = "ACTIVE"
            self.active_window_completed = False
            self.run_stop_reason = None
            eval_task = asyncio.create_task(self.strategy_eval_loop())
            bg_tasks = [*ws_tasks, eval_task]

            try:
                if self.duration_sec <= 0:
                    while not self.stop_Flag:
                        await asyncio.sleep(1.0)
                else:
                    while not self.stop_Flag and (time.time() - self.start_ts) < self.duration_sec:
                        await asyncio.sleep(1.0)

                    self.active_window_completed = (time.time() - self.start_ts) >= self.duration_sec
                    self.allow_new_entries = False
                    self.phase = "DRAIN"
                    drain_t0 = time.time()
                    if self.active_window_completed:
                        log.info(
                            "Aktif giriş penceresi (%.0fs) tamamlandı. Açık %d pozisyon doğal kapanışa bırakıldı.",
                            self.duration_sec, len(self.executor.positions),
                        )
                    else:
                        log.info("Aktif giriş penceresi KESİLDİ | Geçen=%.3fs | Hedef=%.0fs",
                                 time.time() - self.start_ts, self.duration_sec)
                    while (
                        not self.stop_Flag
                        and len(self.executor.positions) > 0
                        and (time.time() - drain_t0) < self.max_drain_sec
                    ):
                        self.drain_elapsed_sec = time.time() - drain_t0
                        await asyncio.sleep(1.0)
                    self.drain_elapsed_sec = time.time() - drain_t0
                    self.phase = "COMPLETED" if self.active_window_completed and not self.stop_Flag else "INTERRUPTED"
                    self.run_stop_reason = (
                        "stop_requested_before_active_target" if not self.active_window_completed else
                        "stop_requested_during_or_at_end_of_active_window" if self.stop_Flag else
                        "drain_limit_with_open_positions" if self.executor.positions else "duration_target_reached"
                    )
                    self.engine.sync_closed_trade_feedback()
                    done_summary = self.build_state_payload()
                    self.summary_path.write_text(
                        json.dumps(done_summary, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    log.info(
                        "%s | Kapanan=%d | Acik=%d | Brüt=$%+.4f | Net=$%+.4f | Evren=%d",
                        "CANLI_TEST_TAMAMLANDI" if self.phase == "COMPLETED" else "CANLI_TEST_KESILDI",
                        done_summary["closed_count"],
                        len(done_summary["open_positions"]),
                        done_summary["gross_pnl"],
                        done_summary["net_pnl"],
                        done_summary["universe_counts"]["union_pure"],
                    )
                    if self.keep_panel_alive:
                        while not self.stop_Flag:
                            await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                self.phase = "INTERRUPTED"
                self.run_stop_reason = "task_cancelled"
                raise
            except Exception as exc:
                self.phase = "FAILED"
                self.run_stop_reason = "exception:" + type(exc).__name__
                raise
            finally:
                if self.phase not in ("COMPLETED", "INTERRUPTED", "FAILED"):
                    self.phase = "INTERRUPTED"
                    self.run_stop_reason = "stop_requested_indefinite_run" if self.duration_sec <= 0 else "shutdown_without_completion"
                self.stop_Flag = True
                for t in bg_tasks:
                    t.cancel()
                await asyncio.gather(*bg_tasks, return_exceptions=True)
                self.engine.sync_closed_trade_feedback()
                summary = self.build_state_payload()
                self.summary_path.write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                telemetry = summary.get("evaluation_telemetry", {})
                log.info("KOSU_SONUCU | Durum=%s | Neden=%s | ToplamDegerlendirme=%d | TekrarKorumasi=%d | TekrarDisiCagri=%d",
                         self.phase, self.run_stop_reason,
                         telemetry.get("evaluation_calls_total", 0), telemetry.get("retry_suppressed_total", 0),
                         telemetry.get("non_retry_evaluation_calls", 0))
                await web_runner.cleanup()
                await self.broker.close()
                if hasattr(self.store, "close"):
                    self.store.close()
        return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kripto Bot v9.4 — Tam Vadeli Evren Canlı Motoru")
    parser.add_argument("--config", type=str, default=str(CANONICAL_CONFIG_PATH))
    parser.add_argument("--duration-sec", type=float, default=0.0, help="0 = kesintisiz çalışma")
    parser.add_argument("--max-drain-sec", type=float, default=600.0)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--report-prefix", type=str, default=None)
    parser.add_argument("--keep-panel-alive", action="store_true")
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    cfg = load_config(args.config)
    runner = DualVenueLiveRunner(
        cfg,
        duration_sec=args.duration_sec,
        max_drain_sec=args.max_drain_sec,
        port=args.port,
        report_prefix=args.report_prefix,
        keep_panel_alive=args.keep_panel_alive,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, setattr, runner, "stop_Flag", True)
        except NotImplementedError:
            pass
    return await runner.run()


if __name__ == "__main__":
    asyncio.run(async_main())
