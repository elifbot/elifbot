"""ACARBOT v4.0 — Ajan katmanı.

Kullanıcı şartnamesi (madde 18-22):
  - Ajanlar ASLA işlem kararı VERMEZ / işlem AÇMAZ.
  - "flag" modda yalnız risk bayrağı üretirler (log + rapor);
    "block" modda bayrak aktifken YENİ GİRİŞ engellenir (opsiyonel).

Ajanlar:
  - USMarketAgent   : SPX / Nasdaq / DXY / VIX → risk-on / risk-off bayrağı.
  - RssNewsAgent    : RSS başlık taraması → makro/kripto risk bayrağı.
  - CongressAgent   : kongre işlem verisi — güvenilir ücretsiz veri kaynağı
                      olmadığı için DÜRÜSTÇE "uygulanmadı" raporlar (bilgi
                      sinyali olarak tasarlandı; işlem tetiklemez).
  - AnalystAgent    : oturum raporunu yorumlar (kurallı; opsiyonel LLM),
                      ÖNERİ verir — işlem kararı vermez.
  - Tarayıcı/araştırma ajanı: bot çalışma zamanına tarayıcı gömmek
    tasarım gereği reddedildi (borsa verisi zaten birinci elden gelir;
    RSS ajanı web başlıklarını zaten toplar) — kapsam dışıdır ve
    DEGISIKLIKLER_FINAL_v4.0.md'de gerekçesiyle belgelenmiştir.
"""

from agents.analyst import AnalystAgent
from agents.congress import CongressAgent
from agents.news_rss import RssNewsAgent
from agents.us_market import USMarketAgent

__all__ = [
    "AnalystAgent",
    "CongressAgent",
    "RssNewsAgent",
    "USMarketAgent",
]
