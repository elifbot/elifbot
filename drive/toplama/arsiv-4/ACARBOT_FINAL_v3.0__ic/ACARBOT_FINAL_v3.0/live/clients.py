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
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Transport = Callable[[str, str, dict[str, str], bytes], tuple[int, bytes]]


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


def urllib_transport(url: str, method: str, headers: dict[str, str],
                     body: bytes) -> tuple[int, bytes]:
    """Gerçek ağ transportu (yalnızca kullanıcı makinesinde kullanılır).

    v3.0 DÜZELTMESİ: HTTPError durumunda yanıt GÖVDESİ okunur ve hata
    mesajına eklenir. Eski sürüm gövdeyi atıyordu; bu yüzden borsanın
    döndüğü hata kodları (ör. Binance -4046 "No need to change margin")
    kayboluyor ve her yeniden başlatmada gereksiz hata oluşuyordu.
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
        raise LiveClientError(
            f"HTTP {exc.code}: {error_body.decode('utf-8', errors='replace')}"
        ) from exc
    except URLError as exc:
        raise LiveClientError(f"borsa isteği başarısız: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — transport sınırında sarılır
        raise LiveClientError(f"borsa isteği başarısız: {exc}") from exc


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
    """Binance USDT-M (testnet/mainnet) imzalı istemci."""

    def __init__(
        self,
        base_url: str,
        api_key_env: str,
        api_secret_env: str,
        transport: Transport,
        recv_window_ms: int = 5_000,
        extra_headers: dict[str, str] | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = read_secret(api_key_env)
        self.api_secret = read_secret(api_secret_env)
        self.transport = transport
        self.recv_window_ms = recv_window_ms
        self.extra_headers = extra_headers or {}
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.last_request_ms: int = 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and bool(self.api_secret)

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
        query["timestamp"] = self.clock()
        query["recvWindow"] = self.recv_window_ms
        encoded = urlencode(query)
        signature = hmac.new(
            self.api_secret.encode(), encoded.encode(), hashlib.sha256,
        ).hexdigest()
        url = f"{self.base_url}{path}?{encoded}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key, **self.extra_headers}
        self.last_request_ms = self.clock()
        status, body = self.transport(url, method, headers, b"")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LiveClientError(f"bozuk JSON yanıtı: {exc}") from exc
        if status >= 400:
            raise LiveClientError(f"HTTP {status}: {payload}")
        return RestResponse(status, payload)


class OkxSignedClient(SignedHttpClient):
    """OKX demo (x-simulated-trading: 1) imzalı istemci."""

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
            self.clock() / 1000.0, tz=timezone.utc,
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
        status, raw = self.transport(url, method, headers, body_bytes)
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LiveClientError(f"bozuk JSON yanıtı: {exc}") from exc
        if status >= 400:
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
