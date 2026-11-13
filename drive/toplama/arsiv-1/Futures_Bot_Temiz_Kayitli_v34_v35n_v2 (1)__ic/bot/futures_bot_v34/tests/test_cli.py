"""Komut satırı kullanılabilirlik testleri."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_ws_bot_help_calisir() -> None:
    """Yüzde işaretli yardım metinleri argparse'i çökertmemeli."""
    kok = Path(__file__).resolve().parents[1]
    sonuc = subprocess.run(
        [sys.executable, "ws_bot.py", "--help"],
        cwd=kok,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert sonuc.returncode == 0, sonuc.stderr
    assert "--giris" in sonuc.stdout
    assert "--pencere-ms" in sonuc.stdout
