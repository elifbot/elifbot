# -*- coding: utf-8 -*-
"""
Bot Masası v5.3.1 — SINIRSIZ MASA sunucusu (alternatif_python paketi).

Puter'sız çalışır: modeller NVIDIA + ücretsiz sağlayıcı API'leriyle konuşur.
exe'nin /api/sohbet hattıyla AYNI protokolü konuşur (data: {"t":...} / {"h":...}),
bu yüzden bot_masasi.html (Sınırsız Masa sayfası) burada da aynen çalışır.

Kullanım:  python sunucu.py  →  http://127.0.0.1:8080
Anahtarlar: anahtarlar.json'a yazılır (nvidia anahtarı gömülüdür, isterseniz
            değiştirebilirsiniz; groq/openrouter anahtarı eklerseniz o botlar da açılır).
"""
import base64
import json
import os
import re
import sys
import threading
import urllib.request
import urllib.error
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KLASOR = os.path.dirname(os.path.abspath(__file__))
AYAR_DOSYASI = os.path.join(KLASOR, "anahtarlar.json")
PORT = 8080

# ── NVIDIA anahtarı: BotMasasi.exe'nin içindeki gömülü anahtar (aynı anahtar) ──
NVIDIA_GOMULU = ("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")

# ── Sağlayıcılar (exe sunucusundaki gerçek model kimlikleri) ──
SAG = [
  {"id": "pollinations", "ad": "Anahtarsız Bot — pollinations (+ücretsiz)",
   "model": "openai", "anahtar_gerekli": False},
  {"id": "nv-glm", "ad": "GLM 5.3 Flash (Z.ai) — NVIDIA (gömülü anahtar)",
   "model": "z-ai/glm-5.3-flash", "anahtar_gerekli": True,
   "anahtar_grubu": "nvidia", "maks_govde": 24000},
  {"id": "nv-ultra", "ad": "Nemotron Ultra 550B — NVIDIA (gömülü anahtar)",
   "model": "nvidia/nemotron-3-ultra-550b-a55b", "anahtar_gerekli": True,
   "anahtar_grubu": "nvidia", "maks_govde": 24000},
  {"id": "nv-bolt", "ad": "Nemotron Bolt — NVIDIA (gömülü anahtar)",
   "model": "nvidia/nemotron-3.5-bolt-e4b", "anahtar_gerekli": True,
   "anahtar_grubu": "nvidia", "maks_govde": 24000},
  {"id": "nv-lightning", "ad": "Nemotron Lightning — NVIDIA (gömülü anahtar)",
   "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "anahtar_gerekli": True,
   "anahtar_grubu": "nvidia", "maks_govde": 24000},
  {"id": "nv-minimax", "ad": "MiniMax M3.1 — NVIDIA (gömülü anahtar)",
   "model": "minimaxai/minimax-m3.1-flash", "anahtar_gerekli": True,
   "anahtar_grubu": "nvidia", "maks_govde": 24000},
  {"id": "nv-gptoss", "ad": "GPT-OSS 20B — NVIDIA (gömülü anahtar)",
   "model": "openai/gpt-oss-20b", "anahtar_gerekli": True,
   "anahtar_grubu": "nvidia", "maks_govde": 24000},
  {"id": "nv-mistral", "ad": "Mistral Large — NVIDIA (gömülü anahtar)",
   "model": "mistralai/mistral-large-4-1t-a52b", "anahtar_gerekli": True,
   "anahtar_grubu": "nvidia", "maks_govde": 24000},
  {"id": "groq", "ad": "Groq — llama 3.1 8B (anahtar: groq.com ücretsiz)",
   "model": "llama-3.1-8b-instant", "anahtar_gerekli": True,
   "anahtar_grubu": "groq"},
  {"id": "openrouter", "ad": "OpenRouter — ':free' modeller (anahtar: openrouter.ai)",
   "model": "deepseek/deepseek-chat-v3.1:free", "anahtar_gerekli": True,
   "anahtar_grubu": "openrouter"},
]

MODELLER_KILIT = {}   # pid -> model id; kullanıcı anahtarlar.json'da değiştirebilir


