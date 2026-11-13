"""Yapılandırma yükleme ve doğrulama.

``config.yaml`` yalnızca hassas olmayan ayarları içerir. API anahtarları ve
webhook/token değerleri yalnızca ortam değişkenlerinden alınır. YAML içine
yanlışlıkla eklenen sırlar iç içe bölümlerde bile yüklenmez.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

import yaml

from .security import install_log_masking, register_secret

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv isteğe bağlı çalışma zamanı
    pass
else:
    load_dotenv(BASE_DIR / ".env")

install_log_masking()


class ConfigError(ValueError):
    """Güvenli olmayan veya geçersiz yapılandırma hatası."""


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
    "dashboard_token",
    "llm_api_key",
}
_SYMBOL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+(?::[A-Z0-9]+)?$")
# Tek doğruluk kaynağı: kapalı-mum filtresi de bu eşlemeyi kullanır.
TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
_SUPPORTED_TIMEFRAMES = set(TIMEFRAME_MS)
LIVE_CONFIRMATION = "YES_I_RISK_REAL_MONEY"


def _without_yaml_secrets(value: Any) -> Any:
    """Sır benzeri anahtarları YAML ağacının her seviyesinden çıkarır."""
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN_YAML_KEYS:
                continue
            clean[str(key)] = _without_yaml_secrets(item)
        return clean
    if isinstance(value, list):
        return [_without_yaml_secrets(item) for item in value]
    return value


def _number(cfg: dict, section: str, key: str, *, minimum: float | None = None,
            maximum: float | None = None) -> float:
    try:
        value = float(cfg[section][key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"{section}.{key} sayısal olmalı") from exc
    if not math.isfinite(value):
        raise ConfigError(f"{section}.{key} sonlu bir sayı olmalı")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{section}.{key} en az {minimum} olmalı")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{section}.{key} en fazla {maximum} olmalı")
    return value


def _default_number(cfg: dict, section: str, key: str, default: float, **limits) -> float:
    cfg[section].setdefault(key, default)
    return _number(cfg, section, key, **limits)


def _integer(cfg: dict, section: str, key: str, *, minimum: int = 1,
             maximum: int = 1_000_000) -> int:
    value = _number(cfg, section, key, minimum=minimum, maximum=maximum)
    if not value.is_integer():
        raise ConfigError(f"{section}.{key} tam sayı olmalı")
    return int(value)


def _boolean(cfg: dict, section: str, key: str, default: bool) -> bool:
    value = cfg[section].setdefault(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{section}.{key} true veya false olmalı")
    return value


def _enum(cfg: dict, section: str, key: str, default: str, allowed: set[str]) -> str:
    value = str(cfg[section].setdefault(key, default)).strip().lower()
    if value not in allowed:
        raise ConfigError(f"{section}.{key} desteklenen değerler: {', '.join(sorted(allowed))}")
    cfg[section][key] = value
    return value


def validate_config(cfg: dict, api: dict | None = None) -> None:
    """Kritik ayarları başlangıçta, emir gönderilmeden önce doğrular."""
    if not isinstance(cfg, dict):
        raise ConfigError("Yapılandırmanın kökü bir YAML nesnesi olmalı")
    for section in ("genel", "risk", "sinyal", "boyutlandirma"):
        if not isinstance(cfg.get(section), dict):
            raise ConfigError(f"Eksik veya geçersiz bölüm: {section}")
    for section in (
        "mtf_filtre", "bildirimler", "failover", "veritabani", "health_check",
        "sigorta", "emirler", "makine_ogrenmesi", "para_akisi", "arbitraj",
        "haberler", "optimizasyon", "panel", "hiz", "paper", "islem_plani", "cikis",
        "futures", "shadow_lab", "pdf_v2", "pdf_v3",
    ):
        value = cfg.setdefault(section, {})
        if not isinstance(value, dict):
            raise ConfigError(f"Geçersiz bölüm: {section}")

    general = cfg["genel"]
    mode = str(general.get("mod", "paper")).lower()
    if mode not in {"paper", "testnet", "live"}:
        raise ConfigError("genel.mod yalnızca paper, testnet veya live olabilir")
    general["mod"] = mode

    exchanges = general.get("borsalar")
    if not isinstance(exchanges, list) or not exchanges:
        raise ConfigError("genel.borsalar en az bir borsa içermeli")
    normalized_exchanges = [str(item).strip().lower() for item in exchanges]
    if len(set(normalized_exchanges)) != len(normalized_exchanges):
        raise ConfigError("genel.borsalar yinelenen borsa içeremez")
    if any(name not in {"binance", "okx"} for name in normalized_exchanges):
        raise ConfigError("Desteklenen borsalar: binance, okx")
    general["borsalar"] = normalized_exchanges

    symbols = general.get("semboller")
    if not isinstance(symbols, list) or not symbols:
        raise ConfigError("genel.semboller en az bir parite içermeli")
    normalized_symbols = [str(item).strip().upper() for item in symbols]
    if len(set(normalized_symbols)) != len(normalized_symbols):
        raise ConfigError("genel.semboller yinelenen parite içeremez")
    if any(not _SYMBOL_RE.fullmatch(symbol) for symbol in normalized_symbols):
        raise ConfigError("Sembol biçimi örneği: BTC/USDT veya BTC/USDT:USDT")
    general["semboller"] = normalized_symbols

    timeframe = str(general.get("zaman_dilimi", "5m"))
    if timeframe not in _SUPPORTED_TIMEFRAMES:
        raise ConfigError(f"Desteklenmeyen zaman dilimi: {timeframe}")
    _integer(cfg, "genel", "kaldıraç", minimum=1, maximum=50)
    _boolean(cfg, "genel", "short_izni", True)
    _default_number(cfg, "paper", "bakiye", 100000, minimum=10, maximum=1e9)
    _boolean(cfg, "paper", "gercekci_yurutme", True)
    _boolean(cfg, "paper", "funding_aktif", True)

    _boolean(cfg, "mtf_filtre", "aktif", True)
    mtf_frames = cfg["mtf_filtre"].setdefault("zaman_dilimleri", ["1h", "4h"])
    if not isinstance(mtf_frames, list) or not mtf_frames:
        raise ConfigError("mtf_filtre.zaman_dilimleri en az bir zaman dilimi içermeli")
    if any(frame not in _SUPPORTED_TIMEFRAMES for frame in mtf_frames):
        raise ConfigError("mtf_filtre.zaman_dilimleri desteklenmeyen değer içeriyor")
    if any(TIMEFRAME_MS[frame] < TIMEFRAME_MS[timeframe] for frame in mtf_frames):
        raise ConfigError("MTF zaman dilimleri işlem zaman diliminden küçük olamaz")
    if len(set(mtf_frames)) != len(mtf_frames):
        raise ConfigError("mtf_filtre.zaman_dilimleri yinelenen değer içeremez")
    bearish = _default_number(cfg, "mtf_filtre", "dusus_engelleme_esigi", -15, minimum=-100, maximum=0)
    bullish = _default_number(cfg, "mtf_filtre", "yukselis_engelleme_esigi", 15, minimum=0, maximum=100)
    if bearish >= 0 or bullish <= 0:
        raise ConfigError("MTF düşüş eşiği negatif, yükseliş eşiği pozitif olmalı")

    _enum(cfg, "risk", "stop_modeli", "fiyat_yuzde", {"marj", "fiyat_yuzde"})
    _enum(cfg, "risk", "marj_modu", "isolated", {"cross", "isolated"})
    _default_number(cfg, "risk", "capraz_max_kullanim_yuzde", 95.0, minimum=10.0, maximum=100.0)
    _default_number(cfg, "risk", "capraz_min_serbest_usdt", 50.0, minimum=0.0, maximum=1e9)
    _boolean(cfg, "risk", "firsat_takasi_aktif", False)
    _default_number(cfg, "risk", "firsat_takasi_min_dakika", 8.0, minimum=1.0, maximum=1440.0)
    _default_number(cfg, "risk", "erken_kar_kilit_tetik", 0.0, minimum=0.0, maximum=100.0)
    _default_number(cfg, "risk", "erken_kar_kilit_seviye", 0.12, minimum=0.0, maximum=100.0)
    _default_number(cfg, "risk", "zirve_kar_koruma_min_usdt", 0.0, minimum=0.0, maximum=10000.0)
    _default_number(cfg, "risk", "zirve_kar_koruma_orani", 0.48, minimum=0.05, maximum=0.90)
    _default_number(cfg, "risk", "atr_trailing_carpani", 0.0, minimum=0.0, maximum=20.0)
    _default_number(cfg, "risk", "marj_zarar_orani", 0.80, minimum=0.05, maximum=0.95)
    _default_number(cfg, "risk", "marj_stop_likidasyon_tamponu", 0.85, minimum=0.50, maximum=0.95)
    _number(cfg, "risk", "stop_loss_yuzde", minimum=0.01, maximum=50)
    _number(cfg, "risk", "gunluk_max_zarar_yuzde", minimum=0.01, maximum=100)
    _number(cfg, "risk", "haftalik_max_zarar_yuzde", minimum=0.01, maximum=100)
    _number(cfg, "risk", "kasa_giris_yuzde", minimum=0.01, maximum=100)
    _number(cfg, "risk", "toplam_marj_tavani_yuzde", minimum=0.01, maximum=100)
    _number(cfg, "risk", "max_kayma_yuzde", minimum=0, maximum=5)
    _number(cfg, "risk", "likidasyon_stop_tamponu", minimum=0.05, maximum=1)
    lock_trigger = _number(cfg, "risk", "kar_kilit_tetikleyici", minimum=0.01, maximum=1000)
    lock_level = _number(cfg, "risk", "kar_kilit_seviyesi", minimum=0, maximum=1000)
    if lock_level >= lock_trigger:
        raise ConfigError("kar_kilit_seviyesi, kar_kilit_tetikleyici değerinden küçük olmalı")
    _number(cfg, "risk", "trailing_yuzde", minimum=0.01, maximum=100)
    _number(cfg, "risk", "islem_basina_risk_yuzde", minimum=0.001, maximum=100)
    _default_number(cfg, "risk", "mola_saniye", 300, minimum=0, maximum=86400)
    _default_number(cfg, "risk", "ekleme_min_kar_yuzde", 0.25, minimum=0, maximum=100)
    _default_number(cfg, "risk", "kurtarma_min_zarar_yuzde", 0.5, minimum=0, maximum=100)
    atr_high = _default_number(cfg, "risk", "atr_yuksek_oynaklik_yuzde", 1.5, minimum=0.001, maximum=100)
    atr_extreme = _default_number(cfg, "risk", "atr_asiri_oynaklik_yuzde", 3, minimum=0.001, maximum=100)
    if atr_extreme < atr_high:
        raise ConfigError("atr_asiri_oynaklik_yuzde, atr_yuksek_oynaklik_yuzde'den küçük olamaz")
    for key, default in (
        ("sinirsiz_ekleme", True), ("capraz_kurtarma", True), ("dinamik_kaldirac", True),
        ("paper_genis_pozisyon_limiti", False),
    ):
        _boolean(cfg, "risk", key, default)
    _integer(cfg, "risk", "paper_max_pozisyon", minimum=1, maximum=10000)
    if "paper_ayni_yon_max_pozisyon" in cfg["risk"]:
        _integer(cfg, "risk", "paper_ayni_yon_max_pozisyon", minimum=1, maximum=10000)
    capital_pct = float(cfg["risk"]["kasa_giris_yuzde"])
    margin_cap = float(cfg["risk"]["toplam_marj_tavani_yuzde"])
    if capital_pct > margin_cap:
        raise ConfigError("kasa_giris_yuzde, toplam_marj_tavani_yuzde değerini aşamaz")

    for key in ("max_pozisyon", "mutlak_max_pozisyon", "ayni_yon_max_pozisyon", "max_kademe"):
        _integer(cfg, "risk", key, minimum=1, maximum=1000)
    if int(cfg["risk"]["mutlak_max_pozisyon"]) < int(cfg["risk"]["max_pozisyon"]):
        raise ConfigError("mutlak_max_pozisyon, max_pozisyon değerinden küçük olamaz")
    if int(cfg["risk"]["ayni_yon_max_pozisyon"]) > int(cfg["risk"]["mutlak_max_pozisyon"]):
        raise ConfigError("ayni_yon_max_pozisyon, mutlak_max_pozisyon değerini aşamaz")

    _boolean(cfg, "futures", "tum_pariteler", False)
    _boolean(cfg, "futures", "kripto_disi_filtre", True)
    _default_number(cfg, "futures", "min_kaldirac", 10, minimum=1, maximum=100)
    for key, default, low, high in (
        ("ws_grup_boyutu", 50, 1, 200),
        ("ws_derinlik_guncelleme_ms", 100, 100, 500),
        ("tarama_paralellik", 4, 1, 32),
        ("max_parite", 0, 0, 10000),
    ):
        cfg["futures"].setdefault(key, default)
        value = _integer(cfg, "futures", key, minimum=low, maximum=high)
        if key == "ws_derinlik_guncelleme_ms" and value not in {100, 250, 500}:
            raise ConfigError("futures.ws_derinlik_guncelleme_ms yalnız 100, 250 veya 500 olabilir")
    _default_number(cfg, "futures", "tarama_araligi_saniye", 300, minimum=15, maximum=86400)

    _boolean(cfg, "islem_plani", "aktif", True)
    _default_number(cfg, "islem_plani", "atr_stop_katsayi", 1.5, minimum=0.01, maximum=100)
    cfg["islem_plani"].setdefault("swing_mum", 20)
    _integer(cfg, "islem_plani", "swing_mum", minimum=2, maximum=1000)
    _default_number(cfg, "islem_plani", "swing_atr_buffer", 0.20, minimum=0, maximum=10)
    _default_number(cfg, "islem_plani", "max_stop_yuzde", 12.0, minimum=0.1, maximum=100)
    tp1_r = _default_number(cfg, "islem_plani", "tp1_r", 1.0, minimum=0.1, maximum=50)
    tp2_r = _default_number(cfg, "islem_plani", "tp2_r", 2.0, minimum=0.1, maximum=100)
    if tp2_r <= tp1_r:
        raise ConfigError("islem_plani.tp2_r, tp1_r'den büyük olmalı")
    _default_number(cfg, "islem_plani", "tp1_kapatma_orani", 0.50, minimum=0.05, maximum=0.95)

    _boolean(cfg, "cikis", "kosan_kar", True)
    _boolean(cfg, "cikis", "net_basabas_aktif", False)
    _default_number(cfg, "cikis", "net_kar_tamponu_usdt", 0.0, minimum=0, maximum=1000)
    _default_number(cfg, "cikis", "orderflow_kontrol_saniye", 1.0, minimum=0.1, maximum=60)
    _default_number(cfg, "cikis", "orderflow_min_kar_yuzde", 0.5, minimum=0, maximum=100)
    _default_number(cfg, "cikis", "orderflow_orani", 1.5, minimum=1.0, maximum=100)
    _default_number(cfg, "cikis", "orderflow_min_usdt", 1000.0, minimum=0, maximum=1e12)
    _default_number(
        cfg, "cikis", "orderflow_min_geri_cekilme_yuzde", 0.05,
        minimum=0, maximum=100,
    )
    _boolean(cfg, "cikis", "erken_bozulma_cikisi_aktif", False)
    _default_number(cfg, "cikis", "erken_bozulma_min_dakika", 18.0, minimum=1.0, maximum=1440.0)
    _default_number(
        cfg, "cikis", "erken_bozulma_uzatilan_dakika", 25.0, minimum=1.0, maximum=1440.0
    )
    _default_number(
        cfg, "cikis", "erken_bozulma_min_zarar_yuzde", 0.25, minimum=0.01, maximum=50.0
    )
    _default_number(cfg, "cikis", "erken_bozulma_ters_skor", 12.0, minimum=1.0, maximum=100.0)

    _boolean(cfg, "shadow_lab", "aktif", False)
    if cfg["shadow_lab"]["aktif"] and mode != "paper":
        raise ConfigError("shadow_lab.aktif yalnız paper modunda kullanılabilir")
    _default_number(cfg, "shadow_lab", "sanal_kasa_usdt", 100000.0, minimum=10, maximum=1e9)
    _default_number(cfg, "shadow_lab", "net_kar_tamponu_usdt", 0.0, minimum=0, maximum=1e6)
    cfg["shadow_lab"].setdefault("max_karsi_teknik_bilesen", 1)
    _integer(cfg, "shadow_lab", "max_karsi_teknik_bilesen", minimum=0, maximum=19)
    _boolean(cfg, "shadow_lab", "range_akis_girisine_izin", False)
    for nested in ("flow", "volatility", "portfolio", "pdf_confluence", "pdf_v3_confluence"):
        value = cfg["shadow_lab"].setdefault(nested, {})
        if not isinstance(value, dict):
            raise ConfigError(f"Geçersiz bölüm: shadow_lab.{nested}")
    _boolean(cfg["shadow_lab"], "pdf_v3_confluence", "aktif", False)
    cfg["shadow_lab"]["pdf_v3_confluence"].setdefault("min_aligned_signals", 2)
    _integer(cfg["shadow_lab"], "pdf_v3_confluence", "min_aligned_signals", minimum=1, maximum=6)
    cfg["shadow_lab"]["pdf_v3_confluence"].setdefault("max_opposed_signals", 2)
    _integer(cfg["shadow_lab"], "pdf_v3_confluence", "max_opposed_signals", minimum=0, maximum=6)
    for key, default, low, high in (
        ("referans_notional_usdt", 1000.0, 0.001, 1e12),
        ("referans_cvd_usdt", 100.0, 0.001, 1e12),
        ("min_kapsama_saniye", 60.0, 0.0, 86400.0),
        ("max_defter_yasi_saniye", 10.0, 0.0, 86400.0),
    ):
        _default_number(cfg["shadow_lab"], "flow", key, default, minimum=low, maximum=high)
    cfg["shadow_lab"]["flow"].setdefault("min_islem_sayisi", 5)
    _integer(cfg["shadow_lab"], "flow", "min_islem_sayisi", minimum=1, maximum=1000000)
    for key, default in (
        ("min_bb_genisligi_yuzde", 0.20), ("min_atr_yuzde", 0.0),
    ):
        _default_number(cfg["shadow_lab"], "volatility", key, default, minimum=0, maximum=1000)
    if cfg["shadow_lab"]["aktif"] and (
        cfg["shadow_lab"]["volatility"]["min_bb_genisligi_yuzde"] <= 0
        and cfg["shadow_lab"]["volatility"]["min_atr_yuzde"] <= 0
    ):
        raise ConfigError("Shadow volatilite deneyinde BB veya ATR eşiği pozitif olmalı")
    for key, default, low, high in (
        ("korelasyon_esik", 0.80, 0.0, 1.0),
        ("korelasyon_max_pozisyon", 3, 1, 1000),
        ("korelasyon_min_ortak_getiri", 20, 2, 1000),
        ("ayni_yon_max_pozisyon", 50, 1, 1000),
    ):
        _default_number(cfg["shadow_lab"], "portfolio", key, default, minimum=low, maximum=high)

    weights = [
        _number(cfg, "sinyal", key, minimum=0, maximum=1)
        for key in ("agirlik_indikator", "agirlik_para_akisi", "agirlik_haber", "agirlik_ml")
    ]
    if sum(weights) <= 0:
        raise ConfigError("Sinyal ağırlıklarından en az biri sıfırdan büyük olmalı")
    long_th = _number(cfg, "sinyal", "long_esik", minimum=0, maximum=100)
    short_th = _number(cfg, "sinyal", "short_esik", minimum=-100, maximum=0)
    if long_th == 0 or short_th == 0:
        raise ConfigError("long_esik pozitif, short_esik negatif olmalı")
    _number(cfg, "sinyal", "cikis_esik", minimum=0, maximum=100)
    _boolean(cfg, "sinyal", "rejim_bazli", True)
    _boolean(cfg, "sinyal", "supertrend_iz_takibi", True)
    _default_number(cfg, "sinyal", "breakout_hacim_z_esik", 1.5, minimum=0, maximum=20)
    _boolean(cfg, "sinyal", "breakout_akim_onayi", True)
    _boolean(cfg, "sinyal", "orderflow_onayi", True)
    _boolean(cfg, "sinyal", "para_akisi_tetik", True)
    _default_number(cfg, "sinyal", "para_akisi_esik", 50, minimum=0, maximum=100)
    _default_number(cfg, "sinyal", "tetik_indikator_min", 10, minimum=0, maximum=100)
    _default_number(cfg, "sinyal", "tetik_min_toplam", 15, minimum=0, maximum=100)
    _default_number(cfg, "sinyal", "min_bb_genisligi_yuzde", 0.0, minimum=0, maximum=100)
    _default_number(cfg, "sinyal", "min_atr_yuzde", 0.0, minimum=0, maximum=100)
    _boolean(cfg, "sinyal", "ikiz_varlik_korumasi", True)
    _boolean(cfg, "sinyal", "tukenme_korumasi_aktif", False)
    _boolean(cfg, "sinyal", "yatay_akis_engeli_aktif", False)
    _boolean(cfg, "sinyal", "teknik_uyum_aktif", False)
    _default_number(cfg, "sinyal", "max_karsit_teknik_bilesen", 1, minimum=0, maximum=20)
    _default_number(cfg, "sinyal", "min_teknik_skor", 20.0, minimum=0.0, maximum=100.0)
    _boolean(cfg, "sinyal", "likidasyon_miknatis_aktif", False)
    _default_number(cfg, "sinyal", "likidasyon_miknatis_mesafe_yuzde", 0.18, minimum=0.02, maximum=5.0)
    _default_number(cfg, "sinyal", "likidasyon_miknatis_akis_istisna", 68.0, minimum=40.0, maximum=100.0)
    _default_number(cfg, "sinyal", "short_min_rsi", 27.0, minimum=0.0, maximum=50.0)
    _default_number(cfg, "sinyal", "short_min_mfi", 18.0, minimum=0.0, maximum=50.0)
    _default_number(cfg, "sinyal", "long_max_rsi", 73.0, minimum=50.0, maximum=100.0)
    _default_number(cfg, "sinyal", "long_max_mfi", 82.0, minimum=50.0, maximum=100.0)

    _enum(
        cfg, "boyutlandirma", "mod", "sabit_usdt",
        {"sabit_usdt", "kasa_10_20x", "atr_kelly", "atr", "kelly", "sabit"},
    )
    _default_number(cfg, "boyutlandirma", "sabit_marj_usdt", 50.0, minimum=1, maximum=1e9)
    _default_number(cfg, "boyutlandirma", "atr_katsayi", 1.5, minimum=0.01, maximum=100)
    cfg["boyutlandirma"].setdefault("atr_periyot", 14)
    _integer(cfg, "boyutlandirma", "atr_periyot", minimum=1, maximum=1000)
    _default_number(cfg, "boyutlandirma", "kelly_kesir", 0.5, minimum=0.01, maximum=1)
    kelly_min = _default_number(cfg, "boyutlandirma", "kelly_min_risk", 0.25, minimum=0, maximum=100)
    kelly_max = _default_number(cfg, "boyutlandirma", "kelly_max_risk", 2, minimum=0.001, maximum=100)
    if kelly_min > kelly_max:
        raise ConfigError("kelly_min_risk, kelly_max_risk değerini aşamaz")
    cfg["boyutlandirma"].setdefault("kelly_min_islem", 20)
    _integer(cfg, "boyutlandirma", "kelly_min_islem", minimum=1, maximum=100000)

    _enum(cfg, "emirler", "giris_tipi", "maker", {"market", "maker", "limit"})
    _default_number(cfg, "emirler", "maker_zaman_asimi_sn", 3, minimum=0.1, maximum=300)
    _default_number(cfg, "emirler", "max_kayma_yuzde", 0.30, minimum=0, maximum=5)
    _default_number(cfg, "emirler", "komisyon_maker_yuzde", 0.02, minimum=0, maximum=10)
    _default_number(cfg, "emirler", "komisyon_taker_yuzde", 0.05, minimum=0, maximum=10)
    _boolean(cfg, "emirler", "borsa_korumasi", True)

    for key, default, low, high in (
        ("max_ardisik_yetki_hatasi", 3, 1, 100),
        ("max_ardisik_emir_hatasi", 3, 1, 100),
    ):
        cfg["sigorta"].setdefault(key, default)
        _integer(cfg, "sigorta", key, minimum=low, maximum=high)
    _default_number(cfg, "sigorta", "gunluk_max_zarar_yuzde", 5, minimum=0.01, maximum=100)
    _default_number(cfg, "sigorta", "ws_kopma_saniye", 10, minimum=1, maximum=3600)
    _default_number(cfg, "sigorta", "flash_crash_yuzde", 8, minimum=0.1, maximum=100)
    _default_number(cfg, "sigorta", "altcoin_sok_mola_saniye", 900, minimum=10, maximum=86400)
    shock_syms = cfg["sigorta"].setdefault("global_sok_sembolleri", ["BTC/USDT", "ETH/USDT"])
    if not isinstance(shock_syms, list) or any(
        not isinstance(item, str) or not _SYMBOL_RE.fullmatch(item.strip().upper())
        for item in shock_syms
    ):
        raise ConfigError("sigorta.global_sok_sembolleri geçerli sembol listesi olmalı")
    cfg["sigorta"]["global_sok_sembolleri"] = [item.strip().upper() for item in shock_syms]

    _boolean(cfg, "pdf_v3", "aktif", True)
    _boolean(cfg, "pdf_v3", "turev_istihbarat_aktif", True)
    _boolean(cfg, "pdf_v3", "asiri_kalabalik_engeli", True)
    _default_number(cfg, "pdf_v3", "turev_cache_sn", 180, minimum=10, maximum=86400)

    for key, default in (("aktif", True),):
        _boolean(cfg, "makine_ogrenmesi", key, default)
    for key, default, high in (("ufuk_mum", 3, 100), ("min_egitim_mumu", 80, 100000), ("yeniden_egitim_araligi", 15, 100000)):
        cfg["makine_ogrenmesi"].setdefault(key, default)
        _integer(cfg, "makine_ogrenmesi", key, minimum=1, maximum=high)

    for key, default, high in (
        ("balina_esik_usdt", 100000, 1e12), ("likidasyon_squeeze_usdt", 50000, 1e12),
        ("pencere_saniye", 300, 86400), ("hacim_patlama_katsayi", 2.5, 1000),
        ("divergence_min_fiyat_yuzde", 0.05, 10),
        ("absorption_min_usdt", 25000, 1e12), ("absorption_oran", 1.5, 100),
    ):
        _default_number(cfg, "para_akisi", key, default, minimum=0.001, maximum=high)
    cfg["para_akisi"].setdefault("emir_defteri_kademe", 20)
    _integer(cfg, "para_akisi", "emir_defteri_kademe", minimum=1, maximum=20)
    cfg["para_akisi"].setdefault("vpvr_pencere_saniye", 21600)
    _integer(cfg, "para_akisi", "vpvr_pencere_saniye", minimum=60, maximum=604800)
    cfg["para_akisi"].setdefault("vpvr_bin", 48)
    _integer(cfg, "para_akisi", "vpvr_bin", minimum=8, maximum=500)
    _default_number(cfg, "para_akisi", "squeeze_bildirim_mola_sn", 300.0, minimum=0, maximum=86400)
    _default_number(cfg, "para_akisi", "squeeze_min_tekil_usdt", 25000.0, minimum=0, maximum=1e12)
    _default_number(cfg, "para_akisi", "baslangic_isinma_saniye", 0.0, minimum=0.0, maximum=3600.0)
    _boolean(cfg, "para_akisi", "canli_akis_guveni_aktif", False)
    _boolean(cfg, "para_akisi", "hafif_akis_teyidi_aktif", False)
    _default_number(cfg, "para_akisi", "min_hafif_kapsama_saniye", 10.0, minimum=0.0, maximum=86400.0)
    _default_number(cfg, "para_akisi", "min_hafif_islem_sayisi", 2, minimum=1, maximum=100000)
    _default_number(cfg, "para_akisi", "min_hafif_notional_usdt", 100.0, minimum=0.0, maximum=1e12)
    _default_number(cfg, "para_akisi", "anlik_tetik_min_kapsama_saniye", 12.0, minimum=0.0, maximum=86400.0)
    _default_number(cfg, "para_akisi", "anlik_tetik_min_notional_usdt", 200.0, minimum=0.0, maximum=1e12)
    _boolean(cfg, "para_akisi", "anlik_akis_tetik_aktif", True)
    _default_number(cfg, "para_akisi", "min_kapsama_saniye", 60.0, minimum=0.0, maximum=86400.0)
    cfg["para_akisi"].setdefault("min_islem_sayisi", 10)
    _integer(cfg, "para_akisi", "min_islem_sayisi", minimum=1, maximum=1000000)
    _default_number(cfg, "para_akisi", "min_notional_usdt", 2500.0, minimum=0.0, maximum=1e12)
    _default_number(cfg, "para_akisi", "max_defter_yasi_saniye", 15.0, minimum=0.0, maximum=86400.0)
    _default_number(cfg, "para_akisi", "referans_notional_usdt", 2500.0, minimum=0.001, maximum=1e12)
    _default_number(cfg, "para_akisi", "referans_cvd_usdt", 250.0, minimum=0.001, maximum=1e12)

    _boolean(cfg, "arbitraj", "aktif", True)
    _default_number(cfg, "arbitraj", "min_net_kar_yuzde", 0.08, minimum=0, maximum=100)
    _default_number(cfg, "arbitraj", "islem_tutari_usdt", 1000, minimum=0.01, maximum=1e9)
    _default_number(cfg, "arbitraj", "mola_saniye", 10, minimum=0, maximum=86400)

    sources = cfg["haberler"].setdefault("kaynaklar", [])
    if not isinstance(sources, list):
        raise ConfigError("haberler.kaynaklar bir URL listesi olmalı")
    for url in sources:
        if not isinstance(url, str) or not url.startswith(("https://", "http://")) or "@" in url:
            raise ConfigError(f"Geçersiz haber kaynağı: {url!r}")
    _default_number(cfg, "haberler", "kontrol_saniye", 30, minimum=5, maximum=86400)
    _boolean(cfg, "haberler", "veto_guc", True)
    _boolean(cfg, "haberler", "korku_acgozluluk", True)
    fear_low = _default_number(cfg, "haberler", "korku_veto_alt", 15, minimum=0, maximum=100)
    greed_high = _default_number(cfg, "haberler", "acgozluluk_long_veto_ust", 85, minimum=0, maximum=100)
    if fear_low >= greed_high:
        raise ConfigError("korku_veto_alt, acgozluluk_long_veto_ust değerinden küçük olmalı")

    for key, default, low, high in (
        ("mum_yenileme_saniye", 15, 1, 3600),
        ("reconnect_saniye", 5, 0.1, 3600),
        ("ws_ping_saniye", 15, 1, 3600),
    ):
        _default_number(cfg, "hiz", key, default, minimum=low, maximum=high)

    _boolean(cfg, "failover", "aktif", True)
    cfg["failover"].setdefault("timeout_esigi", 3)
    _integer(cfg, "failover", "timeout_esigi", minimum=1, maximum=100)
    _default_number(cfg, "failover", "soguma_saniye", 300, minimum=1, maximum=86400)

    db_file = str(cfg["veritabani"].setdefault("dosya", "bot_state.db")).strip()
    if not db_file or Path(db_file).name in {"", ".", ".."}:
        raise ConfigError("veritabani.dosya geçerli bir dosya yolu olmalı")
    _boolean(cfg, "veritabani", "wal_modu", True)
    _default_number(cfg, "veritabani", "cop_toplayici_saniye", 86400, minimum=60, maximum=31536000)
    for key, default in (("max_islem_gecmisi", 2000), ("max_equity_gecmisi", 2000), ("max_arbitraj_gecmisi", 1000)):
        cfg["veritabani"].setdefault(key, default)
        _integer(cfg, "veritabani", key, minimum=10, maximum=10000000)

    for section, default_port in (("health_check", 8502), ("panel", 8501)):
        _boolean(cfg, section, "aktif", True)
        cfg[section].setdefault("port", default_port)
        _integer(cfg, section, "port", minimum=1, maximum=65535)
        host = str(cfg[section].setdefault("host", "0.0.0.0")).strip()
        if not host or any(ch.isspace() for ch in host):
            raise ConfigError(f"{section}.host geçersiz")
    for key in (
        "telegram_aktif",
        "whatsapp_aktif",
        "discord_aktif",
        "pagerduty_aktif",
        "sadece_kritik_pagerduty",
    ):
        _boolean(cfg, "bildirimler", key, True)
    _boolean(cfg, "bildirimler", "telegram_periyodik_rapor", True)
    _boolean(cfg, "bildirimler", "telegram_detayli_rapor", False)
    _boolean(cfg, "bildirimler", "balina_uyarilari", False)
    _default_number(cfg, "bildirimler", "telegram_rapor_araligi_sn", 300, minimum=30, maximum=86400)
    _default_number(cfg, "bildirimler", "telegram_ilk_rapor_gecikmesi_sn", 10, minimum=0, maximum=300)
    _boolean(cfg, "optimizasyon", "otomatik_params", False)
    _default_number(cfg, "optimizasyon", "oos_egitim_orani", 0.70, minimum=0.5, maximum=0.95)
    params_file = str(cfg["optimizasyon"].setdefault("params_dosyasi", "params_best.json")).strip()
    if not params_file:
        raise ConfigError("optimizasyon.params_dosyasi boş olamaz")

    if mode in {"live", "testnet"} and api is not None:
        required = {
            "binance": ("binance_key", "binance_secret"),
            "okx": ("okx_key", "okx_secret", "okx_passphrase"),
        }
        for exchange in normalized_exchanges:
            missing = [key for key in required[exchange] if not str(api.get(key, "")).strip()]
            if missing:
                raise ConfigError(
                    f"{mode} modu için {exchange} kimlik bilgileri eksik: {', '.join(missing)}"
                )
    if mode == "live" and os.getenv("LIVE_TRADING_CONFIRM", "").strip() != LIVE_CONFIRMATION:
        raise ConfigError(
            "Canlı işlem kilitli. Gerçek para riskini kabul ediyorsanız "
            f"LIVE_TRADING_CONFIRM={LIVE_CONFIRMATION} tanımlayın."
        )


def load_config(path: str | Path | None = None) -> dict:
    """YAML + ortam değişkenlerini yükler, sırları ayırır ve ayarları doğrular."""
    configured_path = path or os.getenv("CONFIG_FILE") or (BASE_DIR / "config.yaml")
    raw_cfg = Path(configured_path).expanduser()
    if not raw_cfg.is_absolute() and not raw_cfg.exists() and (BASE_DIR / raw_cfg).exists():
        raw_cfg = BASE_DIR / raw_cfg
    cfg_path = raw_cfg.resolve()
    try:
        with cfg_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Yapılandırma okunamadı: {cfg_path} ({exc})") from exc

    cfg = _without_yaml_secrets(raw)
    if not isinstance(cfg, dict):
        raise ConfigError("Yapılandırmanın kökü bir YAML nesnesi olmalı")

    mode = os.getenv("MODE", "").strip().lower()
    if mode:
        if mode not in {"paper", "testnet", "live"}:
            raise ConfigError("MODE yalnızca paper, testnet veya live olabilir")
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
        "whatsapp_phone": os.getenv("WHATSAPP_PHONE", ""),
        "whatsapp_api_key": os.getenv("WHATSAPP_API_KEY", ""),
        "whatsapp_cloud_token": os.getenv("WHATSAPP_CLOUD_TOKEN", ""),
        "whatsapp_phone_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        "whatsapp_webhook": os.getenv("WHATSAPP_WEBHOOK_URL", ""),
        "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL", ""),
        "pagerduty_routing_key": os.getenv("PAGERDUTY_ROUTING_KEY", ""),
        "dashboard_token": os.getenv("DASHBOARD_TOKEN", ""),
        "llm_url": os.getenv("LLM_API_URL", ""),
        "llm_key": os.getenv("LLM_API_KEY", ""),
        "llm_model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
    }
    for key_name, value in api_cfg.items():
        if key_name not in {"telegram_chat", "llm_url", "llm_model"} and value:
            register_secret(value)

    validate_config(cfg, api_cfg)
    cfg["api"] = api_cfg
    return cfg
