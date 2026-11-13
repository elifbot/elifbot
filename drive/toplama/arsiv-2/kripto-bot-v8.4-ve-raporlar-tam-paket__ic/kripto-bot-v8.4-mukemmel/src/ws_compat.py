"""WebSocket İstemci Uyumluluk Katmanı (`websockets` -> `aiohttp` yedekli).

`websockets` paketi kuruluysa doğrudan onu kullanır; kurulu değilse `aiohttp`
üzerinden birebir aynı `async with connect(url, ...)` ve `async for msg in ws:`
arayüzünü sağlar.
"""
from __future__ import annotations

from typing import Any

try:
    import websockets as _native_ws  # type: ignore

    HAS_NATIVE_WEBSOCKETS = True
except ImportError:
    _native_ws = None
    HAS_NATIVE_WEBSOCKETS = False


class _AiohttpWsWrapper:
    def __init__(self, url: str, **kwargs: Any):
        self.url = url
        self.kwargs = kwargs
        self._session = None
        self._ws = None

    async def __aenter__(self):
        import aiohttp

        heartbeat = self.kwargs.get("ping_interval", 20.0)
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(self.url, heartbeat=heartbeat)
        except Exception:
            await self._session.close()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def send(self, data: str | bytes) -> None:
        if isinstance(data, bytes):
            await self._ws.send_bytes(data)
        else:
            await self._ws.send_str(data)

    async def recv(self) -> str | bytes:
        import aiohttp

        msg = await self._ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT:
            return msg.data
        if msg.type == aiohttp.WSMsgType.BINARY:
            return msg.data
        raise ConnectionError(f"WebSocket kapandı ({msg.type})")

    def __aiter__(self):
        return self

    async def __anext__(self) -> str | bytes:
        import aiohttp

        msg = await self._ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT:
            return msg.data
        if msg.type == aiohttp.WSMsgType.BINARY:
            return msg.data
        raise StopAsyncIteration


def connect(url: str, **kwargs: Any):
    if HAS_NATIVE_WEBSOCKETS:
        return _native_ws.connect(url, **kwargs)
    return _AiohttpWsWrapper(url, **kwargs)
