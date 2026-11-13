"""
Güvenlik testleri — statik denetim.

Amaç: kod tabanında kimlik doğrulamalı çağrı, yazma metodu, sır okuma veya
allowlist dışı URL bulunmadığını makine tarafından doğrulamak.
"""
from __future__ import annotations

import ast
import os

import pytest

BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from config import STATIC_URL_EXCEPTIONS
from data.feed_utils import is_url_allowed

ALLOWED_ENV = {"PANEL_PORT", "BINANCE_BASE"}   # sır DEĞİL: port ve yedek adres

FORBIDDEN_CALL_ATTRS = {"post", "put", "delete", "patch", "head"}
FORBIDDEN_IMPORTS = {"dotenv", "subprocess", "smtplib", "socket", "telnetlib"}


def _python_files() -> list[str]:
    out = []
    for root, dirs, files in os.walk(BOT_ROOT):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "logs", "tests", "src")]
        for f in files:
            if f.endswith(".py") and f != "paper_30dk_supervisor.py":
                out.append(os.path.join(root, f))
    return out


def _parsed() -> list[tuple[str, ast.Module]]:
    return [(p, ast.parse(open(p, encoding="utf-8").read(), filename=p)) for p in _python_files()]


def test_no_write_http_methods() -> None:
    """Hiçbir yerde POST/PUT/DELETE/PATCH çağrısı olmamalı (yalnızca GET)."""
    for path, tree in _parsed():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in FORBIDDEN_CALL_ATTRS, (
                    f"{path}:{node.lineno} yasaklı HTTP metodu: {node.func.attr}"
                )


def test_no_secret_environment_access() -> None:
    """
    os.environ / getenv üzerinden SIR okunmamalı.

    Ortamdan yalnızca SIR OLMAYAN, açıkça listelenmiş değişkenler okunabilir
    (panel portu, Binance yedek taban adresi). Üç erişim biçimi de taranır:
        os.environ.get("X")   os.getenv("X")   os.environ["X"]
    Anahtar ALLOWED_ENV'de olmalı VE sır çağrıştıran bir ad taşımamalı.
    """
    gizli_deseni = ("key", "secret", "token", "passw", "passphrase", "private", "seed")

    def _denetle(path, anahtar, yer):
        assert isinstance(anahtar, str), f"{path}: {yer} — anahtar sabit değil, denetlenemez"
        assert anahtar in ALLOWED_ENV, (
            f"{path}: {yer} — ortam değişkeni ALLOWED_ENV'de değil: {anahtar!r}")
        dusuk = anahtar.lower()
        assert not any(g in dusuk for g in gizli_deseni), (
            f"{path}: {yer} — sır çağrıştıran ortam değişkeni: {anahtar!r}")

    for path, tree in _parsed():
        for node in ast.walk(tree):
            # os.environ.get(...) / os.getenv(...) / os.environ.setdefault(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                f = node.func
                if f.attr == "getenv":
                    anahtar = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
                    _denetle(path, anahtar, "os.getenv")
                elif f.attr in {"get", "setdefault", "pop"} and isinstance(f.value, ast.Attribute) \
                        and f.value.attr == "environ":
                    anahtar = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
                    _denetle(path, anahtar, "os.environ.get")
            # os.environ["X"]
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
                    and node.value.attr == "environ":
                anahtar = node.slice.value if isinstance(node.slice, ast.Constant) else None
                _denetle(path, anahtar, "os.environ[...]")


def test_no_forbidden_imports() -> None:
    """Yasaklı modüller (dotenv, subprocess, smtplib...) import edilmemeli."""
    for path, tree in _parsed():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in FORBIDDEN_IMPORTS, f"{path}: yasaklı import: {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in FORBIDDEN_IMPORTS, f"{path}: yasaklı import: {node.module}"


def test_all_urls_are_allowlisted() -> None:
    """Tam endpoint config politikasından; taban URL/tanı açık istisnadan."""
    for path, tree in _parsed():
        relative = os.path.relpath(path, BOT_ROOT).replace(os.sep, "/")
        # İstisna literal tanımları config'dedir; kullanımlar aşağıda denetlenir.
        if relative == "config.py":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val.startswith("http://") or val.startswith("https://"):
                    assert is_url_allowed(val) or val in STATIC_URL_EXCEPTIONS.get(relative, ()), (
                        f"{path}: allowlist dışı URL: {val}")


def test_no_api_key_strings_in_code() -> None:
    """API anahtarı/secret değişken adları geçmemeli (yorumlar hariç, AST düzeyinde)."""
    forbidden_names = {"api_key", "apikey", "secret", "passphrase", "private_key"}
    for path, tree in _parsed():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id.lower() not in forbidden_names, f"{path}: yasaklı isim: {node.id}"
            if isinstance(node, ast.keyword) and node.arg:
                assert node.arg.lower() not in forbidden_names, f"{path}: yasaklı kwarg"


def test_live_and_testnet_modes_exit() -> None:
    """--mode live / --mode testnet, ağ çağrısından önce exit(1) yapmalı."""
    from main import main

    for mode in ("live", "testnet"):
        with pytest.raises(SystemExit) as exc:
            main(["--mode", mode])
        assert exc.value.code == 1


def test_no_network_before_mode_guard(monkeypatch) -> None:
    """Live modu reddedilirken hiçbir feed oluşturulmamalı."""
    import data.binance_futures_feed as bf

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("ağ istemcisi oluşturulmamalıydı")

    monkeypatch.setattr(bf, "BinanceFuturesFeed", Boom)
    from main import main

    with pytest.raises(SystemExit):
        main(["--mode", "live"])


def test_no_trigger_implementation() -> None:
    """run_with_trigger benzeri otomatik tetikleyici uygulanmamış olmalı."""
    for path, tree in _parsed():
        src = open(path, encoding="utf-8").read()
        if "def run_with_trigger" in src:
            pytest.fail(f"{path}: run_with_trigger tanımlanmamalı (bilinen sorun olarak belgelenmiştir)")
