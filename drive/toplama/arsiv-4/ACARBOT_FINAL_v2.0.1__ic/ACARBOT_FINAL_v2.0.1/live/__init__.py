"""ACARBOT v2.0 — Borsa entegrasyon güvenlik çatısı (şartname madde 9).

Kapsam:
  - Binance Futures TESTNET ve OKX DEMO imzalı istemcileri (clients.py,
    broker_clients.py)
  - Emir gönderiminde idempotency (deterministik clientOrderId)
  - Gerçek pozisyonların borsayla karşılaştırılması (mutabakat)
  - Restart sonrası pozisyon ve emir kurtarma (bayat emir iptali,
    koruyucu stopun yeniden kurulması)
  - Borsa tarafında sunucu koruyucu stop (STOP_MARKET closePosition)
  - Reduce-only çıkış emirleri
  - Acil durum kapatma ve tüm emirleri iptal
  - API anahtarı güvenlik kontrol listesi (para çekme izni KAPALI olmalı)

GÜVENLİK:
  - Varsayılan TAMAMEN KAPALI. Yalnızca --live-testnet + ortam
    değişkenleriyle (API anahtarları) açılır.
  - Ağ erişimi enjekte edilen transport ile yapılır; testlerde sahte
    transport kullanılır, hiçbir test gerçek ağa çıkmaz.
  - Para çekme izninin kapalı olması programatik olarak doğrulanamaz;
    istemci başlangıçta MANUEL kontrol listesi döndürür ve uyarır.
"""

from live.broker_clients import BinanceFuturesTestnet, OkxDemoTrading
from live.clients import (
    LiveClientError,
    OkxSignedClient,
    SignedHttpClient,
    security_checklist,
)
from live.sync import (
    DriftReport,
    EmergencyController,
    IdempotentOrderIdFactory,
    LiveMirror,
    PositionReconciler,
    RestartRecovery,
)

__all__ = [
    "BinanceFuturesTestnet",
    "OkxDemoTrading",
    "LiveClientError",
    "OkxSignedClient",
    "SignedHttpClient",
    "security_checklist",
    "DriftReport",
    "EmergencyController",
    "IdempotentOrderIdFactory",
    "LiveMirror",
    "PositionReconciler",
    "RestartRecovery",
]
