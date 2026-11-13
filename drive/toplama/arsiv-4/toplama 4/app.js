/* Kripto Bot Ekibi — ön yüz mantığı */
const $ = (id) => document.getElementById(id);
const fmt = (v, nd = 2) =>
  Number(v).toLocaleString("tr-TR", { minimumFractionDigits: nd, maximumFractionDigits: nd });
const esc = (s) => String(s ?? "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const yerelTarih = (ts) => {
  if (!ts) return null;
  let s = ts;
  if (!/[Zz]$/.test(s) && !/[+-]\d{2}:?\d{2}$/.test(s)) s += "Z"; // UTC varsay
  const d = new Date(s);
  return isNaN(d) ? null : d;
};
const saat = (ts) => {
  const d = yerelTarih(ts);
  return d ? d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })
           : (ts || "").slice(11, 19);
};
const tarihSaat = (ts) => {
  const d = yerelTarih(ts);
  return d ? d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit",
            hour: "2-digit", minute: "2-digit" })
           : (ts || "").replace("T", " ").slice(0, 16);
};

let durum = null;
let odaSonId = 0;
let odaHata = 0;

async function api(yol, govde = null, yontem) {
  const opt = govde || yontem
    ? { method: yontem || (govde ? "POST" : "GET"),
        headers: { "Content-Type": "application/json" },
        body: govde ? JSON.stringify(govde) : undefined }
    : {};
  const r = await fetch(yol, opt);
  const d = await r.json();
  if (!r.ok) throw new Error(d.hata || d.mesaj || "bilinmeyen hata");
  return d;
}

/* ---------- durum ---------- */
async function durumYukle() {
  durum = await api("/api/durum");
  const chips = $("model-chips");
  chips.innerHTML = durum.modeller
    .map((b) => `<span class="chip ${b.aktif ? "ok" : ""}">${esc(b.emoji)} ${esc(b.ad)}</span>`)
    .join("") + `<span class="chip">⚖️ hakem: ${esc(durum.hakem)}</span>`;
  $("bildirim-badge").textContent =
    `🔔 bildirim: ${durum.bildirim} • tarama: ${durum.tarama_dk} dk • eşik: ${durum.esik}`;
  $("aralik-info").textContent = durum.tarama_dk;
  $("ayar-dk").value = durum.tarama_dk;
  $("ayar-esik").value = durum.esik;
  $("panel-sag").textContent =
    `• analiz: ${durum.istatistik.analiz} • alarm: ${durum.istatistik.alarm}`;
  izlemeCiz(durum.izleme);
  $("hizli").innerHTML = durum.populer
    .map((s) => `<button data-s="${s}">${s.replace("USDT", "")}</button>`).join("");
  $("hizli").querySelectorAll("button").forEach((b) =>
    b.onclick = () => { $("sembol").value = b.dataset.s; analizBaslat(); });
  kadroYukle();
  gecmisYukle();
}

