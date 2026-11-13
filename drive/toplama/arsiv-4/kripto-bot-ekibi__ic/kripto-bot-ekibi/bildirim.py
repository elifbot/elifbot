"""Masaüstü bildirimleri: plyer varsa native bildirim, yoksa konsol logu."""
import logging

log = logging.getLogger("kriptobot.bildirim")

try:
    from plyer import notification
    _HAS_PLYER = True
except Exception:
    _HAS_PLYER = False


def destekleniyor() -> str:
    return "native" if _HAS_PLYER else "konsol"


def gonder(baslik: str, mesaj: str) -> str:
    """Bildirim gönder. Dönen: 'native' veya 'konsol'."""
    if _HAS_PLYER:
        try:
            notification.notify(
                title=baslik[:64],
                message=mesaj[:240],
                app_name="KriptoBot Panel",
                timeout=10,
            )
            return "native"
        except Exception as e:
            log.warning("Native bildirim başarısız: %s", e)
    print(f"\n🔔 ALARM: {baslik}\n   {mesaj}\n")
    return "konsol"
