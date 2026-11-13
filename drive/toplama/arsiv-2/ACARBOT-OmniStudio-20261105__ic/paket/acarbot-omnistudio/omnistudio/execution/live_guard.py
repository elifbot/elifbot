"""LIVE mod kilidi — bu sürümde gerçek emir yolu KAPALIDIR.

Kullanıcı kararı: PAPER modda gerçek piyasa verisiyle test. Bu yüzden LIVE
kod yolu yazılmadı ve bu bekçi her durumda reddeder. Kilidi kaldırmak için
yalnız bir bayrağı çevirmek yetmez; gerçek imzalı borsa istemcisi, anahtar
yönetimi, emir mutabakatı ve risk onayı gerekir.

Arşiv hükmü: v9.4.1 araştırması komisyon öncesi bile net negatif buldu;
`real_money_approved=false`. Bu hüküm bu sürümde DEĞİŞMEDİ.
"""
from __future__ import annotations

from ..core.types import Mode


class LiveTradingBlocked(RuntimeError):
    """Gerçek emir gönderme girişimi engellendi."""


LIVE_BLOCK_REASON = (
    "LIVE mod bu sürümde kilitli. Kullanıcı onayı PAPER + gerçek piyasa verisi "
    "yönünde. Ayrıca v9.4.1 araştırması stratejinin komisyon öncesi net negatif "
    "olduğunu buldu; gerçek para onayı yok."
)


def assert_mode_allowed(mode: Mode | str) -> None:
    m = Mode(mode) if not isinstance(mode, Mode) else mode
    if m is Mode.LIVE:
        raise LiveTradingBlocked(LIVE_BLOCK_REASON)


def mode_banner(mode: Mode | str) -> str:
    m = Mode(mode) if not isinstance(mode, Mode) else mode
    if m is Mode.PAPER:
        return ("PAPER MODU — Gerçek piyasa verisi okunur, sanal deftere işlem "
                "yazılır. Borsaya EMİR GÖNDERİLMEZ.")
    if m is Mode.OBSERVE:
        return "OBSERVE MODU — Yalnız veri ve karar kaydı; pozisyon açılmaz."
    return LIVE_BLOCK_REASON