/* ---------- bot kadrosu ---------- */
async function kadroYukle() {
  try {
    const d = await api("/api/botlar");
    $("bot-liste").innerHTML = d.botlar.map((b) => `
      <div class="bot-kartu ${b.aktif ? "" : "pasif"}">
        <div class="bot-avatar">${esc(b.emoji)}</div>
        <div class="bot-bilgi">
          <div class="bot-ad">${esc(b.ad)}</div>
          <div class="bot-rol">${esc(d.roller[b.rol] || b.rol)}</div>
          <select class="bot-model" data-id="${b.id}">
            ${d.modeller.map((m) =>
              `<option value="${m.id}" ${m.id === b.model ? "selected" : ""}>
                ${m.uygun ? "" : "⚠️ "}${esc(m.etiket)}</option>`).join("")}
          </select>
        </div>
        <div class="bot-dugme">
          <label class="anahtar" title="Aktif / Pasif">
            <input type="checkbox" data-id="${b.id}" ${b.aktif ? "checked" : ""}>
            <span></span>
          </label>
          <button class="btn small bot-sil" data-id="${b.id}" title="Kadrodan çıkar">✕</button>
        </div>
      </div>`).join("") || `<p class="hint">Kadro boş — ➕ Bot Ekle ile ilk botunu kur.</p>`;

    $("bot-rol").innerHTML = Object.entries(d.roller)
      .map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    $("bot-model").innerHTML = d.modeller
      .map((m) => `<option value="${m.id}" ${m.uygun ? "" : "disabled"}>
        ${m.uygun ? "✅ " : "⚠️ (anahtar yok) "}${esc(m.etiket)}</option>`).join("");

    $("bot-liste").querySelectorAll(".bot-model").forEach((sel) =>
      sel.onchange = async () => {
        try {
          await api(`/api/botlar/${sel.dataset.id}`, { model: sel.value });
          durumYukle();
        } catch (e) { alert("Model değişmedi: " + e.message); sel.blur(); }
      });
    $("bot-liste").querySelectorAll(".anahtar input").forEach((cb) =>
      cb.onchange = async () => {
        try {
          await api(`/api/botlar/${cb.dataset.id}`, { aktif: cb.checked });
          durumYukle();
        } catch (e) { alert("Değişmedi: " + e.message); }
      });
    $("bot-liste").querySelectorAll(".bot-sil").forEach((btn) =>
      btn.onclick = async () => {
        if (!confirm("Bu bot kadrodan çıkarılsın mı?")) return;
        try {
          await api(`/api/botlar/${btn.dataset.id}`, null, "DELETE");
          durumYukle();
        } catch (e) { alert("Silinemedi: " + e.message); }
      });
  } catch (e) {
    $("bot-liste").innerHTML = `<p class="hint">❌ Kadro yüklenemedi: ${esc(e.message)}</p>`;
  }
}

async function botEkle() {
  const ad = $("bot-ad").value.trim();
  if (!ad) { $("bot-ekle-mesaj").textContent = "Bot adı gerekli."; return; }
  try {
    const d = await api("/api/botlar", {
      ad,
      emoji: $("bot-emoji").value.trim() || "🤖",
      rol: $("bot-rol").value,
      model: $("bot-model").value,
    });
    $("bot-ekle-mesaj").textContent = "✅ Bot kadroya eklendi — odaya selam verdi.";
    $("bot-ad").value = ""; $("bot-emoji").value = "";
    durumYukle();
  } catch (e) {
    $("bot-ekle-mesaj").textContent = "❌ " + e.message;
  }
}

/* ---------- bot odası ---------- */
function odaSatir(m) {
  const s = esc(m.metin).replace(/\n/g, "<br>");
  if (m.tur === "sistem")
    return `<div class="msg sistem"><span>${s}</span>
      <span class="zaman">${saat(m.ts)}</span></div>`;
  if (m.tur === "kullanici")
    return `<div class="msg kullanici"><span class="zaman">${saat(m.ts)}</span>
      <div class="buble"><div class="kim">${esc(m.kim)}</div>${s}</div></div>`;
  return `<div class="msg bot">
    <div class="avatar">${esc(m.emoji || "🤖")}</div>
    <div class="buble"><div class="kim">${esc(m.kim)}
      ${m.kime ? `<span class="kime">→ ${esc(m.kime)}</span>` : ""}</div>${s}</div>
    <span class="zaman">${saat(m.ts)}</span></div>`;
}

function odaCiz(mesajlar, ek) {
  const alan = $("oda-mesajlar");
  if (ek) alan.insertAdjacentHTML("beforeend", mesajlar.map(odaSatir).join(""));
  else alan.innerHTML = mesajlar.map(odaSatir).join("");
  alan.scrollTop = alan.scrollHeight;
}

