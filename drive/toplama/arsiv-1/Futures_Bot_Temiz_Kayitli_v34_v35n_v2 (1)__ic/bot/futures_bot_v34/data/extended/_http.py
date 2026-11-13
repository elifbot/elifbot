"""v18 — extended feed'ler için allowlist'li public GET yardımcısı (yalnız GET, anahtarsız)."""
from __future__ import annotations
import requests
from data.feed_utils import ensure_url_allowed
from data.extended import DataUnavailableError

def get_json(url: str, params: dict, session=None):
    ensure_url_allowed(url)
    s = session or requests.Session()
    try:
        r = s.get(url, params=params, timeout=15)
    except requests.RequestException as exc:
        raise DataUnavailableError(f"ag hatasi: {url}: {exc}") from exc
    if r.status_code != 200:
        raise DataUnavailableError(f"HTTP {r.status_code}: {url}")
    try:
        return r.json()
    except ValueError as exc:
        raise DataUnavailableError(f"bozuk JSON: {url}") from exc

def okx_data(payload):
    if not isinstance(payload, dict) or payload.get("code") != "0" or not payload.get("data"):
        raise DataUnavailableError(f"OKX gecersiz yanit: {str(payload)[:120]}")
    return payload["data"][0]
