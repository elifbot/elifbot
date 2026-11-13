"""Ayar yükleyici: config.yaml + .env (Sıkı Çevresel Değişken İzolasyonu).

Güvenlik Kuralı (Environment Isolation):
  • Tüm API anahtarları, şifreler ve tokenlar YALNIZCA `.env` / `os.getenv()`
    üzerinden okunur.
  • `config.yaml` içine yanlışlıkla API anahtarı yazılsa bile yoksayılır/silinir.
  • Okunan tüm anahtarlar `security.register_secret` ile maskeleme motoruna
    kaydedilir; böylece log veya hata mesajlarına sızması imkânsız hale gelir.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from .security import install_log_masking, register_secret

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

install_log_masking()

BASE_DIR = Path(__file__).resolve().parent.parent

_FORBIDDEN_YAML_KEYS = {
    "api",
    "api_key",
    "api_secret",
    "binance_api_key",
    "binance_api_secret",
    "okx_api_key",
    "okx_api_secret",
    "okx_api_passphrase",
    "telegram_bot_token",
    "discord_webhook_url",
    "pagerduty_routing_key",
    "llm_api_key",
}


def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path) if path else BASE_DIR / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # YAML içinde yanlışlıkla tanımlanmış tüm anahtar alanlarını temizle
    for k in list(cfg.keys()):
        if k.lower() in _FORBIDDEN_YAML_KEYS:
            cfg.pop(k, None)

    mode = os.getenv("MODE", "").strip().lower()
    if mode in ("paper", "testnet", "live"):
        cfg.setdefault("genel", {})["mod"] = mode

    api_cfg = {
        "binance_key": os.getenv("BINANCE_API_KEY", ""),
        "binance_secret": os.getenv("BINANCE_API_SECRET", ""),
        "okx_key": os.getenv("OKX_API_KEY", ""),
        "okx_secret": os.getenv("OKX_API_SECRET", ""),
        "okx_passphrase": os.getenv("OKX_API_PASSPHRASE", ""),
        "cryptopanic_key": os.getenv("CRYPTOPANIC_KEY", ""),
        "telegram_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat": os.getenv("TELEGRAM_CHAT_ID", ""),
        "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL", ""),
        "pagerduty_routing_key": os.getenv("PAGERDUTY_ROUTING_KEY", ""),
        "llm_url": os.getenv("LLM_API_URL", ""),
        "llm_key": os.getenv("LLM_API_KEY", ""),
        "llm_model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
    }

    # Tüm gizli anahtarları maskeleme havuzuna kaydet (No Secret Leakage)
    for key_name, val in api_cfg.items():
        if key_name not in ("telegram_chat", "llm_url", "llm_model") and val:
            register_secret(val)

    cfg["api"] = api_cfg
    return cfg