async function odaYukle(ek = false) {
  try {
    const d = await api(`/api/oda?son_id=${odaSonId}`);
    if (d.mesajlar.length) {
      odaCiz(d.mesajlar, ek);
      odaSonId = d.son_id;
    }
    $("oda-mesgul").classList.toggle("hidden", !d.mesgul);
    $("btn-oda-gonder").disabled = d.mesgul;
    odaHata = 0;
  } catch (e) { /* panel kapalıyken sessizce geç */ }
}

async function odaGonder(metin) {
  metin = (metin ?? $("oda-metin").value).trim();
  if (!metin) return;
  try {
    await api("/api/oda", { metin });
    $("oda-metin").value = "";
    await odaYukle(true);
  } catch (e) { alert("Gönderilemedi: " + e.message); }
}

/* ---------- izleme ---------- */
function izlemeCiz(liste) {
  $("izleme-liste").innerHTML = (liste || []).map((s) =>
    `<li><span>${s}</span><button class="btn small" data-s="${s}">✕</button></li>`).join("")
    || `<li class="hint">Liste boş — sembol ekleyince otomatik alarm kurulur.</li>`;
  $("izleme-liste").querySelectorAll("button").forEach((b) =>
    b.onclick = () => izlemeIslem(b.dataset.s, false));
}
async function izlemeIslem(sembol, ekle) {
  try {
    const d = await api("/api/izleme", { sembol, ekle });
    izlemeCiz(d.izleme);
  } catch (e) { alert("İzleme hatası: " + e.message); }
}

/* ---------- analiz ---------- */
async function analizBaslat() {
  const sembol = $("sembol").value.trim().toUpperCase();
  if (!sembol) return;
  const st = $("analiz-durum");
  st.classList.remove("hidden");
  st.innerHTML = `<span class="spin"></span>Bot ekibi ${sembol} için oyluyor… (20-60 sn)`;
  $("btn-analiz").disabled = true;
  try {
    const r = await api("/api/analiz", { sembol });
    st.classList.add("hidden");
    sonucCiz(r);
    gecmisYukle();
    odaYukle(true);
  } catch (e) {
    st.innerHTML = `❌ ${e.message}`;
  } finally {
    $("btn-analiz").disabled = false;
  }
}

