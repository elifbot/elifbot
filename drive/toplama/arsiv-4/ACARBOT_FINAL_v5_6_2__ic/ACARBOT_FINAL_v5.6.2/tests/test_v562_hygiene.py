"""v5.6.2 paket hijyeni testleri (ağ gerektirmez).

Kapsam: --help çökmesi, TickVerifier ağ bağımsızlığı, haber koruması
sağlık sinyali, bağımlılık dosyaları, Windows başlatıcıları, veri bütçesi.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from core.config import NewsGuardConfig
from infra.tick_verify import UNVERIFIED, TickVerifier
from safety.news_guard import NewsGuard
from tools.data_budget import estimate

ROOT = Path(__file__).resolve().parents[1]
MIN = 60_000


# ----------------------------------------------------------------------
# 1) --help çökmesi (argparse '%' biçimlendirme hatası)
# ----------------------------------------------------------------------

def test_cli_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "app.main", "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr[-500:]
    assert "ValueError" not in result.stderr
    assert "--dca" in result.stdout


def test_cli_help_has_no_bare_percent_in_help_strings():
    """Her `help=` metnindeki '%' ya '%%' ya da %(ad)s biçimi olmalı."""
    import re
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for chunk in re.findall(r"help\s*=\s*((?:[fFrR]?[\"'].*?[\"']\s*)+)", source, re.S):
        text = "".join(re.findall(r"[\"']([^\"']*)[\"']", chunk))
        stripped = text.replace("%%", "")
        assert not re.search(r"%(?!\([a-z_]+\)[sdr])", stripped), text


# ----------------------------------------------------------------------
# 2) TickVerifier: auto_fetch=False ağa ÇIKMAZ
# ----------------------------------------------------------------------

def test_tick_verifier_auto_fetch_false_never_hits_network(monkeypatch):
    verifier = TickVerifier(policy="strict", auto_fetch=False)

    def boom(*_a, **_k):
        raise AssertionError("ağ çağrısı yapılmamalıydı")

    monkeypatch.setattr(verifier, "fetch_futures_ticks", boom)
    allowed, report = verifier.filter_grid({"binance:BTCUSDT": 0.1})
    assert allowed == {}
    assert report["unverified"] == 1
    assert verifier.verify("binance:BTCUSDT", 0.1).status == UNVERIFIED


def test_tick_verifier_default_still_fetches(monkeypatch):
    """Üretim davranışı değişmedi: varsayılan auto_fetch=True."""
    verifier = TickVerifier()
    calls = []
    monkeypatch.setattr(
        verifier, "fetch_futures_ticks",
        lambda: calls.append(1) or {},
    )
    verifier.verify_many({"binance:BTCUSDT": 0.1})
    assert calls == [1]


# ----------------------------------------------------------------------
# 3) Haber koruması: sessiz zayıflama görünür olmalı
# ----------------------------------------------------------------------

def _guard(fetch, **overrides):
    return NewsGuard(replace(NewsGuardConfig(), **overrides), fetch_json=fetch)


def test_news_guard_not_degraded_before_first_refresh():
    guard = _guard(lambda url: [])
    assert guard.status()["degraded"] is False


def test_news_guard_degraded_when_never_loaded_fail_open():
    def boom(url):
        raise OSError("ağ yok")

    guard = _guard(boom)
    guard.refresh(1_000_000)
    status = guard.status()
    assert status["degraded"] is True
    assert "FAIL-OPEN" in status["degraded_reason"]


def test_news_guard_degraded_message_when_fail_closed():
    def boom(url):
        raise OSError("ağ yok")

    guard = _guard(boom, fail_closed=True)
    guard.refresh(1_000_000)
    degraded, reason = guard.health(1_000_000)
    assert degraded and "ENGELLENİR" in reason


def test_news_guard_degraded_when_data_goes_stale():
    guard = _guard(lambda url: [])
    guard.refresh(1_000_000)               # başarılı (boş liste de başarı)
    assert guard.health(1_000_000)[0] is False
    stale = 1_000_000 + int(guard.config.refresh_seconds * 1000) * 3 + MIN
    degraded, reason = guard.health(stale)
    assert degraded and "bayat" in reason


def test_news_guard_disabled_is_never_degraded():
    guard = _guard(lambda url: [], enabled=False)
    assert guard.health(10**12) == (False, "")


# ----------------------------------------------------------------------
# 4) Bağımlılık dosyaları
# ----------------------------------------------------------------------

def _req_names(name: str) -> set[str]:
    out = set()
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        out.add(line.split("==")[0].lower())
    return out


def test_runtime_requirements_are_minimal():
    names = _req_names("requirements.txt")
    assert names == {"websockets"}
    assert "aiohttp" not in names and "pytest" not in names


def test_dev_requirements_hold_pytest():
    assert "pytest" in _req_names("requirements-dev.txt")


def test_aiohttp_not_imported_anywhere():
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or path.name == "test_v562_hygiene.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "import aiohttp" not in text and "from aiohttp" not in text, path


# ----------------------------------------------------------------------
# 5) Windows başlatıcıları güncel
# ----------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "run_paper_windows.bat", "run_test_15min.bat", "run_testnet_session.bat",
])
def test_windows_launchers_exist_and_are_current(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    assert "v1.1" not in text
    assert "--profile apex" not in text
    assert "\r\n" in (ROOT / name).read_bytes().decode("utf-8")


def test_paper_launcher_prefers_py_launcher_and_kasa1000():
    text = (ROOT / "run_paper_windows.bat").read_text(encoding="utf-8")
    assert "py -3" in text and "--profile kasa1000" in text


# ----------------------------------------------------------------------
# 6) Veri bütçesi aracı
# ----------------------------------------------------------------------

def test_data_budget_matches_report_figure():
    result = estimate(symbols=50, months=12, intervals=("5m",))
    assert result["total_candles"] == 5_256_000     # rapordaki ~5,25 milyon mum
    assert result["total_requests"] == 52_560


def test_data_budget_rejects_bad_input():
    with pytest.raises(ValueError):
        estimate(0, 12, ("5m",))
    with pytest.raises(ValueError):
        estimate(10, 12, ("7m",))
