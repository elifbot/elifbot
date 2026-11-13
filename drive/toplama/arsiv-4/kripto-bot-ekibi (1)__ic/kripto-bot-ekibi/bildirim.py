"""Masaüstü bildirimleri: plyer varsa native bildirim, yoksa konsol logu.

Grafik oturumu olmayan (headless) Linux/SSH ortamlarında plyer/dbus çökmemesi
için önce ortam kontrolü yapılır; başarısızsa güvenle konsol loguna düşer.
"""
import logging
import os
import sys

log = logging.getLogger("kriptobot.bildirim")

try:
    from plyer import notification
    _HAS_PLYER = True
except Exception:
    _HAS_PLYER = False


def _native_mumkun() -> bool:
    """Bu ortamda native bildirim denenebilir mi?"""
    if not _HAS_PLYER:
        return False
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    # Linux/BSD: dbus için grafik oturumu şart (yoksa proses çökebilir)
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def destekleniyor() -> str:
    return "native" if _native_mumkun() else "konsol"


def gonder(baslik: str, mesaj: str) -> str:
    """Bildirim gönder. Dönen: 'native' veya 'konsol'."""
    if _native_mumkun():
        try:
            notification.notify(
                title=baslik[:64],
                message=mesaj[:240],
                app_name="KriptoBot Panel",
                timeout=10,
            )
            return "native"
        except BaseException as e:  # dbus çökmesi dahil her şeyi yut
            log.warning("Native bildirim başarısız: %s", e)
    try:
        print(f"\n🔔 ALARM: {baslik}\n   {mesaj}\n", flush=True)
    except Exception:
        pass
    return "konsol"
