# -*- coding: utf-8 -*-
"""indeks.py — havuzun tam envanteri (model çağrısı yok, tamamen deterministik).

Çıktı:
  havuz/indeks.jsonl : dosya başına bir satır (yol, sha256, boyut, satır, etiketler)
  havuz/ozet.md      : etiket dağılımı
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
HEDEF_KLASORLER = ("drive/toplama", "bot", "docs", "kadro", "havuz", "panel", "yamalar")
METIN = {".py", ".md", ".json", ".txt", ".yml", ".yaml", ".html", ".css", ".sh", ".patch",
         ".example", ".toml", ".cfg", ".ini"}
ATLA = {"__pycache__", ".git", ".pytest_cache", "node_modules", "runs"}

# etiket -> desen (küçük harf aranır)
ETIKETLER: dict[str, re.Pattern] = {
    "stop": re.compile(r"stop|zarar_kes|hard_stop|reduce_only"),
    "trailing": re.compile(r"trailing|trail_|be_kar|breakeven|kilit"),
    "giris": re.compile(r"sinyal|signal|entry|giris|kirilim|breakout"),
    "hacim": re.compile(r"hacim|volume|delta|vwap"),
    "rejim": re.compile(r"rejim|regime|trend|sikisma|squeeze|volatil|atr"),
    "risk": re.compile(r"risk|teminat|margin|kaldirac|leverage|liquid|tasfiye"),
    "veri": re.compile(r"tick|websocket|ws_|feed|besleme|kline|candle|backtest|replay"),
    "icra": re.compile(r"emir|order|post_only|maker|taker|slippage|kayma|retry|idempot"),
    "ops": re.compile(r"log|monitor|alert|restart|health|docker|systemd|ci\b|workflow"),
    "ai": re.compile(r"openai|gemini|nvidia|ollama|prompt|llm|model_"),
}


def _etiketle(metin: str) -> dict[str, int]:
    kucuk = metin.lower()
    return {ad: len(r.findall(kucuk)) for ad, r in ETIKETLER.items() if r.search(kucuk)}


def tara() -> list[dict]:
    kayitlar: list[dict] = []
    for klasor in HEDEF_KLASORLER:
        kok = KOK / klasor
        if not kok.exists():
            continue
        for p in sorted(kok.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in METIN:
                continue
            if any(parca in ATLA for parca in p.parts):
                continue
            try:
                ham = p.read_bytes()
            except OSError:
                continue
            if len(ham) > 2_000_000:
                continue
            try:
                metin = ham.decode("utf-8", errors="ignore")
            except Exception:
                continue
            kayitlar.append({
                "yol": str(p.relative_to(KOK)),
                "sha256": hashlib.sha256(ham).hexdigest()[:16],
                "bayt": len(ham),
                "satir": metin.count("\n") + 1,
                "etiket": _etiketle(metin),
            })
    return kayitlar


def yaz(kayitlar: list[dict]) -> Path:
    cikti = KOK / "havuz" / "indeks.jsonl"
    with open(cikti, "w", encoding="utf-8") as fh:
        for k in kayitlar:
            fh.write(json.dumps(k, ensure_ascii=False) + "\n")
    return cikti


def ozet_md(kayitlar: list[dict]) -> str:
    toplam: dict[str, int] = {}
    dosya: dict[str, int] = {}
    for k in kayitlar:
        for ad, n in k["etiket"].items():
            toplam[ad] = toplam.get(ad, 0) + n
            dosya[ad] = dosya.get(ad, 0) + 1
    satir = ["# Havuz özeti", "",
             f"- Dosya: **{len(kayitlar)}**",
             f"- Toplam boyut: **{sum(k['bayt'] for k in kayitlar) / 1048576:.1f} MB**",
             f"- Satır: **{sum(k['satir'] for k in kayitlar):,}**", "",
             "| Etiket | Geçiş | Dosya |", "|---|---|---|"]
    for ad, n in sorted(toplam.items(), key=lambda kv: -kv[1]):
        satir.append(f"| {ad} | {n:,} | {dosya[ad]} |")
    return "\n".join(satir) + "\n"


def main() -> None:
    kayitlar = tara()
    cikti = yaz(kayitlar)
    (KOK / "havuz" / "ozet.md").write_text(ozet_md(kayitlar), encoding="utf-8")
    print(f"{len(kayitlar)} dosya indekslendi → {cikti.relative_to(KOK)}")


if __name__ == "__main__":
    main()
