"""Sadece Arena canlı önizlemesi için: panele X-Dashboard-Token ekleyen küçük ters vekil.

Üretimde buna gerek yoktur; tarayıcıdan doğrudan panele bağlanıp token'ı
tarayıcı tarafında girmeniz yeterlidir. Çalıştırma:
    PREVIEW_TOKEN=<DASHBOARD_TOKEN> python3 preview_proxy.py
"""
from __future__ import annotations

import os

import aiohttp
from aiohttp import web

PANEL = os.getenv("PANEL_URL", "http://127.0.0.1:8501")
TOKEN = os.getenv("PREVIEW_TOKEN", "")
PORT = int(os.getenv("PREVIEW_PORT", "8600"))
HOP = {"host", "content-length", "transfer-encoding", "connection", "accept-encoding"}


async def proxy(request: web.Request) -> web.StreamResponse:
    url = PANEL + request.rel_url.raw_path_qs
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers["X-Dashboard-Token"] = TOKEN
    body = await request.read()
    async with aiohttp.ClientSession() as s:
        async with s.request(request.method, url, headers=headers, data=body or None) as r:
            resp_headers = {k: v for k, v in r.headers.items() if k.lower() not in HOP}
            out = web.StreamResponse(status=r.status, headers=resp_headers)
            await out.prepare(request)
            async for chunk in r.content.iter_chunked(65536):
                await out.write(chunk)
            await out.write_eof()
            return out


app = web.Application()
app.router.add_route("*", "/{tail:.*}", proxy)
web.run_app(app, host="0.0.0.0", port=PORT, print=None)
