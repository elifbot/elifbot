#!/usr/bin/env python3
"""
panel.py — CANLI İZLEME PANELİ (WebSocket modu)

    PANEL_PORT=8000 python3 panel.py

Okuduğu dosyalar (bot bunları kendisi yazar):
    logs/ws_durum.json   — her saniye yazılan canlı durum (tek doğru kaynak)
    logs/ws_olay.csv     — tespit edilen her ani hareket
    live_trades.csv      — kapanan işlemler

Sadece okur, bota hiçbir şekilde müdahale etmez.
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TABAN = os.path.dirname(os.path.abspath(__file__))
DURUM = os.path.join(TABAN, "logs", "ws_durum.json")
OLAY = os.path.join(TABAN, "logs", "ws_olay.csv")
ISLEM = os.path.join(TABAN, "live_trades.csv")
PORT = int(os.environ.get("PANEL_PORT", "8000"))


# ---------------------------------------------------------------- veri
def _json_yol(yol: str) -> dict:
    try:
        with open(yol, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _csv_son(yol: str, adet: int = 25) -> list[dict]:
    try:
        with open(yol, encoding="utf-8", newline="") as fh:
            satirlar = list(csv.DictReader(fh))
        return satirlar[-adet:][::-1]
    except Exception:
        return []


def veri() -> dict:
    d = _json_yol(DURUM)
    if not d:
        return {
            "calisiyor": False, "bos": True,
            "simdi": datetime.now().strftime("%H:%M:%S"),
            "sure_sn": 0, "bakiye": 0, "acik_pozisyon": 0,
            "acik_pozisyonlar": [], "kapanan_islem": 0, "toplam_pnl": 0,
            "sinyal": 0, "acilan": 0, "reddedilen": 0,
            "okx": {}, "binance": {}, "izlenen_sembol": 0,
            "hacim_hazir": 0, "son_sinyaller": [],
        }
    d["bos"] = False
    d["olaylar"] = _csv_son(OLAY, 20)
    d["kapananlar"] = _csv_son(ISLEM, 15)
    try:
        d["dosya_yasi_sn"] = int(time.time() - os.path.getmtime(DURUM))
    except Exception:
        d["dosya_yasi_sn"] = 999
    return d


# ---------------------------------------------------------------- HTML
HTML = r"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canlı Tarama Paneli</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b0e14;color:#d7dce5;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:14px}
h1{font-size:15px;font-weight:600;letter-spacing:.5px;display:flex;align-items:center;gap:9px}
.dot{width:8px;height:8px;border-radius:50%;background:#f04a4a;box-shadow:0 0 8px #f04a4a}
.dot.on{background:#22c55e;box-shadow:0 0 8px #22c55e;animation:p 1.6s infinite}
@keyframes p{50%{opacity:.35}}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;
  padding-bottom:11px;border-bottom:1px solid #1d2330;flex-wrap:wrap;gap:8px}
.tag{background:#151b26;border:1px solid #232b3a;border-radius:5px;padding:3px 9px;
  font-size:11px;color:#8b95a7}
.tag b{color:#d7dce5}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:9px;margin-bottom:13px}
.card{background:#111722;border:1px solid #1d2330;border-radius:8px;padding:10px 12px}
.card .l{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:#6b7688;margin-bottom:3px}
.card .v{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
.card .s{font-size:10px;color:#5d6878;margin-top:2px}
.g{color:#22c55e}.r{color:#ef4444}.y{color:#eab308}.b{color:#38bdf8}.d{color:#6b7688}
section{background:#111722;border:1px solid #1d2330;border-radius:8px;margin-bottom:12px;overflow:hidden}
section>h2{font-size:10.5px;text-transform:uppercase;letter-spacing:.9px;color:#7b8698;
  padding:9px 12px;border-bottom:1px solid #1d2330;background:#0e131c;font-weight:600;
  display:flex;justify-content:space-between}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th{text-align:left;padding:6px 10px;color:#5d6878;font-weight:500;font-size:10px;
  text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #1a2029}
td{padding:5px 10px;border-bottom:1px solid #161c26;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
tr:hover td{background:#151c28}
.badge{padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600}
.long{background:#0d3320;color:#4ade80}.short{background:#3b1418;color:#f87171}
.bos{padding:16px;text-align:center;color:#4b5563;font-size:11px}
.scroll{max-height:250px;overflow-y:auto}
.scroll::-webkit-scrollbar{width:6px}
.scroll::-webkit-scrollbar-thumb{background:#232b3a;border-radius:3px}
footer{color:#3f4855;font-size:10px;text-align:center;margin-top:14px;line-height:1.7}
.right{text-align:right}
</style></head><body>

<header>
  <h1><span class="dot" id="durumNokta"></span> CANLI TARAMA — <span id="mod">WEBSOCKET</span></h1>
  <div style="display:flex;gap:6px;flex-wrap:wrap">
    <span class="tag">süre <b id="sure">—</b></span>
    <span class="tag">saat <b id="saat">—</b></span>
    <span class="tag" id="bayatTag" style="display:none;color:#eab308">veri bayat</span>
  </div>
</header>

<div class="grid">
  <div class="card"><div class="l">Bakiye</div><div class="v" id="bakiye">—</div><div class="s" id="bakiyeAlt">USDT</div></div>
  <div class="card"><div class="l">Gerçekleşen PnL</div><div class="v" id="pnl">—</div><div class="s" id="pnlAlt">kapalı işlemler</div></div>
  <div class="card"><div class="l">Açık Pozisyon</div><div class="v" id="acik">—</div><div class="s" id="acikAlt">—</div></div>
  <div class="card"><div class="l">Kapanan İşlem</div><div class="v" id="kapanan">—</div><div class="s">tamamlanan</div></div>
  <div class="card"><div class="l">Sinyal</div><div class="v b" id="sinyal">—</div><div class="s" id="sinyalAlt">—</div></div>
  <div class="card"><div class="l">İzlenen Sembol</div><div class="v" id="sembol">—</div><div class="s" id="sembolAlt">—</div></div>
  <div class="card"><div class="l">Mesaj / sn</div><div class="v y" id="msgsn">—</div><div class="s" id="msgsnAlt">okx + binance</div></div>
  <div class="card"><div class="l">Gecikme</div><div class="v" id="gecikme">—</div><div class="s">tik → sinyal</div></div>
</div>

<section>
  <h2>Açık Pozisyonlar <span id="acikSayi" class="d"></span></h2>
  <div id="acikTbl"></div>
</section>

<section>
  <h2>Sinyal Akışı <span class="d">son 20</span></h2>
  <div class="scroll"><div id="sinyalTbl"></div></div>
</section>

<section>
  <h2>Kapanan İşlemler <span class="d">son 15</span></h2>
  <div class="scroll"><div id="islemTbl"></div></div>
</section>

<section>
  <h2>Bağlantı Durumu</h2>
  <div style="padding:10px 12px;font-size:11.5px;line-height:1.9" id="baglanti"></div>
</section>

<footer>
  PAPER MODE · gerçek emir gönderilmez · funding hariç<br>
  OKX: WebSocket push (~100 ms) · Binance: REST (~600 ms) — WebSocket bölgesel engelli<br>
  Kripto USDT-SWAP evreni · hisse tokeni ve emtia hariç
</footer>

<script>
const F = (n, d=2) => (n===null||n===undefined||isNaN(n)) ? '—' :
  Number(n).toLocaleString('tr-TR',{minimumFractionDigits:d,maximumFractionDigits:d});
const isaret = n => n>0 ? 'g' : n<0 ? 'r' : 'd';

function tbl(kolonlar, satirlar) {
  if (!satirlar.length) return '<div class="bos">henüz kayıt yok</div>';
  let h = '<table><tr>' + kolonlar.map(k=>`<th${k.sag?' class="right"':''}>${k.b}</th>`).join('') + '</tr>';
  for (const s of satirlar) {
    h += '<tr>' + kolonlar.map(k=>`<td${k.sag?' class="right"':''}>${k.f(s)}</td>`).join('') + '</tr>';
  }
  return h + '</table>';
}

function ciz(d) {
  const canli = d.calisiyor && !d.bos;
  document.getElementById('durumNokta').className = 'dot' + (canli ? ' on' : '');
  document.getElementById('mod').textContent = d.mod === 'websocket' ? 'WEBSOCKET' : 'REST';

  const sn = d.sure_sn||0;
  document.getElementById('sure').textContent =
    `${Math.floor(sn/60)} dk ${String(sn%60).padStart(2,'0')} sn`;
  document.getElementById('saat').textContent = d.simdi || '—';

  document.getElementById('bayatTag').style.display = (d.dosya_yasi_sn > 6) ? '' : 'none';

  document.getElementById('bakiye').textContent = F(d.bakiye);
  const delta = (d.bakiye||0) - (d.baslangic_bakiye||1000);
  const bAlt = document.getElementById('bakiyeAlt');
  bAlt.textContent = (delta>=0?'+':'') + F(delta,2) + ' USDT';
  bAlt.className = 's ' + isaret(delta);

  const p = d.toplam_pnl||0;
  document.getElementById('pnl').textContent = (p>=0?'+':'') + F(p,2);
  document.getElementById('pnl').className = 'v ' + isaret(p);

  document.getElementById('acik').textContent = d.acik_pozisyon||0;
  document.getElementById('acikAlt').textContent = `marj ${F((d.acik_pozisyon||0)*100,0)} USDT`;

  document.getElementById('kapanan').textContent = d.kapanan_islem||0;
  document.getElementById('sinyal').textContent = d.sinyal||0;
  document.getElementById('sinyalAlt').textContent =
    `${d.acilan||0} açıldı · ${d.reddedilen||0} reddedildi`;

  document.getElementById('sembol').textContent = d.izlenen_sembol||0;
  document.getElementById('sembolAlt').textContent = `${d.hacim_hazir||0} hacim hazır`;

  const msOkx = (d.okx||{}).msg_sn || 0, msBn = (d.binance||{}).msg_sn || 0;
  document.getElementById('msgsn').textContent = F(msOkx + msBn, 0);
  document.getElementById('msgsnAlt').textContent = `okx ${F(msOkx,0)} · binance ${F(msBn,0)}`;
  const g = d.son_gecikme_ms;
  document.getElementById('gecikme').textContent = g==null ? '—' : Math.max(0,g-56)+' ms';
  document.getElementById('gecikme').className = 'v ' + (g==null?'d':(Math.max(0,g-56)<300?'g':'y'));

  // açık pozisyonlar
  const ap = d.acik_pozisyonlar || [];
  document.getElementById('acikSayi').textContent = ap.length ? `${ap.length} adet` : '';
  document.getElementById('acikTbl').innerHTML = tbl([
    {b:'Sembol', f:r => r.sembol},
    {b:'Yön', f:r => `<span class="badge ${r.yon==='LONG'?'long':'short'}">${r.yon}</span>`},
    {b:'Giriş', sag:1, f:r => F(r.giris,6)},
    {b:'Son', sag:1, f:r => F(r.fiyat,6)},
    {b:'PnL', sag:1, f:r => `<span class="${isaret(r.pnl)}">${(r.pnl>=0?'+':'')+F(r.pnl,2)}</span>`},
  ], ap);

  // sinyal akışı
  document.getElementById('sinyalTbl').innerHTML = tbl([
    {b:'Saat', f:r => r.ts||'—'},
    {b:'Sembol', f:r => (r.symbol||'').replace('-USDT-SWAP','')},
    {b:'Yön', f:r => `<span class="badge ${r.yon==='LONG'?'long':'short'}">${r.yon||''}</span>`},
    {b:'Hareket', sag:1, f:r => `<span class="${isaret(r.ret)}">${(r.ret>=0?'+':'')+F(r.ret,2)}%</span>`},
    {b:'rvol', sag:1, f:r => F(r.rvol,1)+'×'},
    {b:'Gecikme', sag:1, f:r => r.gecikme_ms==null?'—':Math.max(0,r.gecikme_ms-56)+'ms'},
  ], (d.son_sinyaller||[]).slice().reverse());

  // kapanan işlemler
  document.getElementById('islemTbl').innerHTML = tbl([
    {b:'Sembol', f:r => (r.symbol||'').replace('-USDT-SWAP','')},
    {b:'Yön', f:r => `<span class="badge ${r.side==='LONG'?'long':'short'}">${r.side||''}</span>`},
    {b:'Giriş', sag:1, f:r => F(r.entry_price,6)},
    {b:'Çıkış', sag:1, f:r => F(r.exit_price,6)},
    {b:'PnL', sag:1, f:r => {
        const v = parseFloat(r.realized_pnl||0);
        return `<span class="${isaret(v)}">${(v>=0?'+':'')+F(v,2)}</span>`;}},
  ], d.kapananlar||[]);

  // bağlantı
  const o = d.okx||{}, bn = d.binance||{};
  document.getElementById('baglanti').innerHTML =
    `OKX &nbsp;· WebSocket · bağlantı <b>${o.baglanti||0}</b> · sembol <b>${o.sembol||0}</b> · ` +
    `toplam mesaj <b>${F(o.tik,0)}</b><br>` +
    `Binance &nbsp;· ${(bn.mod||'rest').toUpperCase()} · sembol <b>${bn.sembol||0}</b> · ` +
    `toplam mesaj <b>${F(bn.tik,0)}</b> · ` +
    `<b class="${bn.aktif?'g':'r'}">${bn.aktif?'çalışıyor':'veri yok'}</b>` +
    (bn.hata?` <span class="d">(${bn.hata})</span>`:'');
}

async function yenile() {
  try {
    const r = await fetch('/api', {cache:'no-store'});
    ciz(await r.json());
  } catch(e) {
    document.getElementById('durumNokta').className = 'dot';
  }
}
yenile();
setInterval(yenile, 1500);
</script>
</body></html>
"""


class Isleyici(BaseHTTPRequestHandler):
    def do_GET(self):                                     # noqa: N802
        if self.path.startswith("/api"):
            govde = json.dumps(veri(), ensure_ascii=False, default=str).encode()
            tur = "application/json"
        elif self.path.startswith("/"):
            govde = HTML.encode()
            tur = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(govde)

    def log_message(self, *a):                            # sessiz
        pass


if __name__ == "__main__":
    print(f"Panel: http://0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Isleyici).serve_forever()