def ayar_yukle():
  try:
    with open(AYAR_DOSYASI, "r", encoding="utf-8") as f:
      veri = json.load(f)
    if not isinstance(veri, dict):
      veri = {}
  except Exception:
    veri = {}
  anahtarlar = veri.get("anahtarlar") or {}
  if not anahtarlar.get("nvidia"):
    anahtarlar["nvidia"] = NVIDIA_GOMULU
  return {"anahtarlar": anahtarlar,
          "modeller": veri.get("modeller") or {},
          "ekstra": veri.get("ekstra") or {}}


def ayar_kaydet(ayar):
  try:
    with open(AYAR_DOSYASI, "w", encoding="utf-8") as f:
      json.dump(ayar, f, ensure_ascii=False, indent=2)
    try:
      os.chmod(AYAR_DOSYASI, 0o600)
    except Exception:
      pass
  except Exception as h:
    print("[uyarı] anahtarlar.json yazılamadı:", h)


AYAR = ayar_yukle()
AYAR_KILIDI = threading.Lock()


def turkce_hata(e):
  """Upstream hatalarını sayfanın tanıdığı Türkçe anahtar sözcüklere çevir."""
  try:
    govde = ""
    if hasattr(e, "read"):
      try:
        govde = e.read().decode("utf-8", "replace")[:400]
      except Exception:
        pass
    kod = getattr(e, "code", None)
    if kod == 429 or "429" in govde or "rate limit" in govde.lower():
      return "429 rate limit — kota doldu: " + govde
    if kod in (401, 403):
      return ("Anahtar reddedildi (HTTP %s): %s — Gömülü NVIDIA anahtarı geçersiz " % (kod, govde) +
              "olabilir. ⚙ Anahtarlar'dan KENDİ NVIDIA anahtarınızı girin (build.nvidia.com, " +
              "ücretsiz); girene kadar botlar otomatik yedek hatlardan (anahtarsız) devam eder.")
    if kod and kod >= 500:
      return "HTTP %d — sağlayıcı hatası: %s" % (kod, govde)
    if govde:
      return "Sağlayıcı hatası: " + govde
  except Exception:
    pass
  return "Bağlantı hatası: " + str(e)


