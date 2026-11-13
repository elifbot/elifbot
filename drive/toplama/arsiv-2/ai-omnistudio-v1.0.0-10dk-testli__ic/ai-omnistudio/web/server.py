"""AI OmniStudio dashboard — canlı koşu panosu (salt okunur).

Güvenlik: yalnız okuma. Emir gönderen, config değiştiren veya anahtar
kabul eden hiçbir uç YOK. Anahtarlar hiçbir zaman istemciye gönderilmez.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omnistudio.ai.registry import registry_status
from omnistudio.core.config import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def latest_run(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    cands = [d for d in runs_dir.iterdir() if d.is_dir()]
    if not cands:
        return None
    return max(cands, key=lambda d: d.stat().st_mtime)


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def tail_jsonl(p: Path, n: int = 60) -> list[dict]:
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def build_app(runs_dir: Path) -> web.Application:
    app = web.Application()

    async def index(_req):
        f = ROOT / "web" / "index.html"
        if f.exists():
            return web.Response(text=f.read_text(encoding="utf-8"),
                                content_type="text/html")
        return web.Response(text="dashboard yok", status=404)

    async def api_state(_req):
        run = latest_run(runs_dir)
        if run is None:
            return web.json_response({"available": False,
                                      "message": "Henüz koşu yok"})
        health = tail_jsonl(run / "health.jsonl", 1)
        result = read_json(run / "SONUC.json")
        decisions = tail_jsonl(run / "decisions.jsonl", 40)
        events = tail_jsonl(run / "events.jsonl", 40)
        return web.json_response({
            "available": True, "run_id": run.name,
            "finished": result is not None,
            "health": health[-1] if health else {},
            "result": result, "decisions": decisions, "events": events,
            "ai_registry": registry_status(),
        })

    async def api_runs(_req):
        if not runs_dir.exists():
            return web.json_response({"runs": []})
        rows = []
        for d in sorted(runs_dir.iterdir(), key=lambda x: x.stat().st_mtime,
                        reverse=True):
            if not d.is_dir():
                continue
            r = read_json(d / "SONUC.json")
            rows.append({
                "run_id": d.name,
                "status": (r or {}).get("run_status", "RUNNING"),
                "mode": (r or {}).get("mode", "?"),
                "closed_trades": ((r or {}).get("execution") or {}).get("closed_trades"),
                "net": ((r or {}).get("execution") or {}).get("closed_net_total"),
            })
        return web.json_response({"runs": rows})

    async def api_providers(_req):
        return web.json_response(registry_status())

    async def api_report(req):
        name = req.match_info["run_id"]
        if "/" in name or ".." in name:
            raise web.HTTPBadRequest()
        f = runs_dir / name / "RAPOR.md"
        if not f.exists():
            raise web.HTTPNotFound()
        return web.Response(text=f.read_text(encoding="utf-8"),
                            content_type="text/plain", charset="utf-8")

    app.router.add_get("/", index)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/runs", api_runs)
    app.router.add_get("/api/providers", api_providers)
    app.router.add_get("/api/report/{run_id}", api_report)
    return app


def main() -> int:
    p = argparse.ArgumentParser(description="AI OmniStudio salt okunur pano")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--runs", default=str(ROOT / "runs"))
    args = p.parse_args()
    load_dotenv()
    web.run_app(build_app(Path(args.runs)), host=args.host, port=args.port,
                print=lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())