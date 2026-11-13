"""AI OmniStudio komut satırı arayüzü."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# paket kökünü yola ekle (kurulum gerektirmeden çalışır)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omnistudio import __version__
from omnistudio.ai.registry import registry_status
from omnistudio.core.config import Config, ConfigError, load_dotenv
from omnistudio.core.types import Mode
from omnistudio.reporting.report import write_reports
from omnistudio.runtime.engine import Engine


def cmd_providers(args: argparse.Namespace) -> int:
    load_dotenv()
    st = registry_status()
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    print(f"\n20 YZ SAĞLAYICI KAYIT DEFTERİ — {st['configured']}/{st['total']} anahtarlı")
    print(f"Konsey modu: {st['mode']}\n")
    print(f"{'#':<3} {'Sağlayıcı':<28} {'Rol':<9} {'Anahtar':<10} {'Ortam değişkeni'}")
    print("-" * 92)
    for i, p in enumerate(st["providers"], 1):
        mark = "VAR" if p["configured"] else "yok"
        print(f"{i:<3} {p['label']:<28} {p['role']:<9} {mark:<10} {p['env_key']}")
    print(f"\n{st['honesty_note']}")
    print("\nAnahtar eklemek için: .env dosyasına OPENAI_API_KEY=... gibi satırlar yazın.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    overrides: dict = {"run": {}, "council": {}}
    if args.duration is not None:
        overrides["run"]["duration_sec"] = args.duration
    if args.drain is not None:
        overrides["run"]["drain_sec"] = args.drain
    if args.symbols is not None:
        overrides["run"]["symbols_per_venue"] = args.symbols
    if args.venues:
        overrides["run"]["venues"] = [v.strip() for v in args.venues.split(",")]
    if args.mode:
        overrides["run"]["mode"] = Mode(args.mode.upper())
    if args.no_ws:
        overrides["run"]["use_websocket"] = False
    if args.no_council:
        overrides["council"]["enabled"] = False
    if args.out:
        overrides["run"]["out_dir"] = args.out
    if args.run_id:
        overrides["run"]["run_id"] = args.run_id
    try:
        cfg = Config.load(args.config, overrides)
    except ConfigError as e:
        print(f"YAPILANDIRMA HATASI: {e}", file=sys.stderr)
        return 2
    engine = Engine(cfg)
    try:
        result = asyncio.run(engine.run())
    except KeyboardInterrupt:
        print("\nKullanıcı durdurdu.", file=sys.stderr)
        return 130
    write_reports(engine.out, result)
    ex = result["execution"]
    print("\n" + "=" * 68)
    print(f"DURUM: {result['run_status']}   MOD: {result['mode']}")
    print(f"Tick: {result['counters']['ticks']}  Sinyal: {result['counters']['signals']}  "
          f"Kabul: {result['counters']['accepted']}  Ret: {result['counters']['rejected']}")
    print(f"Kapanan işlem: {ex['closed_trades']}  Net: {ex['closed_net_total']:+.6f} USDT")
    print(f"Equity: {ex['equity']['total_equity']:.6f} USDT "
          f"(açık unrealized {ex['equity']['unrealized']:+.6f})")
    print(f"Konsey: {result['ai_council']['mode']}  "
          f"Boşluk: {result['continuity']['gap_count']}")
    print(f"Rapor: {engine.out}/RAPOR.md")
    print("Gerçek borsa emri gönderilmedi. Kârlılık iddiası yok.")
    print("=" * 68)
    return 0 if result["run_status"] == "COMPLETED" else 1


def cmd_check(args: argparse.Namespace) -> int:
    """Ağ gerektirmeyen hızlı bütünlük kontrolü."""
    from omnistudio.execution.live_guard import LiveTradingBlocked, assert_mode_allowed
    from omnistudio.strategy.price_history import (PriceHistory,
                                                   linear_first_at_or_after)
    import random
    load_dotenv()
    print(f"AI OmniStudio {__version__} — bütünlük kontrolü\n")
    ok = True

    cfg = Config.load(args.config)
    print(f"[OK] Config doğrulandı (mod={cfg.run.mode.value})")

    try:
        assert_mode_allowed(Mode.LIVE)
        print("[HATA] LIVE kilidi çalışmıyor!")
        ok = False
    except LiveTradingBlocked:
        print("[OK] LIVE mod kilidi aktif — gerçek emir yolu kapalı")

    st = registry_status()
    print(f"[OK] {st['total']} YZ sağlayıcı kayıtlı, {st['configured']} anahtarlı "
          f"→ {st['mode']}")
    if st["total"] != 20:
        ok = False

    rng = random.Random(7)
    mismatch = 0
    for trial in range(200):
        n = rng.randint(1, 300)
        ts = [rng.randint(0, 5000) for _ in range(n)]
        if trial % 2 == 0:
            ts.sort()
        rows = [(t, 100.0 + i) for i, t in enumerate(ts)]
        ph = PriceHistory(maxlen=rng.choice([16, 64, 512]))
        for t, p in rows:
            ph.append(t, p)
        kept = rows[-ph._maxlen:]
        for _ in range(5):
            thr = rng.randint(-100, 5100)
            if ph.first_at_or_after(thr) != linear_first_at_or_after(kept, thr):
                mismatch += 1
    if mismatch:
        print(f"[HATA] PriceHistory eşdeğerliği bozuk: {mismatch} uyuşmazlık")
        ok = False
    else:
        print("[OK] PriceHistory 1000 aramada eski doğrusal aramayla birebir eşdeğer")

    print("\nSONUÇ:", "TEMİZ" if ok else "SORUN VAR")
    return 0 if ok else 1


def cmd_report(args: argparse.Namespace) -> int:
    d = Path(args.run_dir)
    f = d / "SONUC.json"
    if not f.exists():
        print(f"SONUC.json bulunamadı: {f}", file=sys.stderr)
        return 2
    result = json.loads(f.read_text(encoding="utf-8"))
    out = write_reports(d, result)
    print(f"Rapor yenilendi: {out['markdown']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="omnistudio",
        description="AI OmniStudio — 20 YZ konseyli PAPER kripto araştırma botu")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="PAPER koşusu başlat (gerçek piyasa verisi)")
    r.add_argument("--config", help="JSON config yolu")
    r.add_argument("--duration", type=float, help="Aktif süre (saniye)")
    r.add_argument("--drain", type=float, help="Drenaj süresi (saniye)")
    r.add_argument("--symbols", type=int, help="Borsa başına sembol sayısı")
    r.add_argument("--venues", help="Virgülle: binance_vision,gateio,mexc,bitget")
    r.add_argument("--mode", choices=["paper", "observe"], default=None)
    r.add_argument("--no-ws", action="store_true", help="WS yerine REST poll")
    r.add_argument("--no-council", action="store_true", help="Konseyi devre dışı bırak")
    r.add_argument("--out", help="Çıktı kök dizini")
    r.add_argument("--run-id", help="Koşu kimliği")
    r.set_defaults(func=cmd_run)

    pr = sub.add_parser("providers", help="20 YZ sağlayıcı durumunu göster")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_providers)

    c = sub.add_parser("check", help="Ağsız bütünlük kontrolü")
    c.add_argument("--config")
    c.set_defaults(func=cmd_check)

    rp = sub.add_parser("report", help="Var olan koşudan raporu yenile")
    rp.add_argument("run_dir")
    rp.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())