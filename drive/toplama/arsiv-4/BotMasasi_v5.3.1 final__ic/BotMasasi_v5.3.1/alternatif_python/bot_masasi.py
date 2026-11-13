#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot Masası — tek pencereden 13 yapay zekâ modeli
· Anahtarsız ücretsiz model anında çalışır (Pollinations / GPT-tarzı)
· GLM, Llama, Qwen, Kimi, Mistral, DeepSeek, Gemini, Nemotron → ücretsiz kayıt anahtarıyla
· ChatGPT & Claude → kendi API anahtarınızla (ücretli)
· "HEPSİNE SOR" → aynı soruyu seçili tüm modellere aynı anda gönderir, cevapları yanyana gösterir
Yalnızca Python standart kütüphanesi kullanılır; ek kurulum gerekmez.
"""

import json
import os
import sys
import ssl
import threading
import webbrowser
import urllib.error
import urllib.request

TK_OK = True
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    from tkinter.scrolledtext import ScrolledText
except Exception:
    TK_OK = False

APP_ADI = "Bot Masası"
SURUM = "5.3.1"

# ---------------------------------------------------------------- klasör/ayar
def uygulama_klasoru():
    if getattr(sys, "frozen", False):          # PyInstaller .exe
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

AYAR_DOSYASI = os.path.join(uygulama_klasoru(), "ayarlar.json")

def ayar_yukle():
    try:
        with open(AYAR_DOSYASI, "r", encoding="utf-8") as f:
            veri = json.load(f)
        if isinstance(veri, dict):
            veri.setdefault("anahtarlar", {})
            veri.setdefault("modeller", {})
            return veri
    except Exception:
        pass
    return {"anahtarlar": {}, "modeller": {}}

def ayar_kaydet(veri):
    try:
        with open(AYAR_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

# ---------------------------------------------------------------- sağlayıcılar
PROVIDERS = [
    dict(id="pollinations", ad="Anahtarsız Ücretsiz (GPT-tarzı)", tur="openai",
         url="https://text.pollinations.ai/openai",
         models_url="https://text.pollinations.ai/models",
         model="openai-fast", anahtar_gerekli=False, ucretsiz=True,
         rehber="https://pollinations.ai",
         not_="Kayıt yok, anahtar yok — hemen çalışır. Yoğun saatlerde yavaşlayabilir."),
    dict(id="glm", ad="GLM — Z.ai (ücretsiz Flash)", tur="openai",
         url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
         models_url=None,
         model="glm-4.7-flash", anahtar_gerekli=True, ucretsiz=True,
         rehber="https://open.bigmodel.cn",
         not_="glm-4.7-flash tamamen ücretsiz. Anahtar: open.bigmodel.cn → API Anahtarları."),
    dict(id="nvidia", ad="NVIDIA Nemotron (+yüzlerce model)", tur="openai",
         url="https://integrate.api.nvidia.com/v1/chat/completions",
         models_url="https://integrate.api.nvidia.com/v1/models",
         model="nvidia/nemotron-3.5-bolt-e4b", anahtar_gerekli=True, ucretsiz=True,
         rehber="https://build.nvidia.com",
         not_="Ücretsiz anahtar: build.nvidia.com. Kimi için 'moonshotai/kimi-…' modelini seçin."),
    dict(id="groq", ad="Groq — Llama (çok hızlı)", tur="openai",
         url="https://api.groq.com/openai/v1/chat/completions",
         models_url="https://api.groq.com/openai/v1/models",
         model="llama-3.1-8b-instant", anahtar_gerekli=True, ucretsiz=True,
         rehber="https://console.groq.com",
         not_="Ücretsiz anahtar: console.groq.com → API Keys. Güncel model adı için 'Modelleri Getir'."),
    dict(id="mistral", ad="Mistral", tur="openai",
         url="https://api.mistral.ai/v1/chat/completions",
         models_url="https://api.mistral.ai/v1/models",
         model="mistral-small-latest", anahtar_gerekli=True, ucretsiz=True,
         rehber="https://console.mistral.ai",
         not_="Ücretsiz deneme planı var: console.mistral.ai → API Keys."),
    dict(id="qwen", ad="Qwen — Alibaba", tur="openai",
         url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
         models_url=None,
         model="qwen-turbo", anahtar_gerekli=True, ucretsiz=True,
         rehber="https://console.alibabacloud.com",
         not_="Yeni hesaba ücretsiz başlangıç kotası verilir (Model Studio → API-KEY)."),
    dict(id="kimi", ad="Kimi — Moonshot", tur="openai",
         url="https://api.moonshot.ai/v1/chat/completions",
         models_url="https://api.moonshot.ai/v1/models",
         model="moonshot-v1-8k", anahtar_gerekli=True, ucretsiz=True,
         rehber="https://platform.moonshot.ai",
         not_="Yeni hesaba küçük ücretsiz kredi verilir: platform.moonshot.ai → API Keys."),
    dict(id="deepseek", ad="DeepSeek", tur="openai",
         url="https://api.deepseek.com/v1/chat/completions",
         models_url=None,
         model="deepseek-chat", anahtar_gerekli=True, ucretsiz=False,
         rehber="https://platform.deepseek.com",
         not_="Çok ucuz kullanım başına ödeme: platform.deepseek.com → API Keys."),
    dict(id="gemini", ad="Google Gemini", tur="openai",
         url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
         models_url="https://generativelanguage.googleapis.com/v1beta/openai/models",
         model="gemini-3.5-flash-lite", anahtar_gerekli=True, ucretsiz=True,
         rehber="https://aistudio.google.com",
         not_="Ücretsiz kota: aistudio.google.com → Get API key."),
    dict(id="openai", ad="ChatGPT — OpenAI API (ücretli)", tur="openai",
         url="https://api.openai.com/v1/chat/completions",
         models_url="https://api.openai.com/v1/models",
         model="gpt-4o-mini", anahtar_gerekli=True, ucretsiz=False,
         rehber="https://platform.openai.com/api-keys",
         not_="Ücretli. Gerçek ChatGPT'yi ÜCRETSİZ kotalı denemek için: bot_masasi.html dosyasını açın."),
    dict(id="anthropic", ad="Claude — Anthropic API (ücretli)", tur="anthropic",
         url="https://api.anthropic.com/v1/messages",
         models_url="https://api.anthropic.com/v1/models",
         model="claude-sonnet-4-5", anahtar_gerekli=True, ucretsiz=False,
         rehber="https://console.anthropic.com",
         not_="Ücretli. Gerçek Claude'u ÜCRETSİZ kotalı denemek için: bot_masasi.html dosyasını açın."),
    dict(id="openrouter", ad="OpenRouter — tek anahtarla 300+ model", tur="openai",
         url="https://openrouter.ai/api/v1/chat/completions",
         models_url="https://openrouter.ai/api/v1/models",
         model="openrouter/auto", anahtar_gerekli=True, ucretsiz=True,
         rehber="https://openrouter.ai/keys",
         not_="Tek anahtarla Claude/GPT/Kimi/Qwen dahil 300+ model; adı ':free' ile bitenler ücretsizdir."),
    dict(id="ollama", ad="Ollama — bilgisayarınızda yerel", tur="openai",
         url="http://localhost:11434/v1/chat/completions",
         models_url="http://localhost:11434/v1/models",
         model="llama3.1", anahtar_gerekli=False, ucretsiz=True,
         rehber="https://ollama.com",
         not_="ollama.com kuruluysa: sınırsız, anahtarsız, tamamen sizin bilgisayarınızda."),
]
P_MAP = {p["id"]: p for p in PROVIDERS}

# ---------------------------------------------------------------- ağ katmanı
CTX = ssl.create_default_context()

def http_istek(url, payload=None, headers=None, timeout=240):
    basliklar = {"Content-Type": "application/json", "User-Agent": "BotMasasi/5.3.1"}
    if headers:
        basliklar.update(headers)
    veri = json.dumps(payload).encode("utf-8") if payload is not None else None
    istek = urllib.request.Request(url, data=veri, headers=basliklar,
                                   method="POST" if veri else "GET")
    with urllib.request.urlopen(istek, timeout=timeout, context=CTX) as cevap:
        return json.loads(cevap.read().decode("utf-8", "ignore"))

def turkce_hata(e):
    kod = getattr(e, "code", 0)
    try:
        detay = e.read().decode("utf-8", "ignore")[:300].strip()
    except Exception:
        detay = ""
    if kod in (401, 403):
        m = "Anahtar hatalı/eksik veya yetkisiz (HTTP %s). Ayarlar ⚙ bölümünden anahtarı kontrol edin." % kod
    elif kod == 402:
        m = "Kredi/bakiye yetersiz (HTTP 402)."
    elif kod == 404:
        m = "Model veya adres bulunamadı (HTTP 404) — Ayarlar ⚙ → 'Modelleri Getir' ile güncel model adını seçin."
    elif kod == 429:
        m = "Limit doldu (HTTP 429) — kısa süre bekleyin ya da başka bir model seçin."
    elif kod and kod >= 500:
        m = "Sunucu hatası (HTTP %s) — servis şu an sorun yaşıyor, sonra tekrar deneyin." % kod
    else:
        m = "Bağlantı hatası%s" % ((" (HTTP %s)" % kod) if kod else "")
    if detay:
        m += "\n" + detay
    return m

def sse_akis(url, payload, headers, on_delta, timeout=300):
    """OpenAI-uyumlu akışı (stream) okur; tam metni döndürür. on_delta False döndürürse durur."""
    basliklar = {"Content-Type": "application/json", "Accept": "text/event-stream",
                 "User-Agent": "BotMasasi/5.3.1"}
    if headers:
        basliklar.update(headers)
    istek = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                   headers=basliklar, method="POST")
    tam = ""
    with urllib.request.urlopen(istek, timeout=timeout, context=CTX) as cevap:
        for ham in cevap:
            satir = ham.decode("utf-8", "ignore").strip()
            if not satir.startswith("data:"):
                continue
            veri = satir[5:].strip()
            if veri == "[DONE]":
                break
            try:
                nesne = json.loads(veri)
            except ValueError:
                continue
            secimler = nesne.get("choices") or [{}]
            parca = (secimler[0].get("delta") or {}).get("content")
            if parca:
                tam += parca
                if on_delta is not None and on_delta(parca) is False:
                    raise KeyboardInterrupt
    return tam

def openai_sohbet(p, key, model, mesajlar, sistem="", on_delta=None):
    msgs = ([{"role": "system", "content": sistem}] if sistem else []) + list(mesajlar)
    basliklar = {}
    if key:
        basliklar["Authorization"] = "Bearer " + key
    if p["id"] == "openrouter":
        basliklar["HTTP-Referer"] = "https://bot-masasi.local"
        basliklar["X-Title"] = "Bot Masasi"
    govde = {"model": model, "messages": msgs, "stream": True}
    if p["id"] == "pollinations":
        govde["referrer"] = "bot-masasi"
    ilk_hata = None
    if on_delta is not None:
        try:
            metin = sse_akis(p["url"], govde, basliklar, on_delta)
            if metin.strip():
                return metin
        except KeyboardInterrupt:
            raise
        except urllib.error.HTTPError as e:
            ilk_hata = turkce_hata(e)
        except Exception as e:
            ilk_hata = str(e)
    govde["stream"] = False
    try:
        cevap = http_istek(p["url"], govde, basliklar)
        metin = ((cevap.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if not metin:
            metin = json.dumps(cevap, ensure_ascii=False)[:600]
        if on_delta is not None and metin:
            on_delta(metin)
        return metin
    except urllib.error.HTTPError as e:
        raise RuntimeError(ilk_hata or turkce_hata(e))
    except Exception as e:
        raise RuntimeError(ilk_hata or str(e))

def anthropic_sohbet(p, key, model, mesajlar, sistem="", on_delta=None):
    if not key:
        raise RuntimeError("Claude için API anahtarı gerekli: console.anthropic.com → API keys\n"
                           "(Ücretsiz denemek için: bot_masasi.html dosyasını açın.)")
    govde = {"model": model, "max_tokens": 2048, "messages": list(mesajlar)}
    if sistem:
        govde["system"] = sistem
    try:
        cevap = http_istek(p["url"], govde,
                           {"x-api-key": key, "anthropic-version": "2023-06-01"})
    except urllib.error.HTTPError as e:
        raise RuntimeError(turkce_hata(e))
    except Exception as e:
        raise RuntimeError(str(e))
    metin = "".join(b.get("text", "") for b in cevap.get("content", [])
                    if isinstance(b, dict) and b.get("type") == "text")
    if on_delta is not None and metin:
        on_delta(metin)
    return metin

def sohbet(pid, key, model, mesajlar, sistem="", on_delta=None):
    """v5.3.1 SINIRSIZ ZİNCİR: seçili sağlayıcı kalıcı hata verirse (anahtar/kota/404/
    sunucu) otomatik olarak anahtarsız yedek hata (pollinations) geçer; masa asla
    kilitlenmez. Yedek devreye girdiğinde akışta küçük bir not gösterilir."""
    try:
        return _sohbet_tek(pid, key, model, mesajlar, sistem, on_delta)
    except RuntimeError as h:
        if pid == "pollinations":
            raise
        hata = str(h)
        olumcu = any(x in hata for x in ("401", "403", "404", "429", "Anahtar", "Limit",
                                         "Sunucu hatası", "Kredi", "bulunamadı"))
        if not olumcu:
            raise
        if on_delta is not None:
            on_delta("\n↪ %s yanıt vermedi → otomatik yedek hat devrede…\n" % P_MAP[pid]["ad"])
        try:
            metin = _sohbet_tek("pollinations", "", "openai-fast", mesajlar, sistem, on_delta)
        except Exception:
            raise
        if metin.strip():
            if on_delta is not None:
                on_delta("\n✔ yedek hat (Anahtarsız Bot) yanıtladı — kendi anahtarınızı "
                         "Ayarlar ⚙'den girince %s yeniden devreye girer.\n" % P_MAP[pid]["ad"])
            return metin
        raise

def _sohbet_tek(pid, key, model, mesajlar, sistem="", on_delta=None):
    p = P_MAP[pid]
    if p["tur"] == "anthropic":
        return anthropic_sohbet(p, key, model, mesajlar, sistem, on_delta)
    return openai_sohbet(p, key, model, mesajlar, sistem, on_delta)

def modelleri_getir(pid, key):
    p = P_MAP[pid]
    if not p["models_url"]:
        return None
    if pid == "pollinations":
        liste = http_istek(p["models_url"], None, {}, timeout=60)
        sonuc = []
        for m in liste:
            if isinstance(m, dict):
                ad = m.get("name") or m.get("id")
                if ad:
                    if m.get("tier") == "anonymous":
                        ad += "  (anahtarsız)"
                    sonuc.append(ad)
        return sonuc
    basliklar = {}
    if p["tur"] == "anthropic":
        if not key:
            raise RuntimeError("Modelleri listelemek için anahtar gerekli.")
        basliklar = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif key:
        basliklar = {"Authorization": "Bearer " + key}
    cevap = http_istek(p["models_url"], None, basliklar, timeout=60)
    veri = cevap.get("data") or cevap.get("models") or cevap
    ids = []
    for m in veri:
        if isinstance(m, dict):
            i = m.get("id") or m.get("name")
            if i:
                ids.append(i)
        elif isinstance(m, str):
            ids.append(m)
    return sorted(ids)

# ---------------------------------------------------------------- arayüz
RENK = dict(bg="#1b1d21", panel="#24262b", panel2="#2b2e34", yazi="#e8e8e8",
            soluk="#9aa0a6", vurgu="#3b6fe0", vurgu_koyu="#2f57b3", hata="#ff7b72",
            yesil="#7bd88f", sari="#ffd166", kenar="#34373d")

class Uygulama:
    def __init__(self, kok):
        self.kok = kok
        self.ayarlar = ayar_yukle()
        self.anahtarlar = self.ayarlar["anahtarlar"]
        self.modeller = self.ayarlar["modeller"]
        self.sohbetler = [{"baslik": "Yeni Sohbet", "mesajlar": []}]
        self.aktif = 0
        self.iptal = False
        self.mesgul = False

        self.kok.title("%s — 13 model tek pencerede  v%s" % (APP_ADI, SURUM))
        self.kok.geometry("1180x760")
        self.kok.minsize(940, 600)
        self.kok.configure(bg=RENK["bg"])

        self._stil()
        self._yerlesim()
        self._sohbet_listesi_guncelle()
        self._sohbet_goster()

    # ---- stil
    def _stil(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("TCombobox", fieldbackground=RENK["panel2"], background=RENK["panel2"],
                    foreground=RENK["yazi"], arrowcolor=RENK["yazi"], bordercolor=RENK["kenar"])
        s.map("TCombobox", fieldbackground=[("readonly", RENK["panel2"])],
              foreground=[("readonly", RENK["yazi"])])
        self.kok.option_add("*TCombobox*Listbox.background", RENK["panel2"])
        self.kok.option_add("*TCombobox*Listbox.foreground", RENK["yazi"])
        self.kok.option_add("*TCombobox*Listbox.selectBackground", RENK["vurgu"])

    def _btn(self, ebeveyn, yazi, komut, renk="panel2", genislik=None):
        b = tk.Button(ebeveyn, text=yazi, command=komut, bd=0, cursor="hand2",
                      bg=RENK[renk], fg=RENK["yazi"], activebackground=RENK["vurgu_koyu"],
                      activeforeground="#ffffff", padx=10, pady=5,
                      font=("Segoe UI", 9))
        if genislik:
            b.configure(width=genislik)
        return b

    # ---- yerleşim
    def _yerlesim(self):
        # sol kenar çubuğu
        sol = tk.Frame(self.kok, bg=RENK["panel"], width=210)
        sol.pack(side="left", fill="y")
        sol.pack_propagate(False)

        tk.Label(sol, text="  SOHBETLER", bg=RENK["panel"], fg=RENK["soluk"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(10, 4))

        self.liste = tk.Listbox(sol, bg=RENK["panel"], fg=RENK["yazi"], bd=0,
                                highlightthickness=0, selectbackground=RENK["vurgu"],
                                selectforeground="#ffffff", font=("Segoe UI", 10),
                                activestyle="none")
        self.liste.pack(fill="both", expand=True, padx=8, pady=4)
        self.liste.bind("<<ListboxSelect>>", self._sohbet_secildi)
        self.liste.bind("<Double-Button-1>", lambda e: self._yeniden_adlandir())

        alt = tk.Frame(sol, bg=RENK["panel"])
        alt.pack(fill="x", padx=8, pady=8)
        self._btn(alt, "＋ Yeni", self._yeni_sohbet).pack(side="left", padx=(0, 4))
        self._btn(alt, "✏", lambda: self._yeniden_adlandir()).pack(side="left", padx=2)
        self._btn(alt, "🗑", self._sohbet_sil, renk="hata").pack(side="left", padx=2)
        self._btn(alt, "💾", self._json_kaydet).pack(side="left", padx=2)
        self._btn(alt, "📂", self._json_ac).pack(side="left", padx=2)

        # sağ taraf
        sag = tk.Frame(self.kok, bg=RENK["bg"])
        sag.pack(side="left", fill="both", expand=True)

        ust = tk.Frame(sag, bg=RENK["bg"])
        ust.pack(fill="x", padx=12, pady=(10, 2))

        tk.Label(ust, text="Model:", bg=RENK["bg"], fg=RENK["soluk"],
                 font=("Segoe UI", 10)).pack(side="left")
        self.ad_map = {p["ad"]: p["id"] for p in PROVIDERS}
        self.model_kutu = ttk.Combobox(ust, values=list(self.ad_map.keys()),
                                       state="readonly", width=38, font=("Segoe UI", 10))
        self.model_kutu.current(0)
        self.model_kutu.pack(side="left", padx=6)
        self.model_kutu.bind("<<ComboboxSelected>>", lambda e: self._not_goster())

        self._btn(ust, "⚙ Anahtarlar", self._ayarlar_dialog).pack(side="left", padx=4)
        self._btn(ust, "⚖ HEPSİNE SOR", self._hepsine_sor, renk="vurgu").pack(side="left", padx=4)
        self._btn(ust, "📝 .txt", self._txt_aktar).pack(side="left", padx=4)

        self.not_satiri = tk.Label(sag, text="", bg=RENK["bg"], fg=RENK["soluk"],
                                   font=("Segoe UI", 9), anchor="w")
        self.not_satiri.pack(fill="x", padx=14)

        # sistem talimatı
        sys_cerceve = tk.Frame(sag, bg=RENK["bg"])
        sys_cerceve.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(sys_cerceve, text="Rol:", bg=RENK["bg"], fg=RENK["sari"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        self.sistem_giris = tk.Entry(sys_cerceve, bg=RENK["panel2"], fg=RENK["yazi"],
                                     insertbackground=RENK["yazi"], bd=0,
                                     font=("Segoe UI", 10))
        self.sistem_giris.pack(side="left", fill="x", expand=True, padx=6, ipady=5)

        # sohbet alanı
        self.alan = ScrolledText(sag, bg=RENK["bg"], fg=RENK["yazi"], bd=0,
                                 insertbackground=RENK["yazi"], wrap="word",
                                 font=("Segoe UI", 11), state="disabled",
                                 padx=14, pady=10, highlightthickness=0)
        self.alan.pack(fill="both", expand=True, padx=8, pady=6)
        self.alan.tag_configure("kullanici", foreground=RENK["sari"],
                                font=("Segoe UI", 11, "bold"))
        self.alan.tag_configure("bot", foreground=RENK["yazi"])
        self.alan.tag_configure("botad", foreground=RENK["yesil"],
                                font=("Segoe UI", 10, "bold"))
        self.alan.tag_configure("hata", foreground=RENK["hata"])
        self.alan.tag_configure("ayrac", foreground=RENK["kenar"])

        # giriş alanı
        giris = tk.Frame(sag, bg=RENK["bg"])
        giris.pack(fill="x", padx=12, pady=(0, 12))
        self.giris = tk.Text(giris, bg=RENK["panel2"], fg=RENK["yazi"], bd=0,
                             insertbackground=RENK["yazi"], height=3, wrap="word",
                             font=("Segoe UI", 11), highlightthickness=0)
        self.giris.pack(side="left", fill="both", expand=True, ipady=6, padx=(0, 8))
        self.giris.bind("<Return>", self._enter_tusu)
        self.giris.bind("<Shift-Return>", lambda e: None)

        dugmeler = tk.Frame(giris, bg=RENK["bg"])
        dugmeler.pack(side="right", fill="y")
        self.gonder_btn = self._btn(dugmeler, "Gönder ▶", self._gonder, renk="vurgu")
        self.gonder_btn.pack(fill="x", pady=(0, 6))
        self.durdur_btn = self._btn(dugmeler, "⏹ Durdur", self._durdur)
        self.durdur_btn.pack(fill="x")
        self.durdur_btn.configure(state="disabled")

        self._not_goster()

    # ---- sohbet yönetimi
    def _sohbet_listesi_guncelle(self):
        self.liste.delete(0, "end")
        for i, s in enumerate(self.sohbetler):
            self.liste.insert("end", " " + s["baslik"])
        if 0 <= self.aktif < len(self.sohbetler):
            self.liste.selection_clear(0, "end")
            self.liste.selection_set(self.aktif)

    def _sohbet_secildi(self, _e=None):
        secim = self.liste.curselection()
        if secim and not self.mesgul:
            self.aktif = secim[0]
            self._sohbet_goster()

    def _sohbet_goster(self):
        self.alan.configure(state="normal")
        self.alan.delete("1.0", "end")
        s = self.sohbetler[self.aktif]
        for m in s["mesajlar"]:
            if m["role"] == "user":
                self.alan.insert("end", "Sen ▸ ", "kullanici")
                self.alan.insert("end", m["content"] + "\n\n")
            elif m["role"] == "assistant":
                ad = m.get("model", "Bot")
                self.alan.insert("end", ad + " ▸ ", "botad")
                self.alan.insert("end", m["content"] + "\n\n")
            self.alan.insert("end", "─" * 60 + "\n\n", "ayrac")
        self.alan.configure(state="disabled")
        self.alan.see("end")

    def _yeni_sohbet(self):
        if self.mesgul:
            return
        self.sohbetler.append({"baslik": "Yeni Sohbet", "mesajlar": []})
        self.aktif = len(self.sohbetler) - 1
        self._sohbet_listesi_guncelle()
        self._sohbet_goster()

    def _sohbet_sil(self):
        if self.mesgul or len(self.sohbetler) == 1:
            return
        self.sohbetler.pop(self.aktif)
        self.aktif = max(0, self.aktif - 1)
        self._sohbet_listesi_guncelle()
        self._sohbet_goster()

    def _yeniden_adlandir(self):
        s = self.sohbetler[self.aktif]
        ad = simpledialog.askstring("Yeniden adlandır", "Yeni başlık:", initialvalue=s["baslik"])
        if ad:
            s["baslik"] = ad.strip()[:50]
            self._sohbet_listesi_guncelle()

    # ---- kaydet / aç
    def _json_kaydet(self):
        dosya = filedialog.asksaveasfilename(defaultextension=".json",
                                             filetypes=[("Sohbet", "*.json")],
                                             initialfile="sohbetler.json")
        if dosya:
            with open(dosya, "w", encoding="utf-8") as f:
                json.dump(self.sohbetler, f, ensure_ascii=False, indent=2)
            self._durum("Sohbet kaydedildi.")

    def _json_ac(self):
        dosya = filedialog.askopenfilename(filetypes=[("Sohbet", "*.json")])
        if not dosya:
            return
        try:
            with open(dosya, "r", encoding="utf-8") as f:
                veri = json.load(f)
            if isinstance(veri, list) and veri:
                self.sohbetler.extend(veri)
                self.aktif = len(self.sohbetler) - 1
                self._sohbet_listesi_guncelle()
                self._sohbet_goster()
        except Exception as e:
            messagebox.showerror(APP_ADI, "Dosya okunamadı:\n%s" % e)

    def _txt_aktar(self):
        s = self.sohbetler[self.aktif]
        dosya = filedialog.asksaveasfilename(defaultextension=".txt",
                                             filetypes=[("Metin", "*.txt")],
                                             initialfile=s["baslik"] + ".txt")
        if not dosya:
            return
        with open(dosya, "w", encoding="utf-8") as f:
            for m in s["mesajlar"]:
                kim = "SEN" if m["role"] == "user" else (m.get("model") or "BOT").upper()
                f.write("=== %s ===\n%s\n\n" % (kim, m["content"]))
        self._durum("Metin dosyası kaydedildi.")

    def _durum(self, yazi):
        self.not_satiri.configure(text=yazi)

    # ---- gönderim
    def _enter_tusu(self, olay):
        self._gonder()
        return "break"

    def _durdur(self):
        self.iptal = True

    def _aktif_pid(self):
        return self.ad_map.get(self.model_kutu.get(), "pollinations")

    def _not_goster(self):
        p = P_MAP[self._aktif_pid()]
        self.not_satiri.configure(text="ℹ " + p["not_"])

    def _gonder(self):
        if self.mesgul:
            return
        soru = self.giris.get("1.0", "end").strip()
        if not soru:
            return
        pid = self._aktif_pid()
        p = P_MAP[pid]
        key = self.anahtarlar.get(pid, "").strip()
        model = self.modeller.get(pid, p["model"]).strip() or p["model"]
        if p["anahtar_gerekli"] and not key:
            messagebox.showwarning(APP_ADI,
                "%s için API anahtarı girilmemiş.\n\n%s" % (p["ad"], p["not_"]))
            return

        self.giris.delete("1.0", "end")
        s = self.sohbetler[self.aktif]
        s["mesajlar"].append({"role": "user", "content": soru})
        if s["baslik"] == "Yeni Sohbet":
            s["baslik"] = soru[:38] + ("…" if len(soru) > 38 else "")
            self._sohbet_listesi_guncelle()

        self.alan.configure(state="normal")
        self.alan.insert("end", "Sen ▸ ", "kullanici")
        self.alan.insert("end", soru + "\n")
        self.alan.insert("end", p["ad"] + " ▸ ", "botad")
        self.alan.configure(state="disabled")
        self.alan.see("end")

        self.mesgul = True
        self.iptal = False
        self.gonder_btn.configure(state="disabled")
        self.durdur_btn.configure(state="normal")
        self._durum("Yanıt bekleniyor…")

        t = threading.Thread(target=self._is_parcacigi,
                             args=(pid, key, model, list(s["mesajlar"]),
                                   self.sistem_giris.get().strip()),
                             daemon=True)
        t.start()

    def _is_parcacigi(self, pid, key, model, mesajlar, sistem):
        birikmis = []
        def akis(parca):
            if self.iptal:
                return False
            birikmis.append(parca)
            self.kok.after(0, self._deltas_yaz, parca)
            return True
        try:
            metin = sohbet(pid, key, model, mesajlar, sistem, akis)
            if not metin.strip():
                raise RuntimeError("Model boş yanıt döndürdü. Biraz bekleyip tekrar deneyin.")
            self.kok.after(0, self._bitti, pid, model, metin, None)
        except KeyboardInterrupt:
            metin = "".join(birikmis)
            self.kok.after(0, self._bitti, pid, model, metin, "⏹ Durduruldu.")
        except Exception as e:
            self.kok.after(0, self._bitti, pid, model, None, str(e))

    def _deltas_yaz(self, parca):
        self.alan.configure(state="normal")
        self.alan.insert("end", parca, "bot")
        self.alan.configure(state="disabled")
        self.alan.see("end")

    def _bitti(self, pid, model, metin, hata):
        p = P_MAP[pid]
        self.alan.configure(state="normal")
        if hata:
            if metin:
                self.alan.insert("end", metin, "bot")
                self.alan.insert("end", "\n" + hata + "\n", "hata")
                s = self.sohbetler[self.aktif]
                s["mesajlar"].append({"role": "assistant", "content": metin, "model": p["ad"]})
            else:
                self.alan.insert("end", "\n✖ " + hata + "\n", "hata")
        else:
            self.alan.insert("end", "\n\n")
            s = self.sohbetler[self.aktif]
            s["mesajlar"].append({"role": "assistant", "content": metin, "model": p["ad"]})
        self.alan.insert("end", "\n" + "─" * 60 + "\n\n", "ayrac")
        self.alan.configure(state="disabled")
        self.alan.see("end")
        self.mesgul = False
        self.gonder_btn.configure(state="normal")
        self.durdur_btn.configure(state="disabled")
        self._durum("")

    # ---- ayarlar
    def _ayarlar_dialog(self):
        pence = tk.Toplevel(self.kok)
        pence.title("Anahtarlar & Modeller")
        pence.configure(bg=RENK["bg"])
        pence.geometry("900x640")

        tk.Label(pence, text="API anahtarlarını bir kez girin — bilgisayarınızda ayarlar.json dosyasında saklanır.\n"
                             "Sadece kullanacağınız modellere anahtar girin; anahtarsız model zaten çalışır.",
                 bg=RENK["bg"], fg=RENK["soluk"], justify="left").pack(anchor="w", padx=12, pady=(10, 4))

        cerceve = tk.Frame(pence, bg=RENK["bg"])
        cerceve.pack(fill="both", expand=True, padx=12)

        basliklar = ("Model servisi", "API anahtarı", "Model adı", "", "")
        for c, yazi in enumerate(basliklar):
            tk.Label(cerceve, text=yazi, bg=RENK["bg"], fg=RENK["sari"],
                     font=("Segoe UI", 9, "bold")).grid(row=0, column=c, sticky="w", padx=3)

        girisler = {}
        for r, p in enumerate(PROVIDERS, start=1):
            etiket = p["ad"] + ("   ★ÜCRETSİZ" if p["ucretsiz"] and p["anahtar_gerekli"] else "")
            tk.Label(cerceve, text=etiket, bg=RENK["bg"], fg=RENK["yazi"],
                     font=("Segoe UI", 9)).grid(row=r, column=0, sticky="w", padx=3, pady=3)
            k = tk.Entry(cerceve, width=36, show="•", bg=RENK["panel2"], fg=RENK["yazi"],
                         insertbackground=RENK["yazi"], bd=0)
            k.insert(0, self.anahtarlar.get(p["id"], ""))
            k.grid(row=r, column=1, padx=3, ipady=3)
            m = tk.Entry(cerceve, width=26, bg=RENK["panel2"], fg=RENK["yazi"],
                         insertbackground=RENK["yazi"], bd=0)
            m.insert(0, self.modeller.get(p["id"], p["model"]))
            m.grid(row=r, column=2, padx=3, ipady=3)
            self._btn(cerceve, "🔍 Liste", lambda pp=p, ke=k, me=m: self._model_listesi(pp, ke, me)
                      ).grid(row=r, column=3, padx=2)
            self._btn(cerceve, "🌐 Kayıt", lambda u=p["rehber"]: webbrowser.open(u)
                      ).grid(row=r, column=4, padx=2)
            girisler[p["id"]] = (k, m)

        def kaydet():
            for pid, (k, m) in girisler.items():
                self.anahtarlar[pid] = k.get().strip()
                self.modeller[pid] = m.get().strip()
            self.ayarlar["anahtarlar"] = self.anahtarlar
            self.ayarlar["modeller"] = self.modeller
            ok = ayar_kaydet(self.ayarlar)
            pence.destroy()
            self._durum("Ayarlar kaydedildi." if ok else "Ayar dosyasına yazılamadı!")

        self._btn(pence, "Kaydet", kaydet, renk="vurgu").pack(pady=10)

    def _model_listesi(self, p, key_giris, model_giris):
        pid = p["id"]
        key = key_giris.get().strip()
        self._durum("Model listesi alınıyor…")
        def arka_is():
            try:
                liste = modelleri_getir(pid, key)
            except Exception as e:
                self.kok.after(0, messagebox.showerror, APP_ADI, "Liste alınamadı:\n%s" % e)
                self.kok.after(0, self._durum, "")
                return
            self.kok.after(0, lambda: self._liste_sec(p, liste, model_giris))
        threading.Thread(target=arka_is, daemon=True).start()

    def _liste_sec(self, p, liste, model_giris):
        self._durum("")
        if not liste:
            messagebox.showinfo(APP_ADI, "Bu servis model listesi sunmuyor; model adını elle yazın.")
            return
        pencere = tk.Toplevel(self.kok)
        pencere.title("%s — modeller (%d)" % (p["ad"], len(liste)))
        pencere.geometry("460x420")
        lb = tk.Listbox(pencere, bg=RENK["panel2"], fg=RENK["yazi"], bd=0,
                        highlightthickness=0, font=("Consolas", 10))
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        for ad in liste:
            lb.insert("end", ad)

        def sec(_e=None):
            secim = lb.curselection()
            if secim:
                model_giris.delete(0, "end")
                temiz = liste[secim[0]].split("  (anahtarsız)")[0]
                model_giris.insert(0, temiz)
                pencere.destroy()
        lb.bind("<Double-Button-1>", sec)

    # ---- HEPSİNE SOR
    def _hepsine_sor(self):
        if self.mesgul:
            messagebox.showinfo(APP_ADI, "Önce devam eden yanıtı bekleyin veya durdurun.")
            return
        pence = tk.Toplevel(self.kok)
        pence.title("⚖ Hepsine Sor — aynı soru, tüm modeller")
        pence.configure(bg=RENK["bg"])
        pence.geometry("1280x760")

        ust = tk.Frame(pence, bg=RENK["bg"])
        ust.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(ust, text="Soru:", bg=RENK["bg"], fg=RENK["sari"],
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        soru_giris = tk.Text(ust, height=2, bg=RENK["panel2"], fg=RENK["yazi"], bd=0,
                             insertbackground=RENK["yazi"], font=("Segoe UI", 10),
                             wrap="word")
        soru_giris.pack(side="left", fill="x", expand=True, padx=8, ipady=4)

        secim_cerceve = tk.Frame(pence, bg=RENK["bg"])
        secim_cerceve.pack(fill="x", padx=10)
        kutu = {}
        for p in PROVIDERS:
            kullanilabilir = (not p["anahtar_gerekli"]) or bool(self.anahtarlar.get(p["id"], "").strip())
            deger = tk.BooleanVar(value=kullanilabilir)
            cb = tk.Checkbutton(secim_cerceve, text=p["ad"], variable=deger,
                                bg=RENK["bg"], fg=RENK["yazi"], selectcolor=RENK["panel2"],
                                activebackground=RENK["bg"], activeforeground=RENK["yazi"],
                                bd=0, font=("Segoe UI", 8))
            cb.pack(side="left", padx=4)
            if not kullanilabilir:
                cb.configure(fg=RENK["soluk"])
            kutu[p["id"]] = deger

        sonuc_alani = tk.Frame(pence, bg=RENK["bg"])
        sonuc_alani.pack(fill="both", expand=True, padx=10, pady=8)

        durum = {"calisiyor": False}

        def gonder_hepsine():
            if durum["calisiyor"]:
                return
            soru = soru_giris.get("1.0", "end").strip()
            if not soru:
                return
            secili = [pid for pid, v in kutu.items() if v.get()]
            if len(secili) < 1:
                messagebox.showinfo(APP_ADI, "En az bir model seçin.")
                return
            durum["calisiyor"] = True
            gonder_btn.configure(state="disabled")
            kalan = {"n": len(secili)}
            def bir_bitti():
                kalan["n"] -= 1
                if kalan["n"] <= 0:
                    durum["calisiyor"] = False
                    gonder_btn.configure(state="normal")
            for w in sonuc_alani.winfo_children():
                w.destroy()
            for i, pid in enumerate(secili):
                p = P_MAP[pid]
                sutun = tk.Frame(sonuc_alani, bg=RENK["panel"], bd=0)
                sutun.grid(row=0, column=i, sticky="nsew", padx=3, pady=3)
                sonuc_alani.columnconfigure(i, weight=1)
                sonuc_alani.rowconfigure(0, weight=1)
                tk.Label(sutun, text=p["ad"], bg=RENK["panel"], fg=RENK["yesil"],
                         font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", padx=6, pady=(6, 0))
                kutu_txt = ScrolledText(sutun, bg=RENK["panel"], fg=RENK["yazi"], bd=0,
                                        wrap="word", font=("Segoe UI", 9),
                                        highlightthickness=0, state="disabled")
                kutu_txt.pack(fill="both", expand=True, padx=6, pady=6)
                kutu_txt.tag_configure("hata", foreground=RENK["hata"])
                key = self.anahtarlar.get(pid, "").strip()
                model = self.modeller.get(pid, p["model"]).strip() or p["model"]
                threading.Thread(target=self._hepsine_is,
                                 args=(pid, key, model, soru, kutu_txt, pence,
                                       bir_bitti, bir_bitti),
                                 daemon=True).start()

        gonder_btn = self._btn(pence, "⚖ Seçilenlere Gönder", gonder_hepsine, renk="vurgu")
        gonder_btn.pack(pady=4)

    def _hepsine_is(self, pid, key, model, soru, kutu, pence, bitti_durum, bitti_btn):
        def yaz(yazi, tag="bot"):
            def islem():
                kutu.configure(state="normal")
                kutu.insert("end", yazi, tag)
                kutu.configure(state="disabled")
                kutu.see("end")
            pence.after(0, islem)
        try:
            yaz("⏳ düşünüyor…\n")
            sohbet(pid, key, model, [{"role": "user", "content": soru}],
                   "", lambda parca: yaz(parca))
        except Exception as e:
            yaz("\n✖ " + str(e), "hata")
        finally:
            pence.after(0, bitti_durum)
            pence.after(0, bitti_btn)

# ---------------------------------------------------------------- başlat
def main():
    if not TK_OK:
        print("Tkinter bulunamadı. python.org adresinden Python'un tam sürümünü kurun.")
        sys.exit(1)
    kok = tk.Tk()
    Uygulama(kok)
    kok.mainloop()

if __name__ == "__main__":
    main()
