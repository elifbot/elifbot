# -*- coding: utf-8 -*-
"""sir_tara.py — depoya sır sızmasını CI'da engeller.

Kural: hiçbir dosyada canlı anahtar olmayacak. Bulunursa çıkış kodu 1.
Kullanım: python3 bot/tools/sir_tara.py [kok]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DESENLER = {
    "google_ai_key": re.compile(r"AQ\.[A-Za-z0-9_\-]{25,}"),
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_\-]{24,}"),
    "nvidia_key": re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "pem": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
ATLA = {".git", "node_modules", "__pycache__", ".pytest_cache", "runs", "konsey"}
METIN = {".py", ".md", ".json", ".txt", ".yml", ".yaml", ".sh", ".toml", ".cfg", ".ini", ".example"}


def tara(kok: Path) -> list[str]:
    bulgular: list[str] = []
    for p in kok.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in METIN:
            continue
        if any(x in p.parts for x in ATLA):
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            metin = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ad, d in DESENLER.items():
            for m in d.finditer(metin):
                bulgular.append(f"{p.relative_to(kok)}: {ad} ({m.group(0)[:8]}…)")
    return bulgular


def main() -> int:
    kok = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    bulgular = tara(kok)
    if not bulgular:
        print("sır taraması: temiz")
        return 0
    print(f"sır taraması: {len(bulgular)} bulgu", file=sys.stderr)
    for b in bulgular[:40]:
        print(f"  {b}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
