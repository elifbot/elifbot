from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import assert_live_allowed, load_config, load_dotenv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tradebot", description="Binance + OKX futures akis botu")
    ap.add_argument("-c", "--config", default="config/config.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config", help="Ayarlari dogrula")
    sim = sub.add_parser("simulate", help="Cevrimdisi sentetik simulasyon (ag gerektirmez)")
    sim.add_argument("--minutes", type=int, default=120)
    sim.add_argument("--seed", type=int, default=7)
    sub.add_parser("universe", help="Taranacak coin listesini goster (ag gerekir)")
    sub.add_parser("run", help="Botu calistir (mode: paper | testnet | live)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    import os
    cfg_path = args.config if os.path.exists(args.config) else "config/config.example.yaml"
    cfg = load_config(cfg_path)

    if args.cmd == "check-config":
        print(f"OK  mode={cfg.mode}  stop mesafesi=%{cfg.stop_distance*100:.2f}  config={cfg_path}")
        return 0
    if args.cmd == "simulate":
        from .simulate import run_simulation
        logging.getLogger().setLevel(logging.WARNING)
        eng = asyncio.run(run_simulation(cfg, seconds=args.minutes * 60, seed=args.seed))
        print(eng.summary())
        return 0
    from .app import run_universe, run_bot
    if args.cmd == "universe":
        return asyncio.run(run_universe(cfg))
    assert_live_allowed(cfg)
    return asyncio.run(run_bot(cfg))


if __name__ == "__main__":
    sys.exit(main())