function sonucCiz(r) {
  const t = r.teknik;
  const cls = r.final_yon === "LONG" ? "long" : r.final_yon === "SHORT" ? "short" : "notr";
  const emoji = { LONG: "🟢", SHORT: "🔴", NÖTR: "⚪" }[r.final_yon] || "⚪";
  let html = `
  <div class="verdict ${cls}">
    <div>
      <div class="yon">${emoji} ${r.final_yon}</div>
      <div class="meta">${r.hukum} • ${r.sembol}</div>
    </div>
    <div class="meta">Güven<br><b style="font-size:18px;color:var(--text)">${r.final_guven}%</b></div>
    <div class="meta">Oydaşlık<br><b style="font-size:18px;color:var(--text)">${r.oydaslik}%</b></div>
    <div class="meta">Oylar<br><b style="color:var(--text)">${r.oy_dagilimi.LONG}L / ${r.oy_dagilimi.SHORT}S / ${r.oy_dagilimi["NÖTR"]}N</b></div>
    <div class="meta">Fiyat<br><span class="fiyat">${fmt(t.fiyat)} $</span></div>
    <div class="meta">Teknik skor<br><b style="color:var(--text)">${t.skor > 0 ? "+" : ""}${t.skor}</b> (${t.taraf})</div>
    <div class="meta">Plan<br><b style="color:var(--text)">SL ${fmt(t.stop)} • TP1 ${fmt(t.tp1)} • TP2 ${fmt(t.tp2)} • ${t.kaldirac}x</b></div>
  </div>
  <div class="oylar">`;

  for (const o of r.oylar) {
    const kimlik = `${o.bot_emoji || "🤖"} ${o.bot_ad || o.model}`;
    if (o.durum !== "tamam") {
      html += `<div class="oy hata"><div class="model">❌ ${esc(kimlik)}</div>
        <div class="gerekce">${esc(o.hata || "oy alınamadı")}</div></div>`;
      continue;
    }
    const guvenRenk = o.yön === "LONG" ? "g" : o.yön === "SHORT" ? "r" : "";
    html += `
    <div class="oy">
      <div class="model">${esc(kimlik)} <small style="color:var(--dim)">(${esc(o.model)})</small></div>
      <div class="kafa"><span class="yon-chip ${o.yön}">${o.yön}</span>
        <span style="color:var(--dim)">güven ${o.guven}% • risk: ${o.risk}</span></div>
      <div class="bar"><div class="${guvenRenk}" style="width:${o.guven}%"></div></div>
      <div class="gerekce">${esc(o.gerekce)}</div>
    </div>`;
  }
  html += `</div>`;

  if (r.hakem && r.hakem.durum === "tamam") {
    html += `
    <div class="oy hakem" style="margin-bottom:16px">
      <div class="model">⚖️ HAKEM — ${esc(r.hakem.bot_ad || r.hakem.model)}</div>
      <div class="kafa"><span class="yon-chip ${r.hakem.yön}">${r.hakem.yön}</span>
        <span style="color:var(--dim)">güven ${r.hakem.guven}% • risk: ${r.hakem.risk}</span></div>
      <div class="gerekce">${esc(r.hakem.gerekce)}</div>
    </div>`;
  }

  const nedenler = (t.nedenler || []).map(([i, s]) => `${i} ${s}`).join("<br>");
  html += `<div class="card" style="margin-bottom:16px"><h3>🧠 Teknik Gerekçeler</h3>
    <div style="font-size:12px;color:var(--dim)">${nedenler || "—"}</div></div>`;
  $("sonuc").innerHTML = html;
  $("sonuc").classList.remove("hidden");
  $("sonuc").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- tarama ---------- */
async function tarama() {
  const alan = $("tarama-alan");
  alan.innerHTML = `<p class="status"><span class="spin"></span>Piyasa taranıyor…</p>`;
  try {
    const d = await api("/api/tarama", {});
    alan.innerHTML = `<table class="tablo"><tr>
      <th>Sembol</th><th>Taraf</th><th>Skor</th><th>Fiyat</th><th>24s</th>
      <th>RSI</th><th>Funding</th><th>OI 24s</th><th></th></tr>` +
      d.rows.map((r) => {
        const cls = r.taraf.includes("LONG") ? "L" : r.taraf.includes("SHORT") ? "S" : "N";
        return `<tr><td><b>${r.sembol}</b></td>
        <td class="${cls}">${r.emoji} ${r.taraf}</td>
        <td>${r.skor > 0 ? "+" : ""}${r.skor}</td>
        <td>${fmt(r.fiyat)}</td>
        <td>${r.deg24 > 0 ? "+" : ""}${r.deg24.toFixed(2)}%</td>
        <td>${r.rsi}</td><td>${r.funding}%</td><td>${r.oi_deg}%</td>
        <td><button data-s="${r.sembol}">🧠 Analiz</button></td></tr>`;
      }).join("") + `</table>`;
    alan.querySelectorAll("button").forEach((b) =>
      b.onclick = () => { $("sembol").value = b.dataset.s; analizBaslat(); });
  } catch (e) { alan.innerHTML = `<p class="hint">❌ ${e.message}</p>`; }
}

/* ---------- geçmiş / alarmlar ---------- */
async function gecmisYukle() {
  try {
    const d = await api("/api/gecmis?limit=15");
    $("gecmis-tablo").innerHTML = `<tr><th>Zaman</th><th>Sembol</th><th>Karar</th>
      <th>Güven</th><th>Oydaşlık</th><th>Teknik</th><th>Fiyat</th></tr>` +
      (d.rows.length ? d.rows.map((r) => {
        const cls = r.final_yon === "LONG" ? "L" : r.final_yon === "SHORT" ? "S" : "N";
        return `<tr><td style="color:var(--dim)">${tarihSaat(r.created_at)}</td>
          <td><b>${r.sembol}</b>${r.alarm ? " 🚨" : ""}</td>
          <td class="${cls}">${r.final_yon} <small>${r.hukum}</small></td>
          <td>${r.final_guven}%</td><td>${r.oydaslik}%</td>
          <td>${r.teknik_skor > 0 ? "+" : ""}${r.teknik_skor}</td>
          <td>${fmt(r.fiyat)}</td></tr>`;
      }).join("") : `<tr><td colspan="7" class="hint">Henüz analiz yok.</td></tr>`);
    const a = await api("/api/alarmlar");
    $("alarm-tablo").innerHTML = `<tr><th>Zaman</th><th>Sembol</th><th>Sinyal</th>
      <th>Güven</th><th>Fiyat</th></tr>` +
      (a.rows.length ? a.rows.map((r) => {
        const cls = r.final_yon === "LONG" ? "L" : "S";
        return `<tr><td style="color:var(--dim)">${tarihSaat(r.created_at)}</td>
          <td><b>${r.sembol}</b></td><td class="${cls}">${r.final_yon}</td>
          <td>${r.final_guven}%</td><td>${fmt(r.fiyat)}</td></tr>`;
      }).join("") : `<tr><td colspan="5" class="hint">Henüz alarm yok — izleme listesi doldukça burada görünecek.</td></tr>`);
  } catch (e) { /* sessiz */ }
}

/* ---------- ayarlar ---------- */
async function ayarKaydet() {
  try {
    const d = await api("/api/ayarlar", {
      tarama_dk: parseInt($("ayar-dk").value),
      esik: parseInt($("ayar-esik").value),
    });
    $("ayar-mesaj").textContent = "✅ " + d.mesaj;
    durumYukle();
  } catch (e) { $("ayar-mesaj").textContent = "❌ " + e.message; }
}

/* ---------- bağlama ---------- */
$("btn-analiz").onclick = analizBaslat;
$("sembol").addEventListener("keydown", (e) => e.key === "Enter" && analizBaslat());
$("btn-izle").onclick = () => {
  const v = $("izle-sembol").value.trim();
  if (v) { izlemeIslem(v, true); $("izle-sembol").value = ""; }
};
$("izle-sembol").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { const v = $("izle-sembol").value.trim();
    if (v) { izlemeIslem(v, true); $("izle-sembol").value = ""; } }
});
$("btn-tarama").onclick = tarama;
$("btn-ayar").onclick = ayarKaydet;
$("btn-bot-ekle").onclick = botEkle;