def sohbet_akisi(pid, model, key, sistem, mesajlar, yaz, hata):
  """OpenAI-uyumlu akışı sayfanın protokolüne çevirir (aynı hat)."""
  if pid == "pollinations":
    url = "https://text.pollinations.ai/openai"
    basliklar = {"Content-Type": "application/json"}
  elif pid == "nv-glm" or pid.startswith("nv-"):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    if not key:
      key = NVIDIA_GOMULU
    basliklar = {"Content-Type": "application/json",
                 "Authorization": "Bearer " + key,
                 "Accept": "text/event-stream"}
  elif pid == "groq":
    url = "https://api.groq.com/openai/v1/chat/completions"
    basliklar = {"Content-Type": "application/json",
                 "Authorization": "Bearer " + key}
  elif pid == "openrouter":
    url = "https://openrouter.ai/api/v1/chat/completions"
    basliklar = {"Content-Type": "application/json",
                 "Authorization": "Bearer " + key}
  else:
    hata("Bilinmeyen sağlayıcı: " + pid)
    return

  icerik = [{"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in mesajlar]
  if sistem:
    icerik = [{"role": "system", "content": sistem}] + icerik
  gonderilecek = json.dumps({
      "model": model, "messages": icerik, "stream": True, "max_tokens": 4096
  }).encode("utf-8")

  istek = urllib.request.Request(url, data=gonderilecek, headers=basliklar,
                                 method="POST")
  try:
    yanit = urllib.request.urlopen(istek, timeout=300)
  except urllib.error.HTTPError as e:
    hata(turkce_hata(e))
    return
  except Exception as e:
    hata(turkce_hata(e))
    return

  try:
    tampon = b""   # satür bazlı çözümlleme: UTF-8 karakteri asla bölünmez
    while True:
      parca = yanit.read(4096)
      if not parca:
        break
      tampon += parca
      while b"\n" in tampon:
        ham, tampon = tampon.split(b"\n", 1)
        satir = ham.decode("utf-8", "replace").strip()
        if not satir.startswith("data:"):
          continue
        govde = satir[5:].strip()
        if govde == "[DONE]":
          return
        try:
          nesne = json.loads(govde)
        except Exception:
          continue
        secim = (nesne.get("choices") or [{}])[0]
        delta = secim.get("delta") or {}
        t = delta.get("content")
        if t:
          yaz(t)
        hata_metni = nesne.get("error")
        if hata_metni:
          hata((hata_metni.get("message") if isinstance(hata_metni, dict)
                else str(hata_metni)) + " — rate limit/kota olabilir")
          return
  finally:
    try:
      yanit.close()
    except Exception:
      pass


# ── /api/dosya: metin + zip + docx desteği ──
OKUNABILIR = {".txt", ".md", ".py", ".js", ".ts", ".json", ".html", ".css",
              ".go", ".java", ".c", ".cpp", ".h", ".cs", ".rs", ".sh", ".bat",
              ".yml", ".yaml", ".toml", ".ini", ".csv", ".xml", ".sql", ".log"}


def dosya_bloklari(yol, icerik):
  """Bayt içeriği {yol, blok} parçalarına çevirir."""
  uzanti = os.path.splitext(yol)[1].lower()
  if uzanti == ".docx":
    try:
      with zipfile.ZipFile(icerik) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        metin = re.sub(r"</w:p>", "\n", xml)
        metin = re.sub(r"<[^>]+>", "", metin)
        return [{"yol": yol, "blok": "DOSYA: " + yol + "\n" + metin[:60000]}]
    except Exception as h:
      return [{"yol": yol, "blok": "DOSYA: " + yol + "\n(docx okunamadı: %s)" % h}]
  if uzanti == ".zip":
    cikti = []
    try:
      with zipfile.ZipFile(icerik) as z:
        for ad in z.namelist()[:60]:
          if ad.endswith("/"):
            continue
          u = os.path.splitext(ad)[1].lower()
          if u in OKUNABILIR or u in (".docx",):
            b = z.read(ad)
            if len(b) > 300000:
              continue
            cikti.extend(dosya_bloklari(ad, b))
      return cikti or [{"yol": yol,
                        "blok": "ZIP: okunabilir dosya bulunamadı: " + yol}]
    except Exception as h:
      return [{"yol": yol, "blok": "ZIP okunamadı (%s): %s" % (yol, h)}]
  if uzanti in OKUNABILIR:
    metin = icerik.decode("utf-8", "replace")
    return [{"yol": yol,
             "blok": "DOSYA: " + yol + "\n" + metin[:120000]}]
  return [{"yol": yol,
           "blok": "DOSYA: " + yol + "\n(alt desteklenmiyor — metin olarak okunamadı)"}]


class Isleyici(BaseHTTPRequestHandler):
  protocol_version = "HTTP/1.1"

  def _json(self, nesne, kod=200):
    govde = json.dumps(nesne, ensure_ascii=False).encode("utf-8")
    self.send_response(kod)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(govde)))
    self.end_headers()
    self.wfile.write(govde)

  def do_GET(self):
    if self.path == "/api/saglayicilar":
      return self._json({"saglayicilar": SAG})
    if self.path == "/api/ayarlar":
      with AYAR_KILIDI:
        kopya = {k: ("…" if k != "nvidia" and v and len(v) > 8 else v)
                 for k, v in AYAR["anahtarlar"].items()}
      return self._json({"ok": True, "anahtarlar": AYAR["anahtarlar"],
                         "modeller": MODELLER_KILIT, "ekstra": AYAR["ekstra"]})
    if self.path == "/api/saglik":
      return self._json({"ollama": False})
    if self.path in ("/", "/bot_masasi.html"):
      try:
        govde = open(os.path.join(KLASOR, "bot_masasi.html"), "rb").read()
      except Exception:
        govde = b"<h1>bot_masasi.html bulunamadi</h1>"
      self.send_response(200)
      self.send_header("Content-Type", "text/html; charset=utf-8")
      self.send_header("Cache-Control", "no-store")
      self.send_header("Content-Length", str(len(govde)))
      self.end_headers()
      self.wfile.write(govde)
      return
    self._json({"hata": "bilinmeyen yol"}, 404)

  def do_POST(self):
    if self.path == "/api/sohbet":
      uzunluk = int(self.headers.get("Content-Length", 0))
      veri = json.loads(self.rfile.read(uzunluk).decode("utf-8"))
      pid = veri.get("pid", "")
      anahtar_grubu = SAG_almak(pid)
      key = (veri.get("key") or "").strip()
      if not key and anahtar_grubu:
        key = (AYAR["anahtarlar"].get(anahtar_grubu) or "").strip()
      if not key and anahtar_grubu == "nvidia":
        key = NVIDIA_GOMULU
      model = veri.get("model") or ""
      if pid in MODELLER_KILIT:
        model = MODELLER_KILIT[pid]
      self.send_response(200)
      self.send_header("Content-Type", "text/event-stream; charset=utf-8")
      self.send_header("Cache-Control", "no-cache")
      self.send_header("Connection", "close")
      self.end_headers()

      kilit = threading.Lock()

      def yaz(t):
        try:
          with kilit:
            parc = json.dumps({"t": t}, ensure_ascii=False).encode("utf-8")
            self.wfile.write(b"data: " + parc + b"\n\n")
            self.wfile.flush()
        except Exception:
          pass

      def hata(m):
        try:
          with kilit:
            parc = json.dumps({"h": m}, ensure_ascii=False).encode("utf-8")
            self.wfile.write(b"data: " + parc + b"\n\n")
            self.wfile.flush()
        except Exception:
          pass

      try:
        sohbet_akisi(pid, model, key, veri.get("sistem") or "",
                     veri.get("mesajlar") or [], yaz, hata)
      except (BrokenPipeError, ConnectionResetError):
        pass
      except Exception as e:
        hata("Sunucu hatası: " + str(e))
      return

    if self.path == "/api/dosya":
      try:
        cevap_baslik = self.headers.get("Content-Type", "")
        # multipart/form-data el ile ayrıştır (yalnız tek dosya beklenir)
        govde = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        m = re.search(rb'name="dosya"; filename="([^"]+)"', govde)
        if not m:
          return self._json({"hata": "dosya bulunamadı (form alanı 'dosya' olmalı)"})
        ad = m.group(1).decode("utf-8", "replace")
        # başlıklar bittikten sonraki boş satırdan itibaren dosya gövdesi
        sonrasi = govde[m.end():]
        bos = sonrasi.find(b"\r\n\r\n")
        if bos == -1:
          return self._json({"hata": "multipart gövdesi çözümlenemedi"})
        govde_ici = sonrasi[bos + 4:]
        bloklar = dosya_bloklari(ad, govde_ici)
        tur = "zip" if ad.lower().endswith(".zip") else "tek"
        return self._json({"tur": tur, "dosyalar": bloklar})
      except Exception as e:
        return self._json({"hata": str(e)})
    self._json({"hata": "bilinmeyen yol"}, 404)

  def log_message(self, *a):
    pass


def SAG_almak(pid):
  for p in SAG:
    if p["id"] == pid:
      return p.get("anahtar_grubu") or (p["id"] if p.get("anahtar_gerekli") else "")
  return ""


def main():
  sunucu = ThreadingHTTPServer(("127.0.0.1", PORT), Isleyici)
  print("SINIRSIZ MASA sunucusu: http://127.0.0.1:%d" % PORT)
  print("(Kapatmak için Ctrl+C)")
  # v5.3.1: tarayıcıyı sunucu AYAKTA olduktan sonra aç — sayfa boş açılıp
  # F5 yemesisini engeller (eskiden .bat tarayıcıyı sunucudan ÖNCE açıyordu)
  threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:%d/" % PORT)).start()
  try:
    sunucu.serve_forever()
  except KeyboardInterrupt:
    print("\nKapandı.")


if __name__ == "__main__":
  main()
