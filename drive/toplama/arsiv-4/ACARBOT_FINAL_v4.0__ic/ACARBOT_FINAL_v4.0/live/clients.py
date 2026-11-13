"""ACARBOT v2.0 — İmzalı borsa HTTP istemcisi (enjekte edilebilir transport).

Güvenlik tasarımı:
  - Ağ erişimi `transport` fonksiyonuyla enjekte edilir:
        transport(url, method, headers, body) -> (status, body_bytes)
    Testlerde sahte transport, canlıda urllib tabanlı gerçek transport.
  - Anahtarlar yalnızca ortam değişkenlerinden okunur; loglara ASLA
    yazılmaz (safety.alerts'taki maskeleme de ikinci katman olarak çalışır).
  - Binance: HMAC-SHA256(query, secret) → signature parametresi.
  - OKX: OK-ACCESS-SIGN = base64(HMAC-SHA256(ts+method+path+body, secret)).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Transport = Callable[[str, str, dict[str, str], bytes], tuple[int, bytes]]

logger = logging.getLogger(__name__)


def read_secret(env_name: str) -> str:
    """v3.0: gizli anahtar okuma (ortam değişkeni YA DA dosya).

    <AD> ver ortam değişkeni düz metin anahtar bekler; <AD>_FILE verilirse
    değer bir DOSYA YOLU kabul edilir ve dosyanın ilk satırı okunur
    (docker secrets / vault-agent / k8s secret mount uyumlu).
    Öncelik: <AD>_FILE > <AD>.
    """
    file_path = os.environ.get(f"{env_name}_FILE", "").strip()
    if file_path:
        try:
            with open(file_path, encoding="utf-8") as handle:
                return handle.readline().strip()
        except OSError as exc:
            raise LiveClientError(
                f"gizli anahtar dosyası okunamadı ({env_name}_FILE={file_path}): {exc}"
            ) from exc
    return os.environ.get(env_name, "").strip()


class LiveClientError(RuntimeError):
    """Canlı/testnet borsa isteği başarısız."""


class LiveRateLimited(LiveClientError):
    """v4.0: HTTP 429 — Retry-After bilgisiyle taşınır (istemci yeniden dener)."""

    def __init__(self, message: str, retry_after_s: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after_s = max(float(retry_after_s), 0.0)


def urllib_transport(url: str, method: str, headers: dict[str, str],
                     body: bytes) -> tuple[int, bytes]:
    """Gerçek ağ transportu (yalnızca kullanıcı makinesinde kullanılır).

    v3.0 DÜZELTMESİ: HTTPError durumunda yanıt GÖVDESİ okunur ve hata
    mesajına eklenir. Eski sürüm gövdeyi atıyordu; bu yüzden borsanın
    döndüğü hata kodları (ör. Binance -4046 "No need to change margin")
    kayboluyor ve her yeniden başlatmada gereksiz hata oluşuyordu.
    v4.0: HTTP 429 → LiveRateLimited (Retry-After başlığı korunur); 5xx →
    LiveServerError (istemci kısa üstel geri çekilmeyle yeniden dener).
    """
    request = Request(url, data=body if body else None, method=method)
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except HTTPError as exc:
        try:
            error_body = exc.read()
        except Exception:  # noqa: BLE001
            error_body = b""
        text = error_body.decode("utf-8", errors="replace")
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After", "1") if exc.headers else "1"
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = 1.0
            raise LiveRateLimited(
                f"HTTP 429 (Retry-After={retry_after}): {text}",
                retry_after_s=delay,
            ) from exc
        if 500 <= exc.code < 600:
            raise LiveServerError(f"HTTP {exc.code}: {text}") from exc
        raise LiveClientError(
            f"HTTP {exc.code}: {text}"
        ) from exc
    except URLError as exc:
        raise LiveClientError(f"borsa isteği başarısız: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — transport sınırında sarılır
        raise LiveClientError(f"borsa isteği başarısız: {exc}") from exc


class LiveServerError(LiveClientError):
    """v4.0: HTTP 5xx — kısa geri çekilmeyle yeniden denenebilir."""


def default_transport() -> Transport:
    return urllib_transport


@dataclass
class RestResponse:
    status: int
    payload: object

    def as_dict(self) -> dict:
        if isinstance(self.payload, dict):
            return self.payload
        raise LiveClientError(f"beklenmeyen yanıt: {type(self.payload)}")

    def as_list(self) -> list:
        if isinstance(self.payload, list):
            return self.payload
        raise LiveClientError(f"liste beklenirken yanıt: {type(self.payload)}")


class SignedHttpClient:
    """Binance USDT-M (testnet/mainnet) imzalı istemci.

    v4.0 sertleştirme:
      - HTTP 429 → Retry-After süresi kadar bekleyip yeniden dener
        (rate_retries kadar; varsayılan 2).
      - HTTP 5xx → kısa üstel geri çekilmeyle yeniden dener.
      - Borsa saat senkronu: sync_time() sunucu saatini ölçer; imzalı
        istekler local + offset ile damgalanır; -1021/50102 (zaman sapması)
        hatasında TEK kez resync + retry yapılır.
    """

    def __init__(
        self,
        base_url: str,
        api_key_env: str,
        api_secret_env: str,
        transport: Transport,
        recv_window_ms: int = 5_000,
        extra_headers: dict[str, str] | None = None,
        clock: Callable[[], int] | None = None,
        rate_retries: int = 2,
        sleeper=time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = read_secret(api_key_env)
        self.api_secret = read_secret(api_secret_env)
        self.transport = transport
        self.recv_window_ms = recv_window_ms
        self.extra_headers = extra_headers or {}
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.last_request_ms: int = 0
        # v4.0
        self.rate_retries = max(int(rate_retries), 0)
        self._sleeper = sleeper
        self.time_offset_ms: int = 0
        self.last_time_sync_ms: int = 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and bool(self.api_secret)

    def now_ms(self) -> int:
        """v4.0: saat ofseti uygulanmış yerel zaman (ms)."""
        return self.clock() + self.time_offset_ms

    def _call_with_retries(self, call) -> tuple[int, bytes]:
        """429/5xx için geri çekilmeli çağrı (transport sarmalayıcısı)."""
        attempts = self.rate_retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return call()
            except LiveRateLimited as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                delay = min(exc.retry_after_s, 60.0)
                logger.warning(
                    "HTTP 429: %.1f sn bekleniyor ve yeniden deneniyor (%d/%d)",
                    delay, attempt, attempts - 1,
                )
                self._sleeper(delay)
            except LiveServerError as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                delay = min(2.0 ** (attempt - 1), 8.0)
                logger.warning(
                    "HTTP 5xx: %.1f sn sonra yeniden deneniyor (%d/%d)",
                    delay, attempt, attempts - 1,
                )
                self._sleeper(delay)
        assert last_exc is not None
        raise last_exc

    # -- Saat senkronu (v4.0) -------------------------------------------------

    TIME_SYNC_ENDPOINT = "/fapi/v1/time"

    def sync_time(self) -> int:
        """Sunucu saatini ölçer, ofseti günceller; offset_ms döndürür."""
        payload = self.public_request(self.TIME_SYNC_ENDPOINT).as_dict()
        server_ms = int(
            payload.get("serverTime")
            or (payload.get("data") or [{}])[0].get("ts", 0)
            or 0,
        )
        if server_ms <= 0:
            raise LiveClientError("borsa sunucu saati okunamadı")
        self.time_offset_ms = int(server_ms - self.clock())
        self.last_time_sync_ms = self.clock()
        if abs(self.time_offset_ms) > 1_000:
            logger.warning(
                "SAAT SAPMASI: yerel ↔ borsa ofset %d ms — imzalı istekler "
                "ofsetle damgalanıyor",
                self.time_offset_ms,
            )
        return self.time_offset_ms

    def public_request(
        self, path: str, params: dict[str, object] | None = None,
    ) -> RestResponse:
        """v3.0: imzasız PUBLIC uç isteği (exchangeInfo, instruments...).

        API anahtarı gerektirmeyen uçlar için; testnet anahtarı olmayan
        kurulumlarda da filtre/meta okunabilmesini sağlar.
        """
        query = urlencode(params or {})
        url = f"{self.base_url}{path}{('?' + query) if query else ''}"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        status, body = self.transport(url, "GET", headers, b"")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LiveClientError(f"bozuk JSON yanıtı: {exc}") from exc
        if status >= 400:
            raise LiveClientError(f"HTTP {status}: {payload}")
        return RestResponse(status, payload)

    # -- Binance imzalı istek -------------------------------------------

    def signed_request(
        self, method: str, path: str, params: dict[str, object] | None = None,
    ) -> RestResponse:
        if not self.configured:
            raise LiveClientError(
                "API anahtarları eksik; canlı/testnet istemcisi kullanılamaz"
            )
        query = dict(params or {})
        query["timestamp"] = self.now_ms()
        query["recvWindow"] = self.recv_window_ms
        encoded = urlencode(query)
        signature = hmac.new(
            self.api_secret.encode(), encoded.encode(), hashlib.sha256,
        ).hexdigest()
        url = f"{self.base_url}{path}?{encoded}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key, **self.extra_headers}
        self.last_request_ms = self.clock()
        status, body = self._call_with_retries(
            lambda: self.transport(url, method, headers, b""),
        )
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LiveClientError(f"bozuk JSON yanıtı: {exc}") from exc
        if status >= 400:
            text = json.dumps(payload, ensure_ascii=False)
            # v4.0: zaman sapması (-1021) → TEK kez resync + retry
            if "-1021" in text and self.last_time_sync_ms:
                logger.warning("Binance -1021: saat resync + tek retry")
                self.sync_time()
                return self.signed_request(method, path, params)
            raise LiveClientError(f"HTTP {status}: {payload}")
        return RestResponse(status, payload)


class OkxSignedClient(SignedHttpClient):
    """OKX demo (x-simulated-trading: 1) imzalı istemci."""

    TIME_SYNC_ENDPOINT = "/api/v5/public/time"

    def public_request(
        self, path: str, params: dict[str, object] | None = None,
    ) -> RestResponse:
        """v3.0: OKX public uç isteği (imzasız, auth başlıkları yok)."""
        query = urlencode(params or {})
        url = f"{self.base_url}{path}{('?' + query) if query else ''}"
        headers = {"Content-Type": "application/json", **self.extra_headers}
        status, raw = self.transport(url, "GET", headers, b"")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LiveClientError(f"bozuk JSON yanıtı: {exc}") from exc
        if status >= 400:
            raise LiveClientError(f"HTTP {status}: {payload}")
        return RestResponse(status, payload)

    def signed_request(
        self, method: str, path: str, params: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
    ) -> RestResponse:
        if not self.configured:
            raise LiveClientError(
                "API anahtarları eksik; OKX demo istemcisi kullanılamaz"
            )
        timestamp = datetime.fromtimestamp(
            self.now_ms() / 1000.0, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        body_bytes = json.dumps(body).encode() if body else b""
        request_path = path
        if params and method.upper() == "GET":
            request_path = f"{path}?{urlencode(params)}"
        sign_base = f"{timestamp}{method.upper()}{request_path}".encode() + body_bytes
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode(), sign_base, hashlib.sha256).digest(),
        ).decode()
        url = self.base_url + request_path
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": read_secret("OKX_API_PASSPHRASE"),
            "Content-Type": "application/json",
            "x-simulated-trading": "1",
            **self.extra_headers,
        }
        self.last_request_ms = self.clock()
        status, raw = self._call_with_retries(
            lambda: self.transport(url, method, headers, body_bytes),
        )
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LiveClientError(f"bozuk JSON yanıtı: {exc}") from exc
        if status >= 400:
            text = json.dumps(payload, ensure_ascii=False)
            # v4.0: zaman sapması (OKX 50102) → TEK kez resync + retry
            if "50102" in text and self.last_time_sync_ms:
                logger.warning("OKX 50102: saat resync + tek retry")
                self.sync_time()
                return self.signed_request(method, path, params, body=body)
            raise LiveClientError(f"HTTP {status}: {payload}")
        return RestResponse(status, payload)


def security_checklist() -> list[dict[str, str]]:
    """API anahtarı güvenlik kontrol listesi (şartname: para çekme KAPALI).

    Programatik doğrulama mümkün olmadığından manuel adımlar şeffaf
    listelenir; istemci bunları başlangıçta loglar.
    """
    return [
        {"check": "Para çekme izni", "required": "KAPALI",
         "note": "Anahtar yalnızca Futures işlem yetkisine sahip olmalı"},
        {"check": "IP kısıtlaması", "required": "AÇIK",
         "note": "Anahtar yalnızca bot makinesinin IP'sine izin vermeli"},
        {"check": "Anahtar saklama", "required": "ortam değişkeni",
         "note": "Kod/depoda düz metin anahtar bulunmamalı"},
        {"check": "Testnet önce", "required": "EVET",
         "note": "Gerçek para öncesi Binance Testnet / OKX Demo zorunlu"},
    ]