$("btn-oda-gonder").onclick = () => odaGonder();
$("oda-metin").addEventListener("keydown", (e) =>
  e.key === "Enter" && odaGonder());
$("btn-oda-temizle").onclick = async () => {
  try {
    await api("/api/oda/temizle", {});
    odaSonId = 0;
    await odaYukle();
  } catch (e) { alert(e.message); }
};

/* hızlı görev çubukları */
const ODA_GOREVLERI = [
  ["📊 BTC analiz", "BTC analiz et"],
  ["🌐 Piyasayı tara", "Piyasayı tara ve özet çıkar"],
  ["🔥 En güçlü fırsat", "En güçlü fırsat hangisi? Piyasayı tara"],
  ["👋 Tanışma", "Botlar kendini tanıtsın"],
];
$("oda-hizli").innerHTML = ODA_GOREVLERI
  .map(([t], i) => `<button data-i="${i}">${t}</button>`).join("");
$("oda-hizli").querySelectorAll("button").forEach((b) =>
  b.onclick = () => odaGonder(ODA_GOREVLERI[b.dataset.i][1]));

/* ---------- başlat ---------- */
durumYukle();
odaYukle();
setInterval(() => odaYukle(true), 2500);       // oda canlı akış
setInterval(() => { gecmisYukle(); }, 60000);  // geçmişi 1 dk'da bir tazele
